"""Small downloaded files (NSE share and ETF lists, bhavcopy, company facts): kept in a folder normally, or in the database when there is one.

A host with no persistent disk (Render's free plan) wipes the folder on every restart, so each start would download them all again. In the
database they survive. `backend` returns the store to use or None; server.py points it at the database when DATABASE_URL is set. A caller that
passes its own folder (the tests do) always gets plain files.
"""
import os
import time

backend = lambda: None


def read(name, directory=None, default_dir=None):
    """(bytes, saved-at epoch seconds) for the named file, or None when there is none."""
    store = backend() if directory is None else None
    if store:
        return store.raw_get(name)
    path = os.path.join(directory or default_dir, name)
    try:
        with open(path, "rb") as fh:
            return fh.read(), os.path.getmtime(path)
    except OSError:
        return None


def write(name, data, directory=None, default_dir=None):
    store = backend() if directory is None else None
    if store:
        store.raw_put(name, data)
        return
    folder = directory or default_dir
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path + ".tmp", "wb") as fh:
        fh.write(data)
    os.replace(path + ".tmp", path)
