"""Runtime configuration read from environment variables."""
import os
from pathlib import Path

VERSION = "0.5.2"
APP_NAME = "Curatarr"


def _default_config_dir() -> str:
    return "/config" if Path("/config").is_dir() else "./config"


CONFIG_DIR = Path(os.environ.get("CURATARR_CONFIG_DIR", _default_config_dir())).resolve()
DB_PATH = CONFIG_DIR / "curatarr.db"
IMAGE_DIR = CONFIG_DIR / "images"
SEED_FILE = CONFIG_DIR / "collections.yml"

PORT = int(os.environ.get("CURATARR_PORT", "8585"))
LOG_LEVEL = os.environ.get("CURATARR_LOG_LEVEL", "INFO").upper()

# Optional protection for the web UI / API. Basic auth is used by browsers,
# the API key header (X-Api-Key) is handy for scripts.
AUTH_USERNAME = os.environ.get("CURATARR_USERNAME", "")
AUTH_PASSWORD = os.environ.get("CURATARR_PASSWORD", "")
API_KEY = os.environ.get("CURATARR_API_KEY", "")

# Settings that can be provided through the environment. A value saved in the
# web UI takes precedence; the environment fills in anything left blank.
ENV_SETTINGS = {
    "plex_url": "PLEX_URL",
    "plex_token": "PLEX_TOKEN",
    "tmdb_api_key": "TMDB_API_KEY",
    "trakt_client_id": "TRAKT_CLIENT_ID",
    "mdblist_api_key": "MDBLIST_API_KEY",
    "radarr_url": "RADARR_URL",
    "radarr_api_key": "RADARR_API_KEY",
    "sonarr_url": "SONARR_URL",
    "sonarr_api_key": "SONARR_API_KEY",
    "default_schedule": "CURATARR_SCHEDULE",
}

DEFAULT_SETTINGS = {
    "plex_url": "",
    "plex_token": "",
    "plex_verify_ssl": "true",
    "tmdb_api_key": "",
    "trakt_client_id": "",
    "mdblist_api_key": "",
    "radarr_url": "",
    "radarr_api_key": "",
    "radarr_root_folder": "",
    "radarr_quality_profile": "",
    "radarr_search": "true",
    "sonarr_url": "",
    "sonarr_api_key": "",
    "sonarr_root_folder": "",
    "sonarr_quality_profile": "",
    "sonarr_search": "true",
    "default_schedule": "0 */6 * * *",
    "managed_label": "Curatarr",
}

SECRET_SETTINGS = {
    "plex_token",
    "tmdb_api_key",
    "trakt_client_id",
    "mdblist_api_key",
    "radarr_api_key",
    "sonarr_api_key",
}

# Stable client identifier used for plex.tv sign-in. Persisted in settings.
PLEX_CLIENT_ID_KEY = "plex_client_identifier"
