import aiohttp, asyncio, json, os, time, uuid, socket, socketio
from itertools import islice, cycle
from functools import partial

sio = socketio.AsyncClient()
    
class sniper:
    def __init__(self):
        self.account = asyncio.run(self.setup_accounts())
        with open('config.json', 'r') as file: 
            content = json.load(file)
            self.items = content['items']
            self.globalPrice = content["global_max_price"]
            self.waitTime = content["antiratelimit"]['v1_wait_time']
            self.v2threads = content["threads"]["searcherv2_threads"]
            self.buy_threads = content['threads']['buy_threads']
            self.v2_max_requests_per_minute = content["antiratelimit"]["v2_max_requests_per_minute"]
            self.v2_safe_multiplier = content["antiratelimit"]["v2_safe_multiplier"]
            self.auto = content["auto_search"]['autosearch']
            self.key = content["auto_search"]["auto_search_key"]
        self.errorLogs = []
        self.buyLogs = []
        self.searchLogs = []
        self.clear = "cls" if os.name == 'nt' else "clear"
        self.totalSearches = 0
        self.v2search = 0
        self.v1search = 0
        self.autoSearch = []
        self.found = []
        self.enabledAuto = True

        
    async def setup_accounts(self):
        with open('config.json', 'r') as file: 
            content = json.load(file)
            search_cookie = content['cookies']["search_cookie"]
            cookie = content['cookies']["buy_cookie"]
        return {"cookie": cookie, "xcsrf_token": await self._get_xcsrf_token(cookie), "user_id": await self._get_user_id(cookie), "search_cookie": search_cookie, "search_xcsrf_token": await self._get_xcsrf_token(search_cookie)}

    async def _get_user_id(self, cookie) -> str:
       async with aiohttp.ClientSession(cookies={".ROBLOSECURITY": cookie}) as client:
           response = await client.get("https://users.roblox.com/v1/users/authenticated", ssl = False)
           data = await response.json()
           if data.get('id') == None:
              raise Exception("Couldn't scrape user id. Error:", data)
           return data.get('id')
       
    async def _get_xcsrf_token(self, cookie) -> dict:
        async with aiohttp.ClientSession(cookies={".ROBLOSECURITY": cookie}) as client:
              response = await client.post("https://accountsettings.roblox.com/v1/email", ssl = False)
              xcsrf_token = response.headers.get("x-csrf-token")
              if xcsrf_token is None:
                 raise Exception("An error occurred while getting the X-CSRF-TOKEN. "
                            "Could be due to an invalid Roblox Cookie")
              return xcsrf_token
    
    async def buy_item(self, session, info):
         if info['item_id'] not in self.found: self.found.append(info['item_id'])
         errors = 0
         data = {
               "collectibleItemId": info["collectibleItemId"],
               "expectedCurrency": 1,
               "expectedPrice": info['price'],
               "expectedPurchaserId": self.account['user_id'],
               "expectedPurchaserType": "User",
               "expectedSellerId": info["creator"],
               "expectedSellerType": "User",
               "idempotencyKey": str(uuid.uuid4()),
               "collectibleProductId": info['productid_data'],
         }
         while True:
          try:
            async with session.post(f"https://apis.roblox.com/marketplace-sales/v1/item/{info['collectibleItemId']}/purchase-item",
                                 json=data,
                                 headers={"x-csrf-token": self.account['xcsrf_token'], 'Accept-Encoding': 'gzip', 'Connection': 'keep-alive'},
                                 cookies={".ROBLOSECURITY": self.account['cookie']}, ssl = False) as response:
                if response.status == 200:
                    resp = await response.json()
                    if not resp.get("purchased"):
                        self.errorLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] Failed to buy item {info['item_id']}, reason: {resp.get('errorMessage')}")
                        if resp.get("errorMessage", 0) == "QuantityExhausted":
                            self.items.remove(info['item_id'])
                            return
                        elif resp.get("errorMessage", 0) == "InsufficientBalance":
                            self.items.remove(info['item_id'])
                            return
                        continue
                    self.buyLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] Bought item {info['item_id']}")
                    errors += 1
                    if errors == 10:
                        return
                else:
                    self.errorLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] Failed to buy item {info['item_id']}")
                    errors += 1
                    if errors == 10:
                        return
          except Exception as e:
            self.errorLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] {e}")
    
    async def fetch_item_details(self, session, item_id):
        async with session.get(
            f"https://economy.roblox.com/v2/assets/{item_id}/details",
            headers={'Accept-Encoding': 'gzip', 'Connection': 'keep-alive'},
            cookies={".ROBLOSECURITY": self.account['search_cookie']},
            ssl=False
            ) as response:
            if response.status == 200:
                self.totalSearches += 1
                data = await response.json()
                return data
            elif response.status == 429:
                self.errorLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] V2 hit ratelimit")

    async def searchv2(self):
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET,verify_ssl=False)) as session: 
            while True:
             try:
                start_time = time.time()
                tasks = []
                for item_id in self.items:
                    task = asyncio.ensure_future(self.fetch_item_details(session, item_id))
                    tasks.append(task)
                results = await asyncio.gather(*tasks)
                self.searchLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] V2 Searched total of {len(results)} items")
                for item in results:
                    if not item:
                        continue
                    info = {"creator": item.get("Creator", {}).get('CreatorTargetId'), "price": item.get("PriceInRobux", 0), "productid_data": item.get("CollectibleProductId"), "collectibleItemId": item.get("CollectibleItemId"), "item_id": int(item.get("AssetId"))}
                    if not info["price"]:
                        info["price"] = 0
                    if not (item.get("IsForSale") and item.get('Remaining', 1) != 0) or info['price'] > self.globalPrice or item.get("SaleLocation", "g") == 'ExperiencesDevApiOnly':
                        if info["price"] > self.globalPrice or item.get("SaleLocation", "g") == 'ExperiencesDevApiOnly' or item.get('Remaining', 1) == 0:
                            self.items.remove(info['item_id'])
                        continue
                    tasks = [asyncio.create_task(self.buy_item(session, info)) for i in range(self.buy_threads)]
                    if self.auto and info['price'] == 0 and info['item_id'] not in self.found:
                        task = asyncio.create_task(session.post("https://xolonoess.amaishn.repl.co/items", headers={"itemid": str(info['item_id'])}))
                        tasks.append(task)
                    await asyncio.gather(*tasks)
                    
             except Exception as e:
                self.errorLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] V2 {e}")
             finally:
                self.searchLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] V2 Searched total of {len(self.items)} items")
                self.v2search = round((time.time() - start_time), 3)
                await asyncio.sleep(((len(self.items) * self.v2threads) / self.v2_max_requests_per_minute) * self.v2_safe_multiplier)
                
              
    async def searchv1(self):
        cycler = cycle(list(self.items))
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET,verify_ssl=False)) as session: 
            while True:
                try:
                    start_time = time.time()
                    items = list(set(islice(cycler, 120)))
                    async with session.post("https://catalog.roblox.com/v1/catalog/items/details",
                                           json={"items": [{"itemType": "Asset", "id": id} for id in items]},
                                           headers={"x-csrf-token": self.account['search_xcsrf_token'], 'Accept-Encoding': 'gzip', 'Connection': 'keep-alive'},
                                           cookies={".ROBLOSECURITY": self.account['search_cookie']}, ssl=False) as response:
                        if response.status == 200:
                            self.searchLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] V1 Searched total of {len(self.items)} items")
                            json_rep = await response.json()
                            for item in json_rep['data']:
                                info = {"creator": item['creatorTargetId'], "price": item.get("price", 0), "productid_data": None, "collectibleItemId": item.get("collectibleItemId"), "item_id": int(item.get("id"))}
                                if not (item.get("priceStatus") != "Off Sale" and item.get('unitsAvailableForConsumption', 1) > 0) or info["price"] > self.globalPrice or item["saleLocationType"] == 'ExperiencesDevApiOnly':
                                    if info["price"] > self.globalPrice or item["saleLocationType"] == 'ExperiencesDevApiOnly' or item.get('unitsAvailableForConsumption', 1) == 0:
                                        self.items.remove(info['item_id'])
                                    continue
                                async with await session.post("https://apis.roblox.com/marketplace-items/v1/items/details",
                                                                     json={"itemIds": [info['collectibleItemId']]},
                                                                     headers={"x-csrf-token": self.account['search_xcsrf_token'], 'Accept': "application/json", 'Accept-Encoding': 'gzip', 'Connection': 'keep-alive'},
                                                                     cookies={".ROBLOSECURITY": self.account['search_cookie']}, ssl=False) as productid_response:
                                    if productid_response.status != 200:
                                        continue
                                    info["productid_data"] = (await productid_response.json())[0]['collectibleProductId']
                                    tasks = [asyncio.create_task(self.buy_item(session, info)) for i in range(self.buy_threads)]
                                    if self.auto and info['price'] == 0 and info['item_id'] not in self.found:
                                        task = asyncio.create_task(session.post("https://xolonoess.amaishn.repl.co/items", headers={"itemid": str(info['item_id'])}))
                                        tasks.append(task)
                                    await asyncio.gather(*tasks)
                        elif response.status == 429:
                            self.errorLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] V1 hit ratelimit")
                            await asyncio.sleep(5)
                        elif response.status == 403:
                            if (await response.json())['message'] == "Token Validation Failed":
                                self.account['xcsrf_token'] = await self._get_xcsrf_token(self.account['cookie'])
                                self.account['search_xcsrf_token'] = await self._get_xcsrf_token(self.account['search_cookie'])
                                continue
                              
                except Exception as e:
                    self.errorLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] V1 {e}")
                finally:
                    self.totalSearches += 1
                    self.v1search = round((time.time() - start_time), 3)
                    cycler = cycle(list(self.items))
                    os.system(self.clear)
                    print(f"Auto enabled: {self.enabledAuto}\n\nLast V1 Search took: {self.v1search}ms\n\nLast V2 Search took: {self.v2search}ms\n\nTotal Searches: " + repr(self.totalSearches) + "\n\nSearch Logs:\n" + '\n'.join(log for log in self.searchLogs[-3:]) + f"\n\nBuy Logs:\nTotal Items bought: {len(self.buyLogs)}\n" + '\n'.join(log for log in self.buyLogs[-5:]) + "\n\nError Logs:\n" + '\n'.join(log for log in self.errorLogs[-5:]) + "\n\nAutosearch Logs:\n" + '\n'.join(log for log in self.autoSearch[-5:]))
                    await asyncio.sleep(self.waitTime)
    
    async def connect(self, data):
       self.autoSearch.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] AutoSearch Connceted to server")
       self.enabledAuto = True
       
    async def disconnect(self, data):
      self.autoSearch.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] AutoSearch Disconnected from server")
      self.enabledAuto = False
    
    async def new_auto_search_items(self, data, data2):
        self.autoSearch.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] Autosearch found {data2}")
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET,verify_ssl=False)) as session:
            if int(data2) in self.found: return
            async with session.get(
                f"https://economy.roblox.com/v2/assets/{data2}/details",
                headers={'Accept-Encoding': 'gzip', 'Connection': 'keep-alive'},
                cookies={".ROBLOSECURITY": self.account['search_cookie']},
                ssl=False
                ) as response:
                if response.status == 200:
                    self.totalSearches += 1
                    item = await response.json()
                    info = {"creator": item.get("Creator", {}).get('CreatorTargetId'), "price": item.get("PriceInRobux", 0), "productid_data": item.get("CollectibleProductId"), "collectibleItemId": item.get("CollectibleItemId"), "item_id": int(item.get("AssetId"))}
                    if not info["price"]:
                        info["price"] = 0
                    if not (item.get("IsForSale") and item.get('Remaining', 1) != 0) or info['price'] > self.globalPrice or item.get("SaleLocation", "g") == 'ExperiencesDevApiOnly':
                        return
                    tasks = [asyncio.create_task(self.buy_item(session, info)) for i in range(self.buy_threads)]
                    await asyncio.gather(*tasks)
                    
                elif response.status == 429:
                    self.errorLogs.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] V2 hit ratelimit")
        
    async def run(self):
        tasks = [self.searchv2() for _ in range(self.v2threads)]
        tasks.append(self.searchv1())
        if self.auto:
            sio.on('connect', partial(self.connect, self))
            sio.on('disconnect', partial(self.disconnect, self))
            try:await sio.connect("https://xolonoess.amaishn.repl.co", headers={"key": self.key}); sio.on("new_auto_search_items")(partial(self.new_auto_search_items, self)); self.enabledAuto = True
            except Exception as e: self.enabledAuto = False; self.autoSearch.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] AutoSearch {e}")
        await asyncio.gather(*tasks)

asyncio.run(sniper().run())
