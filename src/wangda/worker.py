"""One isolated platform task. Events only; authentication is never serialized."""
import json
from pathlib import Path
import sys

from . import engine
from .adapter import LoginRequired, Unconfirmed, UnsupportedItem, play
from .browser import Browser
from .config import load_config


def main(argv=None):
    config_path, url = (sys.argv[1:] if argv is None else argv)
    config = load_config(env={}, **json.loads(Path(config_path).read_text(encoding='utf-8')))
    try:
        result = play(Browser(config), config, url)
        engine.log(None, ev='result', status='completed', **result)
        return 0
    except LoginRequired:
        engine.log(None, ev='result', status='waiting_login', verified=False)
        return 3
    except UnsupportedItem:
        engine.log(None, ev='result', status='unconfirmed', reason='unsupported_item', verified=False)
        return 4
    except Unconfirmed:
        engine.log(None, ev='result', status='unconfirmed', verified=False)
        return 4
    except Exception as error:
        engine.log(None, ev='result', status='failed', reason=type(error).__name__, verified=False)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
