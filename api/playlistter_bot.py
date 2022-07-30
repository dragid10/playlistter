import sys

import tweepy
from loguru import logger
from spotipy import SpotifyOAuth, Spotify
from tweepy import Tweet
from tweepy.models import Status

from util import helpers

logger.add(sys.stderr, format="<lvl> {level} - {message}</lvl>",
           filter=f"{__name__}",
           level="DEBUG",
           colorize=True,
           backtrace=True,
           diagnose=True,
           catch=True)


class PlaylistterBot:
    def __init__(self,
                 twitter_api_key: str,
                 twitter_api_secret: str,
                 twitter_token: str,
                 twitter_token_secret: str,
                 twitter_bearer_token: str,
                 spotify_client_id: str,
                 spotify_client_secret: str,
                 spotify_playlist_id: str):
        # Twitter
        self.twitter_api_key = twitter_api_key
        self.twitter_api_secret = twitter_api_secret
        self.twitter_token = twitter_token
        self.twitter_token_secret = twitter_token_secret
        self.twitter_bearer_token = twitter_bearer_token
        self.twitter_client = self.twitter_login()
        self.streaming_client = None
        logger.info("Twitter login successful")

        # Spotify
        self.spotify_client_id = spotify_client_id
        self.spotify_client_secret = spotify_client_secret
        self.spotify_playlist_id = spotify_playlist_id
        self.spotify_client = self.spotify_login()
        logger.info("Spotify login successful")

    def twitter_login(self) -> tweepy.API:
        auth: tweepy.OAuth1UserHandler = tweepy.OAuthHandler(consumer_key=self.twitter_api_key, consumer_secret=self.twitter_api_secret)
        auth.set_access_token(key=self.twitter_token, secret=self.twitter_token_secret)
        return tweepy.API(auth)

    def spotify_login(self) -> Spotify:
        scope = "playlist-modify-public"
        auth_manager = SpotifyOAuth(client_id=self.spotify_client_id,
                                    client_secret=self.spotify_client_secret,
                                    scope=scope,
                                    redirect_uri="http://localhost:8888/callback")
        return Spotify(auth_manager=auth_manager)

    # TWITTER METHODS
    def get_logged_in_twitter_user(self) -> tweepy.models.User:
        """Used to both get the logged-in user object and validate the credentials"""
        return self.twitter_client.verify_credentials()

    def get_last_tweet(self) -> Status:
        """Return last tweet from logged-in user"""
        return self.twitter_client.user_timeline(count=1, exclude_replies=True, include_rts=False) or None

    @staticmethod
    def register_tweet_reply(tweet: Status):
        logger.debug(f"Registering reply {tweet.id_str}")
        helpers.USER_REPLIES[tweet.au] = tweet.id_str

    def daily_prompt_for_songs(self):
        """Invites everyone to submit a song for the day"""
        logger.info("Prompting for songs")
        song_prompt = f"""~~ Good Day! ~~

    Help build out the crowd-sourced playlist by directly replying to this tweet in the following format: song - artist

    *The only catch is that you can only suggest one song per day!*

    Playlist Link: https://open.spotify.com/playlist/7sMcyP8zJ8Fr1WkZ27XL7Y?si=6213fe219e644fa5"""
        self.twitter_client.update_status(song_prompt)

    def is_direct_reply(self, tweet: Tweet) -> bool:
        return tweet.author_id != self.get_logged_in_twitter_user().id and tweet.text.count("@") == 1

    def start_new_stream(self, streaming_client, last_tweet: Status):
        # Need to subclass tweepy.StreamingClient to be able to customize stream functionalities
        self.streaming_client = streaming_client

        # technically `in_reply_to_status_id` is not listed in the documentation officially, but it exists
        # https://developer.twitter.com/en/blog/product-news/2022/twitter-api-v2-filtered-stream
        # https://docs.tweepy.org/en/stable/streamingclient.html#streamingclient
        logger.debug(f"Watching last tweet {last_tweet.id_str}")
        self.streaming_client.add_rules(tweepy.StreamRule(f"in_reply_to_status_id:{last_tweet.id_str}"))

        # Ensure we get these fields in the response
        logger.debug("Calling Stream `filter` function now")
        self.streaming_client.filter(tweet_fields="id,author_id,conversation_id,created_at,in_reply_to_user_id")

    def kill_stream(self):
        logger.debug("Killing stream")
        self.streaming_client.disconnect()

    # SPOTIFY METHODS
    def add_song_to_playlist(self, song: str) -> bool:
        playlist = self.spotify_client.playlist(self.spotify_playlist_id)
        playlist_songs = [uri["track"]["uri"] for uri in playlist["tracks"]["items"]]
        if song not in playlist_songs:
            ret = self.spotify_client.playlist_add_items(playlist_id=self.spotify_playlist_id, items=[song])
            logger.debug(f"Added new song to playlist")
        else:
            logger.debug(f"Song already in playlist")
            ret = False
        return ret

    def lookup_songs(self, comment: str) -> str:
        # Split song proposal into song and artist
        song_proposal = comment.split("-")
        # TODO (7/30/22) [dragid10]: CCleanup
        # song = song_proposal[0].strip()
        # artist = song_proposal[1].strip()

        # Lookup song with Spotify API and get the Spotify ID
        song_queries = self.spotify_client.search(q=song_proposal, limit=50)
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
        for track in song_queries:
            for artist in track["artists"]:
                if artist["name"].casefold() == song_details["artists"][0]["name"].casefold():
                    song_details = track
                    break

        logger.debug(f"Found song: {song_details['name']} - {song_details['artists'][0]['name']}")
        return song_details["uri"]