"""配置系统测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsh_autonomous_learning.config import ConfigError, load_config


def test_defaults_are_valid(home: Path):
    cfg = load_config(home=home)
    assert cfg.learning.default_mode == "assisted"
    assert cfg.embedding.provider == "hashing"
    assert cfg.model.provider == "mock"
    assert Path(cfg.paths.db_path).parent == Path(cfg.paths.data_dir)
    assert cfg.learning.chunk_overlap < cfg.learning.chunk_size


def test_unknown_key_rejected(home: Path):
    path = home / "bad.json"
    path.write_text(json.dumps({"learning": {"unknown_option": 1}}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path=path, home=home)


def test_file_and_env_override(home: Path, monkeypatch):
    path = home / "config.json"
    path.write_text(json.dumps({"learning": {"default_mode": "auto"}}), encoding="utf-8")
    monkeypatch.setenv("DSH_AL_LOG_LEVEL", "debug")
    cfg = load_config(path=path, home=home)
    assert cfg.learning.default_mode == "auto"
    assert cfg.logging.level == "DEBUG"


def test_openai_provider_requires_key(home: Path, monkeypatch):
    monkeypatch.delenv("DSH_AL_MODEL_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        load_config(
            home=home,
            overrides={"model": {"provider": "openai", "base_url": "https://example.com/v1"}},
        )


def test_paths_are_resolved_under_home(home: Path):
    cfg = load_config(home=home, overrides={"paths": {"data_dir": str(home / "custom")}})
    assert cfg.paths.db_path.startswith(str(home / "custom"))
    assert cfg.paths.index_dir.startswith(str(home / "custom"))
