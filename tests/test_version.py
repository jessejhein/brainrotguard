"""Tests for build/version identification."""

import importlib
import re

import version as version_module


def _reload(monkeypatch, build_sha: str | None = None):
    if build_sha is None:
        monkeypatch.delenv("BRG_BUILD_SHA", raising=False)
    else:
        monkeypatch.setenv("BRG_BUILD_SHA", build_sha)
    return importlib.reload(version_module)


def test_version_core_stays_numeric():
    """The updater parses __version__ with int(x) per dot-part — no suffix allowed."""
    assert re.fullmatch(r"\d+(\.\d+)+", version_module.__version__)
    assert tuple(int(x) for x in version_module.__version__.split("."))


def test_label_has_build_suffix():
    label = version_module.version_label()
    assert label.startswith(version_module.__version__ + "-")
    assert re.fullmatch(r"\d+(\.\d+)+-([0-9a-f]{7}(-dirty)?|nogit)", label)


def test_env_build_sha_wins(monkeypatch):
    mod = _reload(monkeypatch, "abc1234")
    try:
        assert mod.__build__ == "abc1234"
        assert mod.version_label() == f"{mod.__version__}-abc1234"
    finally:
        _reload(monkeypatch)


def test_missing_git_falls_back_to_nogit(monkeypatch):
    monkeypatch.delenv("BRG_BUILD_SHA", raising=False)
    monkeypatch.setattr(version_module, "_git_build_id", lambda: "")
    try:
        assert version_module._build_id() == "nogit"
    finally:
        monkeypatch.undo()


def test_git_build_id_shape_when_available(monkeypatch):
    monkeypatch.delenv("BRG_BUILD_SHA", raising=False)
    build = version_module._git_build_id()
    if not build:
        return  # not a git checkout (e.g. sdist) — fallback path covers it
    assert re.fullmatch(r"[0-9a-f]{7}(-dirty)?", build)
