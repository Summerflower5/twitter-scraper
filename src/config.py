# src/config.py
import os
from dotenv import load_dotenv
import random

load_dotenv()

def _int_env(name, default):
    try:
        return int(os.getenv(name, default))
    except:
        return default

CONFIG = {
    "PROXY": os.getenv("PROXY", ""),                 # 可选：http://user:pass@host:port
    "COOKIES_FILE": os.getenv("COOKIES_FILE", "twitter_cookies.json"),
    "MIN_SLEEP_MS": _int_env("MIN_SLEEP_MS", 800),
    "MAX_SLEEP_MS": _int_env("MAX_SLEEP_MS", 2200),
    "REQUEST_TIMEOUT": _int_env("REQUEST_TIMEOUT", 15),   # seconds
    "MAX_REQUEST_RETRIES": _int_env("MAX_REQUEST_RETRIES", 3),
    "MAX_PLAYWRIGHT_RETRIES": _int_env("MAX_PLAYWRIGHT_RETRIES", 2),
    # small random jitter helper
    "JITTER": float(os.getenv("JITTER", "0.25")),
}

def random_sleep_ms():
    """Return a random sleep time in seconds between min and max + small jitter."""
    import time, random
    ms = random.randint(CONFIG["MIN_SLEEP_MS"], CONFIG["MAX_SLEEP_MS"])
    jitter = (random.random() - 0.5) * CONFIG["JITTER"] * ms
    sec = max(0.1, (ms + jitter) / 1000.0)
    return sec
