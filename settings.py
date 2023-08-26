from typing import List, Dict, Optional
from dataclasses import dataclass
from dacite import from_dict, Config
import os


class interval:
    req: int = 2
    net_error: int = 20
    transact: int = 5
    cpu_insufficient: int = 15
    max_trx_error: int = 5

@dataclass
class UserParam:
    rpc_domain: str = "https://wax.defibox.xyz"
    cpu_account: Optional[str] = None
    cpu_key: Optional[str] = None
    delay1: int = 0
    delay2: int = 0

    proxy: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None

    account: str = os.environ['wam']
    token: str = os.environ['token']
    charge_time: int = None
    difficulty: int = 1

    claim_delta: int = 50


user_param: UserParam = UserParam()


def load_param(data: Dict) -> UserParam:
    user = from_dict(UserParam, data, config = Config(type_hooks={str: str}))
    user_param.__dict__ = user.__dict__
