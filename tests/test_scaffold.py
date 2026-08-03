"""Smoke tests that the Prompt 0 scaffold is importable."""

from __future__ import annotations


def test_package_version() -> None:
    import vact

    assert vact.__version__ == "0.2.0"


def test_cli_app_imports() -> None:
    from vact.cli import app

    assert app.info.name == "vact"
