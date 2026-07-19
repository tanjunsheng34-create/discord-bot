"""
GMPT Bot — 统一错误日志模块
用法: from utils.logger import log_error; log_error("economy", "buy_cmd", e)
日志写入 bot.log，格式：[时间] [模块] [函数] 错误信息
"""
import logging
import traceback
from datetime import datetime

LOG_FILE = "bot.log"

# 文件 handler（append 模式）
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setLevel(logging.WARNING)
_file_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] [%(module)s] [%(funcName)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

_root = logging.getLogger("gmpt")
_root.setLevel(logging.DEBUG)
_root.addHandler(_file_handler)

# 同时保留控制台输出
_console = logging.StreamHandler()
_console.setLevel(logging.WARNING)
_console.setFormatter(logging.Formatter(
    "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
_root.addHandler(_console)

# 便捷函数
def log_error(module: str, func: str, error):
    """统一错误日志记录"""
    tb = traceback.format_exc()
    if tb and tb != "NoneType: None\n":
        _root.error(f"[{module}] [{func}] {error}\n{tb}")
    else:
        _root.error(f"[{module}] [{func}] {error}")


def log_warn(module: str, func: str, msg: str):
    _root.warning(f"[{module}] [{func}] {msg}")


def log_info(module: str, func: str, msg: str):
    _root.info(f"[{module}] [{func}] {msg}")
