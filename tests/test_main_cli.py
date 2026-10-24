"""Unit tests for main.py verifying setup validation and safety confirmations."""

import os
from unittest.mock import patch

from main import check_setup_status


def test_check_setup_status_detects_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini")
    monkeypatch.setenv("GROQ_API_KEY", "test_groq")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_openrouter")
    monkeypatch.setenv("GMAIL_EMAIL", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app_pass")
    monkeypatch.setenv("TEST_MODE", "true")

    status = check_setup_status(load_env=False)
    assert status["gemini_api_key"] is True
    assert status["groq_api_key"] is True
    assert status["openrouter_api_key"] is True
    assert status["gmail_configured"] is True
    assert status["test_mode"] is True
    assert status["candidates_count"] >= 1


def test_check_setup_status_detects_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GMAIL_EMAIL", raising=False)
    monkeypatch.setenv("TEST_MODE", "false")

    status = check_setup_status(load_env=False)
    assert status["gemini_api_key"] is False
    assert status["gmail_configured"] is False
    assert status["test_mode"] is False
