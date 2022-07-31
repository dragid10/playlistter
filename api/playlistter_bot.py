import sys
from typing import List

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
        self.last_tweet = self.get_last_tweet()
        # self.streaming_client = self.TwitterReplyWatcher(self, last_tweet=self.last_tweet[0])
        logger.info("Twitter login successful")

        # Spotify
        self.spotify_client_id = spotify_client_id
        self.spotify_client_secret = spotify_client_secret
        self.spotify_playlist_id = spotify_playlist_id
        self.spotify_client = self.spotify_login()
        logger.info("Spotify login successful")

        self.streaming_client = self.TwitterReplyWatcher(self, last_tweet=self.last_tweet[0])

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

    def get_last_tweet(self) -> List[Status]:
        """Return last tweet from logged-in user"""
        return self.twitter_client.user_timeline(count=1, exclude_replies=True, include_rts=False) or None

    def get_previous_replies_to_tweet(self) -> List[Status]:
        replies = []
        # Since there is no way to directly grab the replies to a tweet, we need to use the search API
        bot_user = self.get_logged_in_twitter_user().screen_name
        for tweet in tweepy.Cursor(self.twitter_client.search_tweets, q=f"to:{bot_user}", result_type="recent").items(500):
            if hasattr(tweet, "in_reply_to_status_id_str") and tweet.in_reply_to_status_id_str == self.last_tweet[0].id_str:
                replies.append(tweet)
        return replies

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

    def start_new_stream(self, last_tweet: Status):
        # Need to subclass tweepy.StreamingClient to be able to customize stream functionalities
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
        song_queries = self.spotify_client.search(q=song_proposal, type="track", limit=30)
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

    class TwitterReplyWatcher(tweepy.StreamingClient):
        def __init__(self, playlistter_bot, last_tweet: Status):
            self.playlistter = playlistter_bot
            self.last_tweet: Status = last_tweet
            self.is_direct_reply = self.playlistter.is_direct_reply
            super().__init__(playlistter_bot.twitter_bearer_token, wait_on_rate_limit=True, max_retries=25)

        def on_connect(self):
            logger.debug("Successfully connected to Twitter Stream")
            return super().on_connect()

        def on_errors(self, errors):
            logger.error(f"Error from Twitter Stream: {errors}")
            return super().on_errors(errors)

        def on_tweet(self, reply: Tweet):
            logger.debug(f"Received reply from Twitter: {reply}")
            # Only reply to direct replies (aka have a single `@` in the tweet)
            if self.is_direct_reply(reply):
                logger.debug(f"Direct reply detected")
                # Ensure this user hasn't already suggested a song for today
                if reply.author_id not in helpers.USER_REPLIES:
                    logger.debug(f"Found new reply to root tweet {self.last_tweet.id}: {reply.text}")
                    song_proposal = reply.text.replace(f"@{self.last_tweet.author.screen_name}", "").strip()

                    # lookup and add song to playlist
                    logger.debug(f"Looking up song: {song_proposal}")
                    song_uri = self.playlistter.lookup_songs(song_proposal)
                    added_to_playlist = self.playlistter.add_song_to_playlist(song_uri)

                    # Verify song was added to playlist and reply to user if it wasn't
                    if added_to_playlist:
                        logger.debug(f"Added song {song_uri} to playlist")
                        helpers.USER_REPLIES[reply.author_id] = song_proposal
                        self.playlistter.twitter_client.update_status(status="I've added your song to the playlist!",
                                                                      in_reply_to_status_id=reply.id,
                                                                      auto_populate_reply_metadata=True)
                    else:  # Tell user that the song is already in the playlist
                        self.playlistter.twitter_client.update_status(
                            status="This song is already in the playlist! Feel free to choose a different one 🙂",
                            in_reply_to_status_id=reply.id,
                            auto_populate_reply_metadata=True)
                        logger.debug(f"Song {song_proposal} is already in the playlist, informed requesting user")
                else:  # User has already suggested a song for today
                    logger.debug(f"Found duplicate reply to root tweet {self.last_tweet.id_str}: {reply.text}")
                    self.playlistter.twitter_client.update_status(
                        status="Sorry but you've already submitted a song for today! Try again tomorrow",
                        in_reply_to_status_id=reply.id,
                        auto_populate_reply_metadata=True)
            else:  # Not a direct reply
                logger.debug(f"Captured tweet was not a direct reply")

        def on_disconnect(self):
            logger.debug("Disconnected from Twitter Stream")
            return super().on_disconnect()

        def on_closed(self, response):
            logger.debug(f"Stream closed by Twitter with response {response}")
            self.disconnect()

        def on_connection_error(self):
            logger.debug("Connection error from Twitter Stream")
            self.disconnect()

        def on_data(self, raw_data):
            logger.debug(f"Received raw data from Twitter: {raw_data}")
            return super().on_data(raw_data)

        def on_matching_rules(self, matching_rules):
            logger.debug(f"Matching rules from Twitter Stream: {matching_rules}")
            return super().on_matching_rules(matching_rules)

        def disconnect(self):
            logger.info("Manual disconnection invoked on stream")
            return super().disconnect()