import sys

import tweepy
from loguru import logger
from tweepy import Tweet
from tweepy.models import Status

from api.playlistter_bot import PlaylistterBot
from util import helpers

logger.add(sys.stderr, format="<lvl> {level} - {message}</lvl>",
           filter=f"{__name__}",
           level="DEBUG",
           colorize=True,
           backtrace=True,
           diagnose=True,
           catch=True)


class TwitterReplyWatcher(tweepy.StreamingClient):
    def __init__(self, playlistter_bot: PlaylistterBot, last_tweet: Status):
        self.playlistter = playlistter_bot
        self.last_tweet: Status = last_tweet
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
        if self.playlistter.is_direct_reply(reply):
            # Ensure this user hasn't already suggested a song for today
            if reply.author_id not in helpers.USER_REPLIES:
                logger.debug(f"Found new reply to root tweet {self.last_tweet.id}: {reply.text}")
                song_proposal = reply.text.replace(f"@{self.last_tweet.author.screen_name}", "").strip()

                # lookup and add song to playlist
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