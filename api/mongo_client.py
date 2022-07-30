import sys
import urllib.parse

from loguru import logger
from pymongo import MongoClient

logger.add(sys.stderr, format="<lvl> {level} - {message}</lvl>",
           filter=f"{__name__}",
           level="DEBUG",
           colorize=True,
           backtrace=True,
           diagnose=True,
           catch=True)


def login(username: str, password: str, hostname: str) -> MongoClient:
    connect_str = f"mongodb+srv://{urllib.parse.quote(username)}:{urllib.parse.quote(password)}@{hostname}".strip()
    return MongoClient(connect_str)