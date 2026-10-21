from pathlib import Path
import pytest
from wangda.config import load_config


def test_config_is_agent_neutral_and_cli_overrides_env_and_file(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text('[wangda]\nrate=1.0\nport=9339\n')
    config = load_config(config_file=path, data_dir=tmp_path / "data", rate=1.2,
                         env={"WANDA_RATE": "1.5", "WANDA_DATA_DIR": str(tmp_path / "ignored")})
    assert config.rate == 1.2
    assert config.port == 9339
    assert config.profile == config.data_dir / "profile"
    assert config.data_dir == tmp_path / "data"


def test_invalid_rate_rejected_before_browser_use():
    for value in (0, 2, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            load_config(rate=value, env={})


def test_unknown_configuration_key_rejected(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[wangda]\nprot=1234\n')
    with pytest.raises(ValueError, match="Unknown"):
        load_config(config_file=path, env={})


def test_defaults_have_no_agent_paths():
    config = load_config(env={})
    assert config.data_dir.is_absolute()
    assert ".hermes" not in str(config.data_dir)
    assert isinstance(config.profile, Path)


def test_resume_baseline_keeps_settings_but_explicit_sources_override_them(tmp_path):
    config = load_config(base={'rate': 1.0, 'port': 9339}, data_dir=tmp_path,
                         env={'WANDA_RATE': '1.2'})
    assert config.rate == 1.2
    assert config.port == 9339
