"""Tests for triage configuration parsing and startup validation."""

from config import TriageConfig, load_config


def test_defaults_are_disabled():
    cfg = TriageConfig()
    assert cfg.enabled is False
    assert cfg.mode == "shadow"
    assert cfg.deadline_s == 60
    assert cfg.reply_enabled is True


def _load_env_only(monkeypatch, tmp_path):
    """load_config() with no file present falls back to environment variables."""
    monkeypatch.chdir(tmp_path)
    return load_config()


def test_env_parsing(monkeypatch, tmp_path):
    monkeypatch.setenv("BRG_TRIAGE_ENABLED", "true")
    monkeypatch.setenv("BRG_TRIAGE_MODE", "SHADOW")
    monkeypatch.setenv("BRG_TRIAGE_URL", "http://hermes:8644/p/brgtriage/webhooks/brg-request")
    monkeypatch.setenv("BRG_TRIAGE_SECRET", "out")
    monkeypatch.setenv("BRG_TRIAGE_CALLBACK_SECRET", "cb")
    monkeypatch.setenv("BRG_TRIAGE_DEADLINE_S", "45")
    monkeypatch.setenv("BRG_TRIAGE_REPLY_ENABLED", "false")
    cfg = _load_env_only(monkeypatch, tmp_path)
    assert cfg.triage.enabled is True
    assert cfg.triage.mode == "shadow"
    assert cfg.triage.deadline_s == 45
    assert cfg.triage.reply_enabled is False


def test_env_parsing_without_file(monkeypatch):
    monkeypatch.setenv("BRG_TRIAGE_ENABLED", "true")
    monkeypatch.setenv("BRG_TRIAGE_URL", "http://hermes/x")
    monkeypatch.setenv("BRG_TRIAGE_SECRET", "out")
    monkeypatch.setenv("BRG_TRIAGE_CALLBACK_SECRET", "cb")
    from config import Config
    cfg = Config.from_env()
    assert cfg.triage.enabled is True


def test_incomplete_config_is_disabled_at_load(monkeypatch, tmp_path):
    monkeypatch.setenv("BRG_TRIAGE_ENABLED", "true")
    monkeypatch.setenv("BRG_TRIAGE_URL", "http://hermes/x")
    monkeypatch.delenv("BRG_TRIAGE_SECRET", raising=False)
    monkeypatch.setenv("BRG_TRIAGE_CALLBACK_SECRET", "cb")
    cfg = _load_env_only(monkeypatch, tmp_path)
    assert cfg.triage.enabled is False


def test_unknown_mode_is_preserved_for_the_startup_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("BRG_TRIAGE_ENABLED", "true")
    monkeypatch.setenv("BRG_TRIAGE_MODE", "auto")
    monkeypatch.setenv("BRG_TRIAGE_URL", "http://hermes/x")
    monkeypatch.setenv("BRG_TRIAGE_SECRET", "out")
    monkeypatch.setenv("BRG_TRIAGE_CALLBACK_SECRET", "cb")
    cfg = _load_env_only(monkeypatch, tmp_path)
    assert cfg.triage.mode == "auto"  # refused at runtime, not silently rewritten
    assert cfg.triage.enabled is True
