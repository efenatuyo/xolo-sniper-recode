import aiohttp
import asyncio
import json
import os
import time
import uuid
import socketio
import requests
import socket
import random
from itertools import islice, cycle
from functools import partial

sio = socketio.AsyncClient(ssl_verify=False)

if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class Sniper:
    def __init__(self):
        self.account = asyncio.run(self.setup_accounts())
        with open('config.json', 'r') as file:
            content = json.load(file)
            self.items = content['items']
            self.globalPrice = content["global_max_price"]
            self.waitTime = content["antiratelimit"]['v1_wait_time']
            self.v2threads = content["threads"]["searcherv2_threads"]
            self.buy_threads = content['threads']['buy_threads']
            self.v2_max_requests_per_minute = content["antiratelimit"]["v2_max_requests_per_minute"] / self.v2threads
            self.auto = content["auto_search"]['autosearch']
            self.key = content["auto_search"]["auto_search_key"]
            self.webhook = content["webhook"]
        self.site = (requests.get("https://raw.githubusercontent.com/efenatuyo/xolo-sniper-recode/main/site").text).split("\n")[0]
        self.errorLogs = []
        self.waitLogs = []
        self.buyLogs = []
        self.searchLogs = []
        self.clear = "cls" if os.name == 'nt' else "clear"
        self.totalSearches = 0
        self.v2search = 0
        self.v1search = 0
        self.autoSearch = []
        self.found = []
        self.enabledAuto = False

    async def setup_accounts(self):
        with open('config.json', 'r') as file:
            content = json.load(file)
            search_cookie = content['cookies']["search_cookie"]
            cookiee = content['cookies']["buy_cookie"]
        return {"buy_cookies": [{"cookie": cookie, "xcsrf_token": await self._get_xcsrf_token(cookie), "user_id": (await self._get_user_info(cookie))["id"], "user_name": (await self._get_user_info(cookie))["name"]} for cookie in cookiee], "search_cookie": search_cookie, "search_xcsrf_token": await self._get_xcsrf_token(search_cookie)}

    async def _get_user_info(self, cookie) -> str:
        async with aiohttp.ClientSession(cookies={".ROBLOSECURITY": cookie}) as client:
            response = await client.get("https://users.roblox.com/v1/users/authenticated", ssl=False)
            data = await response.json()
            if data.get('id') is None or data.get('name') is None:
                raise Exception("Couldn't scrape user info. Error:", data)
            return {"id": data.get('id'), "name": data.get("name")}

        
    async def _get_xcsrf_token(self, cookie) -> dict:
        async with aiohttp.ClientSession(cookies={".ROBLOSECURITY": cookie}) as client:
            response = await client.post("https://accountsettings.roblox.com/v1/email", ssl=False)
            xcsrf_token = response.headers.get("x-csrf-token")
            if xcsrf_token is None:
                raise Exception("An error occurred while getting the X-CSRF-TOKEN. Could be due to an invalid Roblox Cookie")
            return xcsrf_token

    def log_wait_time(self, task, time):
        current_time = self.get_current_time()
        self.waitLogs.append(f"[{current_time}] {task} sleeping {time}s")
        
    def log_error(self, message):
        current_time = self.get_current_time()
        self.errorLogs.append(f"[{current_time}] {message}")

    def log_purchase(self, item_id, serial):
        current_time = self.get_current_time()
        self.buyLogs.append(f"[{current_time}] Bought item {item_id}, serial {serial}")

    def log_search(self, message):
        current_time = self.get_current_time()
        self.searchLogs.append(f"[{current_time}] {message}")
    
    def log_auto(self, message):
        current_time = self.get_current_time()
        self.autoSearch.append(f"[{current_time}] {message}")
        
    def get_current_time(self):
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

    async def serial(self, account, asset_type, item_id):
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)) as session:
            try:
                async with session.get(f"https://inventory.roblox.com/v2/users/{account['user_id']}/inventory/{asset_type}?limit=10&sortOrder=Desc", cookies={".ROBLOSECURITY": account["cookie"]}) as response:
                    for item_data in (await response.json())["data"]:
                        if int(item_data["assetId"]) == int(item_id):
                            return item_data["serialNumber"]
                    return "not found"
            except Exception as e:
                return e

    async def image_url(self, item_id):
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)) as session:
            try:
                async with session.get(f"https://thumbnails.roblox.com/v1/assets?assetIds={item_id}&size=250x250&format=png") as response:
                    return (await response.json())["data"][0]['imageUrl']
            except Exception as e:
                return e
            
        
    async def buy_item(self, session, info, cookie_info):
        data = {
            "collectibleItemId": info["collectibleItemId"],
            "expectedCurrency": 1,
            "expectedPrice": info['price'],
            "expectedPurchaserId": cookie_info['user_id'],
            "expectedPurchaserType": "User",
            "expectedSellerId": info["creator"],
            "expectedSellerType": "User",
            "idempotencyKey": str(uuid.uuid4()),
            "collectibleProductId": info['productid_data'],
        }
        print("buy thread started")
        for i in range(10):
            try:
                async with session.post(
                    f"https://apis.roblox.com/marketplace-sales/v1/item/{info['collectibleItemId']}/purchase-item",
                    json=data,
                    headers={"x-csrf-token": cookie_info['xcsrf_token'], 'Accept-Encoding': 'gzip', 'Connection': 'keep-alive'},
                    cookies={".ROBLOSECURITY": cookie_info['cookie']},
                    ssl=False
                ) as response:
                    if response.status == 200:
                        resp = await response.json()
                        if not resp.get("purchased"):
                            self.log_error(f"Failed to buy item {info['item_id']}, full response: {resp}")
                            if resp.get("errorMessage", 0) in ["QuantityExhausted", "InsufficientBalance"]:
                                self.items.remove(info['item_id'])
                            return
                        serial = await self.serial(cookie_info, info["asset_type"], info["item_id"])
                        self.log_purchase(info['item_id'], serial)
                        if self.webhook["enabled"]:
                            async with session.post(self.webhook["url"], json={"embeds": [{"title": f"Bought {info['item_id']}", "url": f"https://www.roblox.com/catalog/{info['item_id']}", "color": 3447003,  "fields": [{"name": f"Price: `{info['price']}`\nSerial: `#{serial}`\nBought from `{cookie_info['user_name']}`","value": "","inline": True}],"thumbnail": {"url": await self.image_url(info['item_id'])}}]}) as response: pass
            except Exception as e:
                self.log_error(f"{e}")
            finally:
                data["idempotencyKey"] = str(uuid.uuid4())

    async def fetch_item_details_v2(self, session, item_id, method="normal"):
        async with session.get(
            f"https://economy.roblox.com/v2/assets/{item_id}/details",
            headers={'Accept-Encoding': 'gzip, deflate', 'Connection': 'keep-alive'},
            cookies={".ROBLOSECURITY": self.account['search_cookie']},
            ssl=False
        ) as response:
            if response.status == 200:
                self.totalSearches += 1
                item = await response.json()
                if not item:
                    return
                info = {"creator": item.get("Creator", {}).get('CreatorTargetId'), "price": item.get("PriceInRobux", 0), "productid_data": item.get("CollectibleProductId"), "collectibleItemId": item.get("CollectibleItemId"), "item_id": int(item.get("AssetId")), "asset_type": item.get("AssetTypeId")}
                if not info["price"]:
                    info["price"] = 0
                tasks = []
                if method == "normal":
                  if not (item.get("IsForSale") and item.get('Remaining', 1) != 0) or info['price'] > self.globalPrice or item.get("SaleLocation", "g") == 'ExperiencesDevApiOnly':
                    if info["price"] > self.globalPrice or item.get("SaleLocation", "g") == 'ExperiencesDevApiOnly' or item.get('Remaining', 1) == 0:
                        self.items.remove(info['item_id'])
                    return
                  if self.auto and info['price'] == 0 and info['item_id'] not in self.found:
                    tasks.append(session.post(f"{self.site}/items", headers={"itemid": str(info['item_id'])}))
                else:
                  if not (item.get("IsForSale") and item.get('Remaining', 1) != 0) or info['price'] > 0 or item.get("SaleLocation", "g") == 'ExperiencesDevApiOnly':
                      return
                                      
                for i in range(self.buy_threads):
                    for cookie_info in self.account["buy_cookies"]:
                        await asyncio.create_task(self.buy_item(session, info, cookie_info))
                await asyncio.gather(*tasks)
                
            elif response.status == 429:
                self.log_error(f"V2 hit ratelimit")
                await asyncio.sleep(random.uniform(0.5, 1.0))
                
    async def searchv2(self):
        request_count = 0
        start_time_x = time.time()
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)) as session:
            while True:
                try:
                    start_time = time.time()
                    if len(self.items) == 0: continue
                    tasks = []
                    for item_id in self.items:
                        tasks.append(self.fetch_item_details_v2(session, item_id))
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                except Exception as e:
                    self.log_error(f"V2 {e}")
                finally:
                    self.log_search(f"V2 Searched a total of {len(self.items)} items")
                    self.v2search = round((time.time() - start_time), 3)
                    elapsed_time = time.time() - start_time
                    request_count += len(self.items)
                    if request_count >= self.v2_max_requests_per_minute:
                        request_count = 0
                        elapsed_time = time.time() - start_time
                        if elapsed_time < 60.0:
                            wait_time = 60.0 - elapsed_time
                            self.log_wait_time("V2", wait_time)
                            await asyncio.sleep(wait_time)
                        start_time = time.time()

    async def searchv1(self):
        cycler = cycle(list(self.items))
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)) as session:
            while True:
                try:
                    start_time = time.time()
                    items = list(set(islice(cycler, 120)))
                    async with session.post(
                        "https://catalog.roblox.com/v1/catalog/items/details",
                        json={"items": [{"itemType": "Asset", "id": id} for id in items]},
                        headers={"x-csrf-token": self.account['search_xcsrf_token'], 'Accept-Encoding': 'gzip, deflate', 'Connection': 'keep-alive'},
                        cookies={".ROBLOSECURITY": self.account['search_cookie']},
                        ssl=False
                    ) as response:
                        if response.status == 200:
                            self.log_search(f"V1 Searched a total of {len(self.items)} items")
                            json_rep = await response.json()
                            for item in json_rep['data']:
                                info = {"creator": item['creatorTargetId'], "price": item.get("price", 0), "productid_data": None, "collectibleItemId": item.get("collectibleItemId"), "item_id": int(item.get("id")), "asset_type": item.get("assetType")}
                                if not (item.get("priceStatus") != "Off Sale" and item.get('unitsAvailableForConsumption', 1) > 0) or info["price"] > self.globalPrice or item["saleLocationType"] == 'ExperiencesDevApiOnly':
                                    if info["price"] > self.globalPrice or item["saleLocationType"] == 'ExperiencesDevApiOnly' or item.get('unitsAvailableForConsumption', 1) == 0:
                                        self.items.remove(info['item_id'])
                                    continue
                                async with await session.post(
                                    "https://apis.roblox.com/marketplace-items/v1/items/details",
                                    json={"itemIds": [info['collectibleItemId']]},
                                    headers={"x-csrf-token": self.account['search_xcsrf_token'], 'Accept': "application/json", 'Accept-Encoding': 'gzip, deflate', 'Connection': 'keep-alive'},
                                    cookies={".ROBLOSECURITY": self.account['search_cookie']},
                                    ssl=False
                                ) as productid_response:
                                    if productid_response.status != 200:
                                        continue
                                    info["productid_data"] = (await productid_response.json())[0]['collectibleProductId']
                                    tasks = []
                                    if self.auto and info['price'] == 0 and info['item_id'] not in self.found:
                                        tasks.append(session.post(f"{self.site}/items", headers={"itemid": str(info['item_id'])}))
                                    
                                    for i in range(self.buy_threads):
                                        for cookie_info in self.account["buy_cookies"]:
                                            await asyncio.create_task(self.buy_item(session, info, cookie_info))
                                    
                                    await asyncio.gather(*tasks)
                        elif response.status == 429:
                            self.log_error(f"V1 hit ratelimit")
                            await asyncio.sleep(5)
                        elif response.status == 403:
                            if (await response.json())['message'] == "Token Validation Failed":
                                for index in range(len(self.account["buy_cookies"])):
                                    self.account['buy_cookies'][index]["xcsrf_token"] = await self._get_xcsrf_token(self.account['buy_cookies'][index]["cookie"])
                                self.account['search_xcsrf_token'] = await self._get_xcsrf_token(self.account['search_cookie'])
                                continue

                except Exception as e:
                    self.log_error(f"V1 {e}")
                finally:
                    self.totalSearches += 1
                    self.v1search = round((time.time() - start_time), 3)
                    cycler = cycle(list(self.items))
                    os.system(self.clear)
                    print(f"Auto enabled: {self.enabledAuto}\n\nLast V1 Search took: {self.v1search}ms\n\nLast V2 Search took: {self.v2search}ms\n\nTotal Searches: {self.totalSearches}\n\nSearch Logs:\n" + '\n'.join(log for log in self.searchLogs[-3:]) + "\n\nWait Logs:\n" + '\n'.join(log for log in self.waitLogs[-3:]) + f"\n\nBuy Logs:\nTotal Items bought: {len(self.buyLogs)}\n" + '\n'.join(log for log in self.buyLogs[-5:]) + "\n\nError Logs:\n" + '\n'.join(log for log in self.errorLogs[-5:]) + "\n\nAutosearch Logs:\n" + '\n'.join(log for log in self.autoSearch[-5:]))
                    await asyncio.sleep(self.waitTime)

    async def connect(self, data):
        self.log_auto("AutoSearch connected to the server")
        self.enabledAuto = True

    async def disconnect(self, data):
        self.log_auto("AutoSearch disconnected from the server")
        self.enabledAuto = False

    async def new_auto_search_items(self, data, data2):
      async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)) as session:
        if isinstance(data2, dict):
            if int(data2['item_id']) in self.found:
                return
            self.log_auto(f"AutoSearch found {data2['item_id']}")
            for i in range(self.buy_threads):
                    for cookie_info in self.account["buy_cookies"]:
                            await asyncio.create_task(self.buy_item(session, data2, cookie_info))
            return
        if int(data2) in self.found:
            return
        self.log_auto(f"AutoSearch found {data2}")
        await self.fetch_item_details_v2(session, data2, method="auto")

    async def run(self):
        tasks = [self.searchv2() for _ in range(self.v2threads)]
        tasks.append(self.searchv1())
        if self.auto:
            sio.on('connect', partial(self.connect, self))
            sio.on('disconnect', partial(self.disconnect, self))
            try:
                await sio.connect(self.site, headers={"key": self.key})
                sio.on("new_auto_search_items")(partial(self.new_auto_search_items, self))
                self.enabledAuto = True
            except Exception as e:
                self.enabledAuto = False
                self.log_auto(f"{e}")
        await asyncio.gather(*tasks)


asyncio.run(Sniper().run())
