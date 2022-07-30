import datetime
import sys

from apscheduler.events import EVENT_JOB_SUBMITTED, JobSubmissionEvent
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from decouple import config
from loguru import logger
from tweepy.models import Status

from api import mongo_client
from api.playlistter_bot import PlaylistterBot
from models.twitter_reply_watcher import TwitterReplyWatcher
from util import helpers

logger.remove()  # Remove default logger to avoid dupe logs
logger.add(sys.stderr, format="<lvl> {level} - {message}</lvl>", level="DEBUG", colorize=True, backtrace=True, diagnose=True, catch=True)
logger.add(sys.stderr, format="<lvl> {level} - {message}</lvl>", filter="apscheduler", level="DEBUG", colorize=True, backtrace=True,
           diagnose=True, catch=True)


def new_day_tasks():
    logger.info("Starting new day tasks")

    # Check if I've tweeted today already
    last_tweet: Status = playlistter.get_last_tweet()

    # If I've not already tweeted today then clear reply map and prompt for songs
    if not last_tweet or (last_tweet[0].created_at.astimezone(helpers.EASTERN_TZ).date() != datetime.datetime.now().astimezone(
            helpers.EASTERN_TZ).date()):
        helpers.clear_user_reply_map()
        playlistter.daily_prompt_for_songs()

    # Get last tweet again in case we didn't have one before (kinda wasteful tbh)
    last_tweet = playlistter.get_last_tweet()[0]

    # Populate the reply map with all replies to the last tweet
    helpers.populate_user_replies_map(playlistter, last_tweet)

    # If this is started by a new day as opposed to the script dying, then kill the current stream before starting a new one
    logger.debug("Killing current stream")
    playlistter.kill_stream()

    # Watch for new replies by starting a new stream
    logger.debug("Starting new stream")

    streaming_client = TwitterReplyWatcher(playlistter, last_tweet)
    playlistter.start_new_stream(streaming_client, last_tweet)


def scheduler_callback(event: JobSubmissionEvent):
    logger.debug(f"""Scheduler callback triggered: {event}""")
    if event.job_id:
        pass
    pass


if __name__ == '__main__':
    # Log into Twitter
    playlistter = PlaylistterBot(twitter_api_key=config.TWITTER_CONSUMER_KEY,
                                 twitter_api_secret=config.TWITTER_CONSUMER_SECRET,
                                 twitter_token=config.TWITTER_ACCESS_TOKEN,
                                 twitter_token_secret=config.TWITTER_ACCESS_SECRET,
                                 twitter_bearer_token=config.TWITTER_BEARER_TOKEN,
                                 spotify_client_id=config.SPOTIFY_CLIENT_ID,
                                 spotify_client_secret=config.SPOTIFY_CLIENT_SECRET,
                                 spotify_playlist_id=config.SPOTIFY_PLAYLIST_ID)

    # Create mongo client
    mongo = mongo_client.login(username=config.MONGO_USER, password=config.MONGO_PASSWORD, hostname=config.MONGO_HOST)

    # Create Scheduler job
    scheduler = BlockingScheduler(timezone=helpers.EASTERN_TZ,
                                  jobstores={'mongo': MongoDBJobStore(client=mongo)},
                                  job_defaults={'misfire_grace_time': None, 'coalesce': True})

    # cron daily at 03:30am ET
    logger.info("Starting scheduler")
    scheduler.add_job(new_day_tasks,
                      id="playlistter",
                      name="playlistter",
                      replace_existing=True,
                      # max_instances=1,
                      # trigger=CronTrigger.from_crontab("30 3 * * *", timezone=helpers.EASTERN_TZ),
                      trigger=CronTrigger.from_crontab("*/1 * * * *", timezone=helpers.EASTERN_TZ),
                      next_run_time=datetime.datetime.now(tz=helpers.EASTERN_TZ) + datetime.timedelta(minutes=2)
                      )

    scheduler.add_listener(scheduler_callback, EVENT_JOB_SUBMITTED)

    scheduler.start()