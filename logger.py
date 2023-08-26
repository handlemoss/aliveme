import logging
import sys
from logging import handlers
import os

_log = logging.getLogger(__name__)
_log.setLevel(logging.INFO)
log = logging.LoggerAdapter(_log, {"tag": "global"})
os.system('color')

path_logs = "./logs"

logging.addLevelName(6, "SUCCESS")
def success(self, message, *args, **kws):
    self._log(6, message, args, kws)
logging.Logger.success = success

class bcolors:
    BOLD = '\033[1m'
    GREEN = '\033[32m'
    RED = '\033[31m'
    GOLD = '\033[33m'
    YELLOW = '\033[93m'
    PURPLE = '\033[35m'
    BLUE = '\033[36m'
    GREENBACK = '\033[42m'
    REDBACK = '\033[41m'
    GREYBACK = '\033[47m'
    BLUEBACK = '\033[46m'
    PURPLEBACK = '\033[45m'
    RESET = '\033[0m'

class CustomFormatter(logging.Formatter):
    format = "[%(asctime)s][%(levelname)s][%(tag)s]: %(message)s"

    FORMATS = {
        logging.INFO: f"{bcolors.BLUE}[%(asctime)s][%(levelname)s][%(tag)s]: {bcolors.RESET}%(message)s{bcolors.RESET}",
        logging.WARNING: f"{bcolors.BLUE}[%(asctime)s][%(levelname)s][%(tag)s]: {bcolors.YELLOW}%(message)s{bcolors.RESET}",
        logging.ERROR: f"{bcolors.BLUE}[%(asctime)s][%(levelname)s][%(tag)s]: {bcolors.RED}%(message)s{bcolors.RESET}",
        logging.CRITICAL: f"{bcolors.BLUE}[%(asctime)s][%(levelname)s][%(tag)s]: {bcolors.REDBACK}%(message)s{bcolors.RESET}",
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

def init_loger(loger_name: str):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CustomFormatter())
    logging.getLogger().addHandler(handler)
