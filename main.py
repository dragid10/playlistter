import sys
from datetime import datetime

import tweepy
from apscheduler.schedulers.blocking import BlockingScheduler
from decouple import config
from loguru import logger
from pytz import timezone
from spotipy import Spotify, SpotifyOAuth
from tweepy import Tweet
from tweepy.models import Status

eastern = timezone('US/Eastern')

# Twitter configs
TWITTER_API_KEY = config("twitter_api_key")
TWITTER_API_SECRET = config("twitter_api_secret")
TWITTER_TOKEN = config("twitter_token")
TWITTER_TOKEN_SECRET = config("twitter_token_secret")
TWITTER_BEARER_TOKEN = config("twitter_bearer_token")

# Spotify configs
SPOTIFY_CLIENT_ID = config("spotify_client_id")
SPOTIFY_CLIENT_SECRET = config("spotify_client_secret")
SPOTIFY_PLAYLIST_ID = config("spotify_playlist_id")

# Tweet object return fields
TWEET_FIELDS = ["id", "author_id", "conversation_id", "created_at", "in_reply_to_user_id", ]
# TWEET_FIELDS = ["id,author_id,conversation_id,created_at,in_reply_to_user_id"]

log_format = "<lvl> {level} - {message}</lvl>"
logger.remove()  # Remove default logger to avoid dupe logs
logger.add(sys.stderr, format=log_format, level="DEBUG", colorize=True, backtrace=True, diagnose=True)


class TwitterReplyWatcher(tweepy.StreamingClient):
    def __init__(self, bearer_token: str, last_tweet: Status):
        super().__init__(bearer_token)
        self.last_tweet: Status = last_tweet

    def on_tweet(self, reply: Tweet):
        # Only reply to direct replies (aka have a single `@` in the tweet)
        if is_direct_reply(reply):
            # Ensure this user hasn't already suggested a song for today
            if reply.author_id not in USER_REPLIES:
                logger.debug(f"Found new reply to root tweet {self.last_tweet.id}: {reply.text}")
                song_proposal = reply.text.replace(f"@{self.last_tweet.author.screen_name}", "").strip()

                # lookup and add song to playlist
                song_uri = lookup_songs(song_proposal)
                added_to_playlist = add_song_to_playlist(song_uri)

                # Verify song was added to playlist and reply to user if it wasn't
                if added_to_playlist:
                    USER_REPLIES[reply.author_id] = song_proposal
                else:  # Tell user that the song is already in the playlist
                    twitter.update_status(status="This song is already in the playlist! Feel free to choose a different one 🙂",
                                          in_reply_to_status_id=reply.id,
                                          auto_populate_reply_metadata=True)
                    logger.debug(f"Song {song_proposal} is already in the playlist, informed requesting user")
            else:  # User has already suggested a song for today
                logger.debug(f"Found duplicate reply to root tweet {self.last_tweet.id_str}: {reply.text}")
                twitter.update_status(status="Sorry but you've already submitted a song for today! Try again tomorrow",
                                      in_reply_to_status_id=reply.id,
                                      auto_populate_reply_metadata=True)
        else:  # Not a direct reply
            logger.debug(f"Captured tweet was not a direct reply")


# Temporary In-memory map to keep track of user replies
# Will get cleared each new day
USER_REPLIES = {}


def twitter_login() -> tweepy.API:
    auth: tweepy.OAuth1UserHandler = tweepy.OAuthHandler(consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET)
    auth.set_access_token(key=TWITTER_TOKEN, secret=TWITTER_TOKEN_SECRET)
    return tweepy.API(auth)


def spotify_login():
    # The only scope we need to add songs to a playlist
    scope = "playlist-modify-public"
    auth_manager = SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID,
                                client_secret=SPOTIFY_CLIENT_SECRET,
                                scope=scope,
                                redirect_uri="http://localhost:8888/callback")
    return Spotify(auth_manager=auth_manager)


def kill_current_stream():
    # TODO
    pass


def new_day_tasks():
    logger.info("Starting new day tasks")

    # Check if I've tweeted today already
    last_tweet: Status = get_my_last_tweet()

    # If I've not already tweeted today then clear reply map and prompt for songs
    if not last_tweet or (last_tweet[0].created_at.astimezone(eastern).date() != datetime.now().astimezone(eastern).date()):
        clear_user_reply_map()
        daily_prompt_for_songs()

    # Get last tweet again in case we didn't have one before (kinda wasteful tbh)
    last_tweet = get_my_last_tweet()[0]

    # Populate the reply map with all replies to the last tweet
    populate_user_replies_map(last_tweet)

    # If this is started by a new day as opposed to the script dying, then kill the current stream before starting a new one
    logger.debug("Killing current stream")
    kill_current_stream()

    # Watch for new replies by starting a new stream
    logger.debug("Starting new stream")
    start_new_stream(last_tweet)


def get_my_last_tweet() -> Status:
    """Return last tweet from logged in user"""
    return twitter.user_timeline(count=1, exclude_replies=True, include_rts=False) or None


def clear_user_reply_map() -> bool:
    global USER_REPLIES
    try:
        USER_REPLIES.clear()
        return True
    except Exception:
        logger.exception(f"Failed to clear reply map")
        return False


def start_new_stream(last_tweet: str):
    # Need to subclass tweepy.StreamingClient to be able to customize stream funtionalities
    streaming_client = TwitterReplyWatcher(TWITTER_BEARER_TOKEN, last_tweet)

    # technically `in_reply_to_status_id` is not listed in the documentation officially, but it exists
    # https://developer.twitter.com/en/blog/product-news/2022/twitter-api-v2-filtered-stream
    # https://docs.tweepy.org/en/stable/streamingclient.html#streamingclient
    streaming_client.add_rules(tweepy.StreamRule(f"in_reply_to_status_id:{last_tweet}"))

    # Ensure we get these fields in the response
    streaming_client.filter(tweet_fields="id,author_id,conversation_id,created_at,in_reply_to_user_id")


def daily_prompt_for_songs():
    """Invites everyone to submit a song for the day"""
    logger.info("Prompting for songs")
    song_prompt = f"""~~ Good Day! ~~
    
Help build out the crowd-sourced playlist by directly replying to this tweet in the following format: song - artist

*The only catch is that you can only suggest one song per day!*

Playlist Link: https://open.spotify.com/playlist/7sMcyP8zJ8Fr1WkZ27XL7Y?si=6213fe219e644fa5"""
    twitter.update_status(song_prompt)


def lookup_songs(comment: str) -> str:
    # Split song proposal into song and artist
    song_proposal = comment.split("-")
    song = song_proposal[0].strip()
    artist = song_proposal[1].strip()

    # Lookup song with Spotify API and get the Spotify ID
    song_queries = spotify.search(q=song_proposal, )
    song_queries = song_queries.get("tracks", {}).get("items", [])

    # Naively match the song and artist to the first result
    song_details = song_queries[0]

    """I disabled this block because the naive approach somehow yields better results. I think spotify already optimizes their search
    results so I don't need to do it myself"""
    # # Extract all artists from the search results
    # artist_list = []
    # for song in song_queries:
    #     for artist in song["artists"]:
    #         artist_list.append(artist["name"])
    #
    # # Do a fuzzy match to find the best match amongst results
    # best_match = process.extractOne(artist["name"], artist_list, scorer=fuzz.token_set_ratio)
    # for track in song_queries["tracks"]["items"]:
    #     for artist in track["artists"]:
    #         if artist["name"] == best_match[0]:
    #             song_details = track
    #             break

    logger.debug(f"Found song: {song_details['name']} - {song_details['artists'][0]['name']}")
    return song_details["uri"]


def add_song_to_playlist(song: str) -> bool:
    playlist = spotify.playlist(SPOTIFY_PLAYLIST_ID)
    playlist_songs = [uri["track"]["uri"] for uri in playlist["tracks"]["items"]]
    if song not in playlist_songs:
        ret = spotify.playlist_add_items(playlist_id=SPOTIFY_PLAYLIST_ID, items=[song])
        logger.debug(f"Added new song to playlist")
    else:
        logger.debug(f"Song already in playlist")
        ret = False
    return ret


def populate_user_replies_map(last_tweet):
    global USER_REPLIES

    # Since there is no way to directly grab the replies to a tweet, we need to use the search API
    for tweet in tweepy.Cursor(twitter.search_tweets, q=f"to:{last_tweet.author.screen_name}", result_type="recent").items(500):
        if hasattr(tweet, "in_reply_to_status_id_str") and tweet.in_reply_to_status_id_str == last_tweet.id_str:
            if tweet.author.id_str not in USER_REPLIES:
                song = tweet.text.strip()
                logger.debug(f"Previous song suggestion by {tweet.author.id_str}: {tweet.text}")
                USER_REPLIES[tweet.author.id_str] = song


def is_direct_reply(tweet: Tweet) -> bool:
    return tweet.author_id != twitter.verify_credentials().id and tweet.text.count("@") == 1


if __name__ == '__main__':
    # Log into Twitter
    twitter = twitter_login()
    twitter.verify_credentials()
    logger.debug(f"Logged into Twitter")

    # Log into Spotify
    spotify = spotify_login()
    logger.debug(f"Logged into Spotify")

    # Create Scheduler job
    scheduler = BlockingScheduler(timezone=eastern)

    # cron daily at 2am EST
    logger.info("Starting scheduler")
    # scheduler.add_job(new_day_tasks, trigger="cron", hour=3, minute=0, second=0, timezone=eastern)
    scheduler.add_job(new_day_tasks, timezone=eastern)
    scheduler.start()