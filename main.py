import logger
from logger import log
import ruamel.yaml
yaml = ruamel.yaml.YAML()
from ruamel.yaml.comments import CommentedMap
from settings import user_param, load_param
from alien import Alien, HttpProxy
import traceback
import sys
import os

def start():
    user_yml = "user.yml"
    if len(sys.argv) == 2:
        user_yml = sys.argv[1]

    with open("{0}/users/{1}".format(os.path.abspath(os.getcwd()), user_yml), "r", encoding="utf8") as file:
        data: CommentedMap = yaml.load(file)
        file.close()
    load_param(data)

    logger.init_loger(user_param.account)

    proxy = None
    if user_param.proxy:
        proxy = HttpProxy(user_param.proxy, user_param.proxy_username, user_param.proxy_password)

    if user_param.claim_delta:
        claim_delta = user_param.claim_delta
    else:
        claim_delta = 50

    log.info("正在加载配置文件: {0}".format(user_yml))
    log.info("=============开始采矿=============")
    alien = Alien(os.environ['wam'], os.environ['token'], user_param.charge_time, claim_delta, proxy)
    alien.run()
    log.info("=============采矿停止=============")



def main():
    print(">>>>>>>>>>>>> OpenAlien 开源版:v1.0.2 <<<<<<<<<<<<")
    print(">>>>>>>>>>>>> 交流QQ群:568229631 <<<<<<<<<<<<")
    print(">>>>>>>>>>>>> 项目地址:https://github.com/encoderlee/OpenAlien <<<<<<<<<<<<\n")
    try:
        start()
    except Exception as e:
        traceback.print_exc()
    #input("按回车键退出")


if __name__ == '__main__':
    main()
