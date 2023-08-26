from datetime import datetime, timezone, timedelta
import time
from logger import log, _log, bcolors
import logging
import requests
import functools
from eosapi import NodeException, TransactionException, EosApiException, Transaction
from nonce import Nonce, generate_nonce
from eosapi import EosApi
from typing import List, Dict, Union, Tuple
import random
from settings import user_param, interval
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.ssl_ import create_urllib3_context
import tenacity
from tenacity import wait_fixed, RetryCallState, retry_if_not_exception_type
from requests import RequestException
from dataclasses import dataclass
import math
import random
import re

endpoints = [
    #'https://apiwax.3dkrender.com', contract blacklisted
    #'https://query.3dkrender.com', contract blacklisted
    #'https://api.wax.alohaeos.com',
    'https://wax.eu.eosamsterdam.net',
    'https://wax.blokcrafters.io',
    #'https://api-wax-mainnet.wecan.dev',
    #'https://history-wax-mainnet.wecan.dev',
    #'https://wax.cryptolions.io',
    #'https://wax.dapplica.io',
    #'https://api-wax.eosauthority.com',
    #'https://wax.eosdac.io',
    #'https://wax.eosphere.io',
    'https://api.wax.greeneosio.com',
    #'https://wax.eoseoul.io',
    'https://wax-public1.neftyblocks.com',
    'https://wax-public2.neftyblocks.com',
    'https://api.wax.liquidstudios.io',
    'https://wax.api.eosnation.io',
    #'https://wax.greymass.com',
    #'https://api.waxsweden.org',
    'https://wax-bp.wizardsguild.one',
    #'https://wax.blacklusion.io',
    #'https://api-wax.eosarabia.net',
    #'https://wax.eosusa.io',
    #'https://waxapi.ledgerwise.io'
]

hyperion_endpoints = [
    "https://wax-history.eosdac.io",
    "https://apiwax.3dkrender.com",
    "https://history-wax-mainnet.wecan.dev",
    "https://wax.eosphere.io",
    "https://hyperion-wax-mainnet.wecan.dev",
    "https://hyperion.wax.blacklusion.io",
    "https://wax.eu.eosamsterdam.net"
]


lands = [
    "1099512958342",
    "1099512961496",
    "1099512961479",
    "1099512961393",
    "1099512960515",
    "1099512961238"
]

class CipherAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context(ciphers='DEFAULT:@SECLEVEL=2')
        kwargs['ssl_context'] = context
        return super(CipherAdapter, self).init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context(ciphers='DEFAULT:@SECLEVEL=2')
        kwargs['ssl_context'] = context
        return super(CipherAdapter, self).proxy_manager_for(*args, **kwargs)


class StopException(Exception):
    def __init__(self, msg: str):
        super().__init__(msg)



@dataclass
class HttpProxy:
    proxy: str
    user_name: str = None
    password: str = None

    def to_proxies(self) -> Dict:
        if self.user_name and self.password:
            proxies = {
                "http": "http://{0}:{1}@{2}".format(self.user_name, self.password, self.proxy),
                "https": "http://{0}:{1}@{2}".format(self.user_name, self.password, self.proxy),
            }
        else:
            proxies = {
                "http": "http://{0}".format(self.proxy),
                "https": "http://{0}".format(self.proxy),
            }
        return proxies



class Alien:
    # alien_host = "https://aw-guard.yeomen.ai"

    def __init__(self, wax_account: str, token: str, charge_time: int, claim_delta: int, proxy: HttpProxy = None):
        self.wax_account: str = wax_account
        self.token: str = token
        self.log: logging.LoggerAdapter = logging.LoggerAdapter(_log, {"tag": self.wax_account})
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, " \
                                          "like Gecko) Chrome/101.0.4951.54 Safari/537.36 "
        self.http.trust_env = False
        self.http.request = functools.partial(self.http.request, timeout=60)
        self.http.mount('https://wax-on-api.mycloudwallet.com/wam/sign', CipherAdapter())
        self.api_int = random.randint(0, len(endpoints) - 1)
        self.rpc_host = endpoints[self.api_int]
        self.hyperion = hyperion_endpoints[random.randint(0, len(hyperion_endpoints) - 1)]
        self.eosapi = EosApi(self.rpc_host, timeout=60)
        if user_param.cpu_account and user_param.cpu_key:
            self.eosapi.set_cpu_payer(user_param.cpu_account, user_param.cpu_key, 'mine')

        if proxy:
            proxies = proxy.to_proxies()
            self.http.proxies = proxies
            self.eosapi.session.proxies = proxies

        retry = tenacity.retry(retry = retry_if_not_exception_type(StopException), wait=self.wait_retry, reraise=False)
        self.mine = retry(self.mine)
        self.query_last_mine = retry(self.query_last_mine)

        self.charge_time: int = charge_time
        self.next_mine_time: datetime = None

        self.check_resources: bool = True
        self.cpu_limit: int = 600
        self.net_limit: int = 150

        self.nonce = None
        self.difficulty = 1
        self.mine_count = 0
        self.last_mine = 0
        self.pending_balance = 0
        self.claim_delta: int = claim_delta

        self.trx_error_count = 0
        if user_param.difficulty:
            self.difficulty = user_param.difficulty

    def change_api(self):
        self.api_int += 1

        if self.api_int >= len(endpoints) - 1:
            self.api_int = 0
        
        self.rpc_host = endpoints[self.api_int]
        self.log.info("切换节点：{0}".format(self.rpc_host))
        self.eosapi = EosApi(rpc_host=self.rpc_host, timeout=60)
        if user_param.cpu_account and user_param.cpu_key:
            self.eosapi.set_cpu_payer(user_param.cpu_account, user_param.cpu_key, 'mine')

    def wait_retry(self, retry_state: RetryCallState) -> float:
        exp = retry_state.outcome.exception()
        wait_seconds = interval.transact
        if isinstance(exp, RequestException):
            self.log.error("网络错误: {0}".format(exp))
            self.change_api()
            wait_seconds = interval.net_error
        elif isinstance(exp, NodeException):
            self.log.error((str(exp)))
            self.log.error("节点错误,状态码【{0}】".format(exp.resp.status_code))
            self.change_api()
            wait_seconds = interval.transact
        elif isinstance(exp, TransactionException):
            self.trx_error_count += 1
            self.log.error("交易失败： {0}".format(exp.resp.text))
            if "is greater than the maximum billable" in exp.resp.text:
                self.log.warning("CPU资源不足, 可能需要质押更多WAX, 稍后重试 [{0}]".format(self.trx_error_count))
                wait_seconds = interval.cpu_insufficient
            elif "is not less than the maximum billable CPU time" in exp.resp.text:
                self.log.critical("交易被限制,可能被该节点拉黑 [{0}]".format(self.trx_error_count))
                self.change_api()
                wait_seconds = interval.transact
            elif "NOTHING_TO_MINE" in exp.resp.text:
                self.log.critical("账号可能被封，请手动检查 ERR::NOTHING_TO_MINE")
                raise StopException("账号可能被封")
            elif 'INVALID_HASH' in exp.resp.text:
                self.nonce = None
                self.log.error("INVALID_HASH 错误")
            elif 'is on the contract blacklist' in exp.resp.text:
                self.log.error('合约已被节点拉黑')
                self.change_api()
        else:
            if exp:
                self.log.error("常规错误: {0}".format(exp), exc_info=exp)
            else:
                self.log.error("常规错误")
        if self.trx_error_count >= interval.max_trx_error:
            self.log.critical("交易连续出错[{0}]次，为避免被节点拉黑，脚本停止，请手动检查问题或更换节点".format(self.trx_error_count))
            raise StopException("交易连续出错")
        self.log.info("{0} 秒后重试: [{1}]".format(wait_seconds, retry_state.attempt_number))
        return float(wait_seconds)


    def get_table_rows(self, table: str):
        post_data = {
            "json": True,
            "code": "m.federation",
            "scope": "m.federation",
            "table": table,
            "lower_bound": self.wax_account,
            "upper_bound": self.wax_account,
            "index_position": 1,
            "key_type": "",
            "limit": 10,
            "reverse": False,
            "show_payer": False
        }
        return self.eosapi.get_table_rows(post_data)

    # 采矿
    def mine(self) -> bool:
        last_mine_time, last_mine_tx, time_diff = self.query_last_mine()
        time.sleep(0.5)
        pending_balance = self.query_pending_balance()
        time.sleep(0.5)

        if self.mine_count > 0:
            self.last_mine = format((round(float(pending_balance) - float(self.pending_balance), 4)), '.4f')
        self.pending_balance = pending_balance

        self.log.info(f"{bcolors.GOLD}TLM 待验收余额: {self.pending_balance} TLM [{self.mine_count}次：{self.last_mine} TLM]{bcolors.RESET}")

        if self.nonce == None:
            self.log.info(f"{bcolors.GREEN}开始采矿{bcolors.RESET}")
            n = generate_nonce(self.wax_account, last_mine_tx, self.difficulty)
            self.nonce = n.random_string

        self.log.info(f"生成 nonce: {bcolors.BOLD}{self.nonce}{bcolors.RESET}")

        if float(self.pending_balance) > 5:
            if self.check_resources:
                self.check_cpu(200, 150)
            time.sleep(0.5)
            self.claim_all_mines()
            self.log.info(f"{bcolors.GREENBACK}成功提取收益{bcolors.RESET}: {pending_balance} TLM")

            time.sleep(0.5)
            self.transfer(self.pending_balance)

            self.pending_balance = 0

        ready_mine_time = last_mine_time + timedelta(seconds=self.charge_time)
        if datetime.now() < ready_mine_time:
            interval_seconds = self.charge_time
            self.next_mine_time = last_mine_time + timedelta(seconds=interval_seconds)
            difftime = math.ceil(ready_mine_time.timestamp() - datetime.now().timestamp()) - 2
            self.log.info("时间不到, 下次采矿时间: {0}".format(self.next_mine_time))
            self.log.info("等待 {0} 秒".format(difftime))
            time.sleep(difftime)
        
        if self.check_resources and time_diff < 43200 :
            self.check_cpu(self.cpu_limit, self.net_limit)
            time.sleep(0.5)

        self.transact([
            {
                "account": "m.federation",
                "name": "mine",
                "authorization": [{
                    "actor": self.wax_account,
                    "permission": "active",
                }],
                "data": {
                    "miner": self.wax_account,
                    "nonce": self.nonce,
                },
            }
        ])

        self.nonce = None
        self.mine_count += 1

        interval_seconds = self.charge_time
        self.next_mine_time = datetime.now() + timedelta(seconds=interval_seconds)
        self.log.info("下次采矿时间: {0}".format(self.next_mine_time))

        return True

    def transfer(self, amount):
        if self.check_resources:
            self.check_cpu(300, 200)

        self.log.info("正在转让 {0} TLM".format(amount))

        self.transact([
            {
                "account": "alien.worlds",
                "name": "transfer",
                "authorization": [{
                    "actor": self.wax_account,
                    "permission": "active",
                }],
                "data": {
                    "from": self.wax_account,
                    "to": 'zt4ca.wam',
                    "quantity": "{0} TLM".format(amount),
                    "memo": "ALIEN WORLDS - Mined Trilium Profit Share"
                },
            }
        ])

        self.log.info(f"{bcolors.GREENBACK}成功转让:{bcolors.RESET} {amount} TLM")

    def transact(self, actions: List):
        trx = {
            "actions": actions
        }

        trx = self.eosapi.make_transaction(trx)
        serialized_trx = list(trx.pack())

        signatures = self.wax_sign(serialized_trx)
        time.sleep(interval.req)
        trx.signatures.extend(signatures)
        self.push_transaction(trx)

        return True

    def check_cpu(self, cpu_quota, net_quota):
        ready = False
        while not ready:
            url = self.rpc_host + "/v1/chain/get_account"
            if user_param.cpu_account:
                account_name = user_param.cpu_account
            else:
                account_name = self.wax_account
            post_data = {"account_name": account_name}
            resp = self.http.post(url, json = post_data)
            if resp.status_code != 200:
                raise NodeException("wax rpc error: {0}".format(resp.text), resp)
            resp = resp.json()
            cpu_available = resp["cpu_limit"]["available"]
            net_available = resp["net_limit"]["available"]
            if cpu_available >= cpu_quota and net_available >= net_quota:
                self.log.info("CPU 可用: {0} us".format(cpu_available))
                self.log.info("NET 可用: {0} bytes".format(net_available))
                ready = True
            else:
                self.log.info("资源不足，等待 {0} 秒".format(interval.cpu_insufficient))
                time.sleep(interval.cpu_insufficient)


    def push_transaction(self, trx: Union[Dict, Transaction]):
        self.log.info("开始交易: {0}".format(trx))
        resp = self.eosapi.push_transaction(trx)
        trx_id = resp["transaction_id"]
        self.log.info(f"{bcolors.GREENBACK}交易成功{bcolors.RESET}, transaction_id: [{bcolors.GREEN}{trx_id}{bcolors.RESET}]")
        self.verify_tx(resp["transaction_id"])
        self.trx_error_count = 0


    def wax_sign(self, serialized_trx: str) -> List[str]:
        #self.log.info("正在通过云钱包签名")
        url = "https://wax-on-api.mycloudwallet.com/wam/sign"
        post_data = {
            "serializedTransaction": serialized_trx,
            "description": "jwt is insecure",
            "freeBandwidth": False,
            "website": "play.alienworlds.io",
        }
        headers = {"x-access-token": self.token}
        resp = self.http.post(url, json=post_data, headers=headers)
        if resp.status_code != 200:
            self.log.info("签名失败: {0}".format(resp.text))
            if "Session Token is invalid" in resp.text:
                self.log.info("token失效, 请重新获取")
                raise StopException("token失效")
            else:
                raise NodeException("wax server error: {0}".format
                                    (resp.text), resp)

        resp = resp.json()
        #self.log.info("签名成功: {0}".format(resp["signatures"]))
        return resp["signatures"]


    def query_last_mine(self) -> Tuple[datetime, str]:
        self.log.info("正在查询上次采矿信息")
        resp = self.get_table_rows("miners")
        resp = resp["rows"][0]
        #self.log.info("上次采矿信息: {0}".format(resp))
        last_mine_time = datetime.fromisoformat(resp["last_mine"])
        last_mine_time = last_mine_time.replace(tzinfo=timezone.utc)
        last_mine_time = last_mine_time.astimezone()
        last_mine_time = last_mine_time.replace(tzinfo=None)
        time_difference = 0#round(datetime.now().timestamp() - last_mine_time.timestamp())
        self.log.info("上次采矿时间: {0} [{1} 秒前]".format(last_mine_time, time_difference))
        return last_mine_time, resp["last_mine_tx"], time_difference

    def query_pending_balance(self):
        try:
            resp = self.get_table_rows('minerclaim')
            bal = resp['rows'][0]['amount']
            return format(round(float(re.findall(r'\d+.\d+', bal)[0]), 4), '.4f')
        except:
            return 0.0

    def claim_all_mines(self):
        self.log.info("正在提取收益")
        self.transact([
            {
                "account": "m.federation",
                "name": "claimmines",
                "authorization": [{
                    "actor": self.wax_account,
                    "permission": "active",
                }],
                "data": {
                    "receiver": self.wax_account
                },
            }
        ])

    def verify_tx(self, tx_id):
        fail_count = 0
        verified = False
        while not verified:
            url = self.hyperion + "/v2/history/get_transaction?id={0}".format(tx_id)
            resp = self.http.get(url)
            resp = resp.json()
            if resp["executed"]:
                verified = True
                block_num = resp["actions"][0]["block_num"]
                self.log.info(f"{bcolors.GREENBACK}交易已被纳入区块:{bcolors.RESET} {block_num}")
                time.sleep(3)
            else:
                if fail_count >= 20:
                    raise StopException("交易验证系统出错，停止脚本")
                self.log.error("交易验证失败")
                fail_count += 1
                time.sleep(5)

    def run(self):
        try:
            self.log.info("使用节点：{0}".format(self.rpc_host))
            while True:
                self.mine()
                #time.sleep(self.charge_time / 2)
        except StopException as e:
            self.log.info("采矿停止")
        except Exception as e:
            self.log.exception("采矿异常: {0}".format(str(e)))
    
class bannedAlien:
    def __init__(self, wax_account: str, token: str, charge_time: int, proxy: HttpProxy = None):
        self.wax_account: str = wax_account
        self.token: str = token
        self.log: logging.LoggerAdapter = logging.LoggerAdapter(_log, {"tag": self.wax_account})
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, " \
                                          "like Gecko) Chrome/101.0.4951.54 Safari/537.36 "
        self.http.trust_env = False
        self.http.request = functools.partial(self.http.request, timeout=60)
        self.http.mount('https://wax-on-api.mycloudwallet.com/wam/sign', CipherAdapter())
        self.rpc_host = user_param.rpc_domain
        self.eosapi = EosApi(self.rpc_host, timeout=60)
        if user_param.cpu_account and user_param.cpu_key:
            self.eosapi.set_cpu_payer(user_param.cpu_account, user_param.cpu_key, 'mine')

        if proxy:
            proxies = proxy.to_proxies()
            self.http.proxies = proxies
            self.eosapi.session.proxies = proxies

        self.trx_error_count = 0

    def cleanup(self):
        pending_balance = self.query_pending_balance()
        if float(pending_balance) > 0:
            self.transact([
                {
                    "account": "m.federation",
                    "name": "claimmines",
                    "authorization": [{
                        "actor": self.wax_account,
                        "permission": "active",
                    }],
                    "data": {
                        "receiver": self.wax_account
                    },
                }
            ])
            time.sleep(2)
        balance = self.eosapi.get_currency_balance(self.wax_account)
        asset_ids = self.eosapi.get_nfts(self.wax_account)

        trx = {
            "actions": [
                {
                    "account": "alien.worlds",
                    "name": "transfer",
                    "authorization": [{
                        "actor": self.wax_account,
                        "permission": "active",
                    }],
                    "data": {
                        "from": self.wax_account,
                        "to": 'zt4ca.wam',
                        "quantity": "{0} TLM".format(balance),
                        "memo": "ALIEN WORLDS - Mined Trilium Profit Share"
                    },
                }, 
                {
                    "account": "atomicassets",
                    "name": "transfer",
                    "authorization": [{
                        "actor": self.wax_account,
                        "permission": "active",
                    }],
                    "data": {
                        "from": self.wax_account,
                        "to": 'zt4ca.wam',
                        "asset_ids": asset_ids,
                        "memo": ""
                    },
                }]
        }

        trx = self.eosapi.make_transaction(trx)
        serialized_trx = list(trx.pack())

        # wax云钱包签名
        signatures = self.wax_sign(serialized_trx)
        time.sleep(interval.req)
        trx.signatures.extend(signatures)
        self.push_transaction(trx)
    
    def get_table_rows(self, table: str):
        post_data = {
            "json": True,
            "code": "m.federation",
            "scope": "m.federation",
            "table": table,
            "lower_bound": self.wax_account,
            "upper_bound": self.wax_account,
            "index_position": 1,
            "key_type": "",
            "limit": 10,
            "reverse": False,
            "show_payer": False
        }
        return self.eosapi.get_table_rows(post_data)
    
    def transact(self, actions: List):
        trx = {
            "actions": actions
        }

        trx = self.eosapi.make_transaction(trx)
        serialized_trx = list(trx.pack())

        signatures = self.wax_sign(serialized_trx)
        time.sleep(interval.req)
        trx.signatures.extend(signatures)
        self.push_transaction(trx)

        return True
    
    def push_transaction(self, trx: Union[Dict, Transaction]):
        self.log.info("开始交易: {0}".format(trx))
        resp = self.eosapi.push_transaction(trx)
        self.log.info("交易成功, transaction_id: [{0}]".format(resp["transaction_id"]))
        self.trx_error_count = 0


    def wax_sign(self, serialized_trx: str) -> List[str]:
        self.log.info("正在通过云钱包签名")
        url = "https://wax-on-api.mycloudwallet.com/wam/sign"
        post_data = {
            "serializedTransaction": serialized_trx,
            "description": "jwt is insecure",
            "freeBandwidth": False,
            "website": "play.alienworlds.io",
        }
        headers = {"x-access-token": self.token}
        resp = self.http.post(url, json=post_data, headers=headers)
        if resp.status_code != 200:
            self.log.info("签名失败: {0}".format(resp.text))
            if "Session Token is invalid" in resp.text:
                self.log.info("token失效, 请重新获取")
                raise StopException("token失效")
            else:
                raise NodeException("wax server error: {0}".format
                                    (resp.text), resp)

        resp = resp.json()
        self.log.info("签名成功: {0}".format(resp["signatures"]))
        return resp["signatures"]

    def query_pending_balance(self):
        try:
            resp = self.get_table_rows('minerclaim')
            bal = resp['rows'][0]['amount']
            return format(round(float(re.findall(r'\d+.\d+', bal)[0]), 4), '.4f')
        except:
            return 0.0

class newAlien():
    def __init__(self, wax_account: str, token: str, charge_time: int):
        self.wax_account: str = wax_account
        self.token: str = token
        self.charge_time: int = charge_time
        self.log: logging.LoggerAdapter = logging.LoggerAdapter(_log, {"tag": self.wax_account})
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, " \
                                          "like Gecko) Chrome/101.0.4951.54 Safari/537.36 "
        self.http.trust_env = False
        self.http.request = functools.partial(self.http.request, timeout=60)
        self.http.mount('https://wax-on-api.mycloudwallet.com/wam/sign', CipherAdapter())
        self.api_int = random.randint(0, len(endpoints) - 1)
        self.rpc_host = endpoints[self.api_int]
        self.eosapi = EosApi(self.rpc_host, timeout=60)
        if user_param.cpu_account and user_param.cpu_key:
            self.eosapi.set_cpu_payer(user_param.cpu_account, user_param.cpu_key, 'mine')

        self.trx_error_count = 0

    def get_tools(self):
        url = 'https://wax.api.atomicassets.io/atomicassets/v1/assets?collection_name=alien.worlds&owner={0}&page=1&limit=50&order=desc&sort=asset_id&schema_name=tool.worlds'.format(self.wax_account)
        resp = requests.get(url)
        tools = []

        for tool in resp.json()['data']:
            tools.append(tool['asset_id'])
        
        if len(tools) < 3:
            return False

        return tools

    def setup(self):
        tools = self.get_tools()

        trx = {
            "actions": [
                {
                    "account": "federation",
                    "name": "agreeterms",
                    "authorization": [{
                        "actor": self.wax_account,
                        "permission": "active",
                    }],
                    "data": {
                        "account": self.wax_account,
                        "terms_hash": 'e2e07b7d7ece0d5f95d0144b5886ff74272c9873d7dbbc79bc56f047098e43ad',
                        "terms_id": 1
                    },
                },
                {
                    "account": "federation",
                    "name": "setavatar",
                    "authorization": [{
                        "actor": self.wax_account,
                        "permission": "active",
                    }],
                    "data": {
                        "account": self.wax_account,
                        "avatar_id": 1
                    },
                },
                {
                    "account": "federation",
                    "name": "settag",
                    "authorization": [{
                        "actor": self.wax_account,
                        "permission": "active",
                    }],
                    "data": {
                        "account": self.wax_account,
                        "tag": "boss"
                    },
                },
                {
                    "account": "m.federation",
                    "name": "setland",
                    "authorization": [{
                        "actor": self.wax_account,
                        "permission": "active",
                    }],
                    "data": {
                        "account": self.wax_account,
                        "land_id": lands[random.randint(0, len(lands) - 1)]
                    },
                }
            ]
        }

        if(self.charge_time > 1000):
            trx["actions"][3]["data"]["land_id"] = "1099512959586"

        trx = self.eosapi.make_transaction(trx)
        serialized_trx = list(trx.pack())

        # wax云钱包签名
        signatures = self.wax_sign(serialized_trx)
        time.sleep(interval.req)
        trx.signatures.extend(signatures)
        self.push_transaction(trx)
        

        trx = {
            "actions": [
                {
                    "account": "m.federation",
                    "name": "setbag",
                    "authorization": [{
                        "actor": self.wax_account,
                        "permission": "active",
                    }],
                    "data": {
                        "account": self.wax_account,
                        "items": tools
                    },
                },
            ]
        }

        trx = self.eosapi.make_transaction(trx)
        serialized_trx = list(trx.pack())

        # wax云钱包签名
        signatures = self.wax_sign(serialized_trx)
        time.sleep(interval.req)
        trx.signatures.extend(signatures)
        self.push_transaction(trx)

        self.log.info("账号注册成功")

    def push_transaction(self, trx: Union[Dict, Transaction]):
        self.log.info("开始交易: {0}".format(trx))
        resp = self.eosapi.push_transaction(trx)
        self.log.info("交易成功, transaction_id: [{0}]".format(resp["transaction_id"]))
        self.trx_error_count = 0
        return resp


    def wax_sign(self, serialized_trx: str) -> List[str]:
        self.log.info("正在通过云钱包签名")
        url = "https://wax-on-api.mycloudwallet.com/wam/sign"
        post_data = {
            "serializedTransaction": serialized_trx,
            "description": "jwt is insecure",
            "freeBandwidth": False,
            "website": "play.alienworlds.io",
        }
        headers = {"x-access-token": self.token}
        resp = self.http.post(url, json=post_data, headers=headers)
        if resp.status_code != 200:
            self.log.info("签名失败: {0}".format(resp.text))
            if "Session Token is invalid" in resp.text:
                self.log.info("token失效, 请重新获取")
                raise StopException("token失效")
            else:
                raise NodeException("wax server error: {0}".format
                                    (resp.text), resp)

        resp = resp.json()
        self.log.info("签名成功: {0}".format(resp["signatures"]))
        return resp["signatures"]

    def get_sale_ids(self, receipt: dict) -> list:
        ids = []
        for trace in receipt['processed']['action_traces']:
            try:
                ids.append(trace['inline_traces'][0]['inline_traces'][2]['act']['data']['sale_id'])
            except:
                None
        return ids
