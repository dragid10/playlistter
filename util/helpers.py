import sys

import pytz
import tweepy
from loguru import logger
from tweepy import Tweet
from tweepy.models import Status

from api.playlistter_bot import PlaylistterBot

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


def is_direct_reply(client: tweepy.API, tweet: Tweet) -> bool:
    return tweet.author_id != client.verify_credentials().id and tweet.text.count("@") == 1


# noinspection PyBroadException
def clear_user_reply_map() -> bool:
    global USER_REPLIES
    try:
        USER_REPLIES.clear()
        return True
    except Exception:
        logger.exception(f"Failed to clear reply map")
        return False


def populate_user_replies_map(playlistter: PlaylistterBot, last_tweet: Status):
    global USER_REPLIES

    # Since there is no way to directly grab the replies to a tweet, we need to use the search API
    for tweet in tweepy.Cursor(playlistter.twitter_client.search_tweets, q=f"to:{last_tweet.author.screen_name}", result_type="recent") \
            .items(500):
        if hasattr(tweet, "in_reply_to_status_id_str") and tweet.in_reply_to_status_id_str == last_tweet.id_str:
            if tweet.author.id_str not in USER_REPLIES:
                song = tweet.text.strip()
                logger.debug(f"Previous song suggestion by {tweet.author.id_str}: {tweet.text}")
                USER_REPLIES[tweet.author.id_str] = song