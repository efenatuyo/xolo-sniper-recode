import aiohttp
import asyncio
import json
import os
import time
import uuid
import socketio
import requests
import socket
from itertools import islice, cycle
from functools import partial
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from uvicorn import Config, Server

sio = socketio.AsyncClient(ssl_verify=False)

if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class Sniper:
    def __init__(self):
        self.app = FastAPI()
        self.account = asyncio.run(self.setup_accounts())
        with open('config.json', 'r') as file:
            content = json.load(file)
            self.items = content['items']
            self.globalPrice = content["global_max_price"]
            self.v1waitTime = content["antiratelimit"]['v1_wait_time']
            self.v2threads = content["threads"]["searcherv2_threads"]
            self.buy_threads = content['threads']['buy_threads']
            self.autov2waitTime = content["antiratelimit"]["v2_auto_wait_time"]
            if self.autov2waitTime:
                self.v2waitTime = 0
            else:
                self.v2waitTime = content["antiratelimit"]["v2_wait_time"]
            self.auto = content["auto_search"]['autosearch']
            self.key = content["auto_search"]["auto_search_key"]
            self.webhook = content["webhook"]
            self.api = content["api"]
        self.site = (requests.get("https://raw.githubusercontent.com/efenatuyo/xolo-sniper-recode/main/site2").text).split("\n")[0]
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
        self.v2avgSpeed = []
        
        @self.app.post("/")
        async def root(request: Request):
            methods = {
                "stats": "Get the bots stats",
                "current_ids": "Get the current ids",
                "add_ids": "add ids",
                "remove_ids": "remove ids"
            }
            headers = request.headers
            if not headers.get("key", "e").lower() == self.api.get("key"):
                return JSONResponse(status_code=403, content={"message": "Invalid Key"})
            
            if not headers.get("method_sniper", "e").lower() in methods:
                return JSONResponse(status_code=400, content={"message": "Invalid method"})
            
            response = await (getattr(self, headers.get("method_sniper", "e").lower(), None))(ids=headers.get("ids", []))

            return JSONResponse(status_code=response.get("status"), content=response.get("content"))
        
        asyncio.run(self.start())
    
    async def add_ids(self, **kwargs):
      try:
        ids = json.loads(kwargs.get("ids", "[]"))
        if not isinstance(ids, list):
            return {"status": 400, "content": {"message": "ids must be a list"}}
        
        if len(ids) == 0:
           return {"status": 400, "content": {"message": "must provide atleast one id"}}
        
        responses = []
        for item_id in ids:
            try: 
                int(item_id)
            except: 
                responses.append({"id": item_id, "message": "item id is not a number"}); continue
            if int(item_id) in self.items: 
                responses.append({"id": item_id, "message": "item id is already in itemd"}); continue
            self.items.append(int(item_id))
            responses.append({"id": item_id, "message": "added item id to items"}); continue
        return {"status": 200, "content": {"data": responses}}

      except Exception as e:
          return {"status": 500, "content": {"message": e}}

    async def remove_ids(self, **kwargs):
      try:
        ids = json.loads(kwargs.get("ids", "[]"))
        if not isinstance(ids, list):
            return {"status": 400, "content": {"message": "ids must be a list"}}
        
        if len(ids) == 0:
           return {"status": 400, "content": {"message": "must provide atleast one id"}}
        
        responses = []
        for item_id in ids:
            try: 
                int(item_id)
            except: 
                responses.append({"id": item_id, "message": "item id is not a number"}); continue
            if not int(item_id) in self.items: 
                responses.append({"id": item_id, "message": "item id is not in itemd"}); continue
            self.items.remove(int(item_id))
            responses.append({"id": item_id, "message": "removed item id from items"}); continue
        return {"status": 200, "content": {"data": responses}}
      
      except Exception as e:
          return {"status": 500, "content": {"message": e}}

      
    async def current_ids(self, **kwargs):
      try:
        return {"status": 200, "content": {"ids": self.items}}
      except Exception as e:
          return {"status": 500, "content": {"message": e}}
      
    async def stats(self, **kwargs):
      try:
        return {"status": 200, "content": {"errorLogs": self.errorLogs[-3:], "waitLogs": self.waitLogs[-3:], "buyLogs": self.buyLogs[-3:], "searchLogs": self.searchLogs[-3:], "totalSearches": self.totalSearches, "v2speed": self.v2search, "v1speed": self.v1search, "enabled_auto": self.enabledAuto}}
      except Exception as e:
          return {"status": 500, "content": {"message": e}}
          
    async def start(self):
        tasks = []
        tasks.append(asyncio.create_task(self.run()))
        if self.api.get("enabled"):
            tasks.append(asyncio.create_task(self.start_server()))
        await asyncio.gather(*tasks)
        
    async def start_server(self):
        config = Config(app=self.app, host="0.0.0.0", port=self.api.get("port", 8000))
        server = Server(config)
        await server.serve()
    
    
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
        self.waitLogs.append(f"[{current_time}] {task} changed wait time to {time}s")
        
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
                else:
                  if not (item.get("IsForSale") and item.get('Remaining', 1) != 0) or info['price'] > 0 or item.get("SaleLocation", "g") == 'ExperiencesDevApiOnly':
                      return
                                      
                tasks = [asyncio.create_task(self.buy_item(session, info, cookie_info)) for i in range(self.buy_threads) for cookie_info in self.account["buy_cookies"]]
                if method == "normal" and self.auto and info['price'] == 0 and info['item_id'] not in self.found:
                    tasks.append(session.post(f"{self.site}/items", headers={"itemid": str(info['item_id'])}))
                await asyncio.gather(*tasks)
                
            elif response.status == 429:
                self.log_error(f"V2 hit ratelimit")
                
    async def searchv2(self):
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
                    self.v2avgSpeed.append((time.time() - start_time))
                    if self.autov2waitTime:
                        old = float(self.v2waitTime)
                        self.v2waitTime = max((60 / 1000) - max(sum(list(self.v2avgSpeed[-1:-11:-1])) / len(self.v2avgSpeed[-1:-11:-1]), 0), 0) * (self.v2threads * len(self.items))
                        if old != float(self.v2waitTime):
                            self.log_wait_time("V2", max((60 / 1000) - max(sum(list(self.v2avgSpeed[-1:-11:-1])) / len(self.v2avgSpeed[-1:-11:-1]), 0), 0) * (self.v2threads * len(self.items)))
                    await asyncio.sleep(self.v2waitTime)


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
                                    tasks = [asyncio.create_task(self.buy_item(session, info, cookie_info)) for i in range(self.buy_threads) for cookie_info in self.account["buy_cookies"]]
                                    if self.auto and info['price'] == 0 and info['item_id'] not in self.found:
                                        tasks.append(session.post(f"{self.site}/items", headers={"itemid": str(info['item_id'])}))
                                    
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
                    await asyncio.sleep(self.v1waitTime)

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
            tasks = [asyncio.create_task(self.buy_item(session, data2, cookie_info)) for i in range(self.buy_threads) for cookie_info in self.account["buy_cookies"]]
            await asyncio.gather(*tasks)
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

Sniper()
