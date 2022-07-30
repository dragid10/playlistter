# Twitter configs
from decouple import config

TWITTER_API_KEY = config("twitter_api_key")
TWITTER_API_SECRET = config("twitter_api_secret")
TWITTER_TOKEN = config("twitter_token")
TWITTER_TOKEN_SECRET = config("twitter_token_secret")
TWITTER_BEARER_TOKEN = config("twitter_bearer_token")

# Spotify configs
SPOTIFY_CLIENT_ID = config("spotify_client_id")
SPOTIFY_CLIENT_SECRET = config("spotify_client_secret")
SPOTIFY_PLAYLIST_ID = config("spotify_playlist_id")

# Mongo Configs
MONGO_HOST = config("mongo_host")
MONGO_PORT = config("mongo_port")
MONGO_USER = config("mongo_user")
MONGO_PASSWORD = config("mongo_password")