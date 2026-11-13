"""Tests for triage configuration parsing and startup validation."""

from config import TriageConfig, load_config


def test_defaults_are_disabled():
    cfg = TriageConfig()
    assert cfg.enabled is False
    assert cfg.mode == "shadow"
    assert cfg.deadline_s == 60
    assert cfg.reply_enabled is True
    assert cfg.hold_notification is True
    assert cfg.hold_timeout_s == 240
    assert cfg.auto_min_confidence == 0.85
    assert cfg.auto_approve is True
    assert cfg.auto_deny is True


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


def test_auto_mode_is_accepted(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("BRG_TRIAGE_ENABLED", "true")
    monkeypatch.setenv("BRG_TRIAGE_MODE", "auto")
    monkeypatch.setenv("BRG_TRIAGE_URL", "http://hermes/x")
    monkeypatch.setenv("BRG_TRIAGE_SECRET", "out")
    monkeypatch.setenv("BRG_TRIAGE_CALLBACK_SECRET", "cb")
    monkeypatch.setenv("BRG_TRIAGE_HOLD_NOTIFICATION", "false")
    monkeypatch.setenv("BRG_TRIAGE_HOLD_TIMEOUT_S", "90")
    monkeypatch.setenv("BRG_TRIAGE_AUTO_MIN_CONFIDENCE", "0.9")
    monkeypatch.setenv("BRG_TRIAGE_AUTO_APPROVE", "false")
    monkeypatch.setenv("BRG_TRIAGE_AUTO_DENY", "true")
    cfg = _load_env_only(monkeypatch, tmp_path)
    assert cfg.triage.mode == "auto"
    assert cfg.triage.enabled is True
    assert cfg.triage.hold_notification is False
    assert cfg.triage.hold_timeout_s == 90
    assert cfg.triage.auto_min_confidence == 0.9
    assert cfg.triage.auto_approve is False
    assert cfg.triage.auto_deny is True
    assert "not implemented" not in caplog.text


def test_unknown_mode_falls_back_to_shadow(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("BRG_TRIAGE_ENABLED", "true")
    monkeypatch.setenv("BRG_TRIAGE_MODE", "yolo")
    monkeypatch.setenv("BRG_TRIAGE_URL", "http://hermes/x")
    monkeypatch.setenv("BRG_TRIAGE_SECRET", "out")
    monkeypatch.setenv("BRG_TRIAGE_CALLBACK_SECRET", "cb")
    cfg = _load_env_only(monkeypatch, tmp_path)
    assert cfg.triage.mode == "shadow"
    assert "yolo" in caplog.text


def test_short_hold_warns(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("BRG_TRIAGE_ENABLED", "true")
    monkeypatch.setenv("BRG_TRIAGE_URL", "http://hermes/x")
    monkeypatch.setenv("BRG_TRIAGE_SECRET", "out")
    monkeypatch.setenv("BRG_TRIAGE_CALLBACK_SECRET", "cb")
    monkeypatch.setenv("BRG_TRIAGE_DEADLINE_S", "120")
    monkeypatch.setenv("BRG_TRIAGE_HOLD_TIMEOUT_S", "30")
    cfg = _load_env_only(monkeypatch, tmp_path)
    assert cfg.triage.hold_timeout_s == 30
    assert "hold_timeout_s" in caplog.text
