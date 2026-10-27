"""Logging setup: console + rotating file in /config/logs, with secrets redacted."""
import io
import logging
import platform
import re
import sys
import zipfile
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from . import config

LOG_DIR = config.CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "curatarr.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 5
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Tokens and keys must never reach a log file someone may share.
_SECRET_PATTERNS = [
    re.compile(r"(?i)((?:x-plex-token|api_key|apikey|token|access_token|client_id)=)[^&\s\"']+"),
    re.compile(r"(?i)((?:x-plex-token|x-api-key|trakt-api-key|authorization)[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)[^\s\"',}]+"),
]
_LINE = re.compile(r"^(\S+ \S+) (\w+)\s+([\w.]+): (.*)$")


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = RedactingFormatter(FORMAT)
    root = logging.getLogger()
    root.setLevel(config.LOG_LEVEL)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                       encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(console)
    root.addHandler(file_handler)
    # Request logs from the HTTP client include full URLs with API keys; keep them quiet.
    # Per-request access lines from the web server would bury the useful entries.
    # The scheduler logs every job it (re)adds, which buries the sync messages.
    for noisy in ("httpx", "httpcore", "apscheduler", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True


def log_files() -> list:
    """Current log first, then rotated files newest to oldest."""
    files = [LOG_FILE] + [LOG_DIR / f"curatarr.log.{i}" for i in range(1, BACKUPS + 1)]
    return [f for f in files if f.is_file()]


def tail(lines: int = 500, level: str = "", search: str = "") -> list[dict]:
    """Most recent entries (oldest first), filtered by minimum level and text."""
    min_level = LEVELS.index(level.upper()) if level.upper() in LEVELS else 0
    needle = search.lower()
    entries: deque = deque(maxlen=lines)
    current = None
    for path in reversed(log_files()):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.rstrip("\n")
                match = _LINE.match(raw)
                if match:
                    if current:
                        _keep(entries, current, min_level, needle)
                    time, lvl, logger, message = match.groups()
                    current = {"time": time, "level": lvl, "logger": logger, "message": message}
                elif current:   # continuation line, e.g. a traceback
                    current["message"] += "\n" + raw
    if current:
        _keep(entries, current, min_level, needle)
    return list(entries)


def _keep(entries: deque, entry: dict, min_level: int, needle: str) -> None:
    lvl = LEVELS.index(entry["level"]) if entry["level"] in LEVELS else 0
    if lvl < min_level:
        return
    if needle and needle not in f"{entry['logger']} {entry['message']}".lower():
        return
    entries.append(entry)


def diagnostics(settings: dict, collections: list[dict]) -> str:
    """Plain-text summary for bug reports. Secret values are never included."""
    configured = {k: ("set" if v else "not set") for k, v in settings.items()
                  if k in config.SECRET_SETTINGS}
    lines = [
        f"Curatarr {config.VERSION}",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Python {platform.python_version()} on {platform.platform()}",
        f"Config dir: {config.CONFIG_DIR}",
        f"Plex URL: {settings.get('plex_url') or 'not set'}",
        f"Default schedule: {settings.get('default_schedule')}",
        "Credentials: " + ", ".join(f"{k}={v}" for k, v in sorted(configured.items())),
        "",
        f"Collections ({len(collections)}):",
    ]
    for row in collections:
        cfg = row["config"]
        sources = ", ".join(f"{s['type']}" for s in cfg.get("sources", []))
        lines.append(f"  #{row['id']} {cfg.get('name')} [{cfg.get('library')}] "
                     f"sources={sources} enabled={cfg.get('enabled')} "
                     f"last={row.get('last_status')} {row.get('last_run') or ''}")
        if row.get("last_message"):
            lines.append(f"      {redact(row['last_message'])}")
    return "\n".join(lines) + "\n"


def bundle(settings: dict, collections: list[dict]) -> bytes:
    """Zip of all log files plus diagnostics.txt."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diagnostics.txt", diagnostics(settings, collections))
        for path in log_files():
            zf.writestr(path.name, redact(path.read_text(encoding="utf-8", errors="replace")))
    return buf.getvalue()
