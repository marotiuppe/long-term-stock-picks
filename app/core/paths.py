"""Where the app's folders are. Modules live in sub-folders, so file paths are built from the app folder, not from __file__."""
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# On a host with a persistent disk (Render), set STOCKPICKS_DATA_DIR to its mount path so accounts, keys and the price cache survive a deploy.
_ROOT = os.environ.get("STOCKPICKS_DATA_DIR")
DATA_DIR = os.path.join(_ROOT, "data") if _ROOT else os.path.join(APP_DIR, "data")
CACHE_DIR = os.path.join(_ROOT, "cache") if _ROOT else os.path.join(APP_DIR, "cache")
