"""Configuration: explicit CLI values > environment > TOML > defaults."""
from dataclasses import asdict, dataclass
import math
import os
from pathlib import Path
import tomllib

from platformdirs import user_config_path, user_data_path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    profile: Path
    browser: str | None = None
    port: int = 0
    rate: float = 1.5
    headed: bool = False
    retries: int = 2
    stale_seconds: float = 180
    confirmation_seconds: float = 180
    poll_seconds: float = 1

    def as_dict(self):
        return {k: str(v) if isinstance(v, Path) else v for k, v in asdict(self).items()}


def load_config(config_file=None, env=None, **overrides):
    env = os.environ if env is None else env
    path = Path(config_file or env.get('WANDA_CONFIG') or user_config_path('wangda-cli', appauthor=False) / 'config.toml')
    values = {}
    if path.exists():
        with path.open('rb') as handle:
            doc = tomllib.load(handle)
        if set(doc) - {'wangda'} or not isinstance(doc.get('wangda', {}), dict):
            raise ValueError('Configuration must contain only a [wangda] table')
        values = doc.get('wangda', {})
    elif config_file or env.get('WANDA_CONFIG'):
        raise ValueError('Configuration file does not exist')
    fields = set(Config.__dataclass_fields__)
    if unknown := set(values) - fields:
        raise ValueError(f'Unknown configuration keys: {sorted(unknown)}')
    values = dict(values)
    for key in fields:
        if (value := env.get('WANDA_' + key.upper())) is not None:
            values[key] = value
    values.update({k: v for k, v in overrides.items() if v is not None})
    if set(values) - fields:
        raise ValueError('Unknown configuration override')
    data_dir = Path(values.pop('data_dir', user_data_path('wangda-cli', appauthor=False))).expanduser().resolve()
    profile = Path(values.pop('profile', data_dir / 'profile')).expanduser().resolve()
    for key in ('port', 'retries'):
        if key in values:
            values[key] = int(values[key])
    for key in ('rate', 'stale_seconds', 'confirmation_seconds', 'poll_seconds'):
        if key in values:
            values[key] = float(values[key])
    if isinstance(values.get('headed'), str):
        if values['headed'].lower() not in ('true', 'false', '1', '0'):
            raise ValueError('headed must be true or false')
        values['headed'] = values['headed'].lower() in ('true', '1')
    config = Config(data_dir=data_dir, profile=profile, **values)
    if not math.isfinite(config.rate) or config.rate not in (1.0, 1.2, 1.5):
        raise ValueError('rate must be a platform-supported value: 1.0, 1.2 or 1.5')
    if not 0 <= config.port <= 65535 or not 0 <= config.retries <= 10:
        raise ValueError('port must be 0..65535 and retries must be 0..10')
    for key in ('stale_seconds', 'confirmation_seconds', 'poll_seconds'):
        if not math.isfinite(getattr(config, key)) or getattr(config, key) <= 0:
            raise ValueError(f'{key} must be finite and positive')
    return config
