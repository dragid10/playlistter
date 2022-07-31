import sys
from typing import List

import pytz
from loguru import logger
from tweepy.models import Status

# Temporary In-memory map to keep track of user replies
# Will get cleared each new day
USER_REPLIES = {}
EASTERN_TZ = pytz.timezone('US/Eastern')

logger.add(sys.stderr, format="<lvl> {level} - {message}</lvl>",
           filter=f"{__name__}",
           level="DEBUG",
           colorize=True,
           backtrace=True,
           diagnose=True,
           catch=True)


# noinspection PyBroadException
def clear_user_reply_map() -> bool:
    global USER_REPLIES
    try:
        USER_REPLIES.clear()
        return True
    except Exception:
        logger.exception(f"Failed to clear reply map")
        return False


def populate_user_replies_map(replies: List[Status]):
    global USER_REPLIES
    for reply in replies:
        if reply.author.id_str not in USER_REPLIES:
            song = reply.text.strip()
            logger.debug(
                f"Previous song suggestion by {reply.author.id_str}: {reply.text}")
            USER_REPLIES[reply.author.id_str] = song
