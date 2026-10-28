"""Portable Wangda playback automation."""
from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth is pyproject.toml; never hardcode a second copy here.
    __version__ = version('wangda-cli')
except PackageNotFoundError:  # running straight from a source checkout
    __version__ = '0.0.0+source'
