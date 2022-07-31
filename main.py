import datetime
import sys
from typing import List

from apscheduler.events import EVENT_JOB_ADDED
from apscheduler.events import EVENT_JOB_SUBMITTED
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from tweepy.models import Status

from api import mongo_client
from api.playlistter_bot import PlaylistterBot
from util import config
from util import helpers

logger.remove()  # Remove default logger to avoid dupe logs
logger.add(
    sys.stderr,
    format="<lvl> {level} - {message}</lvl>",
    level="DEBUG",
    colorize=True,
    backtrace=True,
    diagnose=True,
    catch=True,
)
logger.add(
    sys.stderr,
    format="<lvl> {level} - {message}</lvl>",
    filter="apscheduler",
    level="DEBUG",
    colorize=True,
    backtrace=True,
    diagnose=True,
    catch=True,
)


def new_day_tasks():
    logger.info("Starting new day tasks")

    # Check if I've tweeted today already
    last_tweet: List[Status] = playlistter.get_last_tweet()

    # If I've not already tweeted today then clear reply map and prompt for songs
    if not last_tweet or (
        last_tweet[0].created_at.astimezone(helpers.EASTERN_TZ).date()
        != datetime.datetime.now().astimezone(helpers.EASTERN_TZ).date()
    ):
        helpers.clear_user_reply_map()
        playlistter.daily_prompt_for_songs()

    # Get last tweet again in case we didn't have one before (kinda wasteful tbh)
    last_tweet: Status = playlistter.get_last_tweet()[0]

    # If script is restarting, then grab previous replies to daily tweet to popular user map
    previous_replies: List[Status] = playlistter.get_previous_replies_to_tweet()

    # Populate the reply map with all replies to the last tweet
    helpers.populate_user_replies_map(previous_replies)

    # If this is started by a new day as opposed to the script dying, then kill the current stream before starting a new one
    logger.debug("Killing current stream")
    playlistter.kill_stream()

    # Watch for new replies by starting a new stream
    logger.debug("Starting new stream")

    playlistter.start_new_stream(last_tweet)


def scheduler_callback(event):
    logger.debug(f"""Scheduler callback triggered: {event}""")

    # Kill current twitter stream (if any) on new job event
    if event.job_id:
        playlistter.kill_stream()


if __name__ == "__main__":
    # Create PlaylistterBot instance to handle both the Twitter and Spotify APIs
    playlistter = PlaylistterBot(
        twitter_api_key=config.TWITTER_API_KEY,
        twitter_api_secret=config.TWITTER_API_SECRET,
        twitter_token=config.TWITTER_TOKEN,
        twitter_token_secret=config.TWITTER_TOKEN_SECRET,
        twitter_bearer_token=config.TWITTER_BEARER_TOKEN,
        spotify_client_id=config.SPOTIFY_CLIENT_ID,
        spotify_client_secret=config.SPOTIFY_CLIENT_SECRET,
        spotify_playlist_id=config.SPOTIFY_PLAYLIST_ID,
        spotify_perma_token=config.SPOTIFY_PERMA_TOKEN,
    )

    # Create mongo client
    mongo = mongo_client.login(
        username=config.MONGO_USER,
        password=config.MONGO_PASSWORD,
        hostname=config.MONGO_HOST,
    )

    # Create Scheduler job
    scheduler = BlockingScheduler(
        timezone=helpers.EASTERN_TZ,
        jobstores={"mongo": MongoDBJobStore(client=mongo)},
        job_defaults={"misfire_grace_time": None, "coalesce": True},
    )

    # cron daily at 03:30am ET
    logger.info("Starting scheduler")
    scheduler.add_job(
        new_day_tasks,
        id="playlistter",
        name="playlistter",
        replace_existing=True,
        trigger=CronTrigger.from_crontab("30 3 * * *", timezone=helpers.EASTERN_TZ),
        next_run_time=datetime.datetime.now(tz=helpers.EASTERN_TZ)
        + datetime.timedelta(minutes=1),
    )

    # Add callback to scheduler to kill twitter stream on new runs
    scheduler.add_listener(scheduler_callback, EVENT_JOB_SUBMITTED | EVENT_JOB_ADDED)

    scheduler.start()
