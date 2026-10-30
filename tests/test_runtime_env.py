"""Tests for materialize_gcp_credentials (the managed-pool credentials bridge)."""

import json

import pytest

from src.orchestration.runtime_env import materialize_gcp_credentials

KEY = {"type": "service_account", "project_id": "p", "private_key": "x", "client_email": "a@b"}


def test_keeps_an_existing_key_file(monkeypatch):
    monkeypatch.setenv("GCP_CREDENTIALS_PATH", "/local/key.json")
    monkeypatch.setenv("GCP_CREDENTIALS_JSON", json.dumps(KEY))
    assert materialize_gcp_credentials() == "/local/key.json"


def test_nothing_to_do_without_any_credentials(monkeypatch):
    monkeypatch.delenv("GCP_CREDENTIALS_PATH", raising=False)
    monkeypatch.delenv("GCP_CREDENTIALS_JSON", raising=False)
    assert materialize_gcp_credentials() is None


@pytest.mark.parametrize("raw", [json.dumps(KEY), repr(KEY)])
def test_writes_json_or_dict_repr_to_a_private_file(monkeypatch, raw):
    monkeypatch.delenv("GCP_CREDENTIALS_PATH", raising=False)
    monkeypatch.setenv("GCP_CREDENTIALS_JSON", raw)
    path = materialize_gcp_credentials()
    try:
        with open(path, encoding="utf-8") as handle:
            assert json.load(handle) == KEY
        assert json.loads(__import__("os").environ["GCP_CREDENTIALS_JSON"]) == KEY
        assert __import__("os").environ["GCP_CREDENTIALS_PATH"] == path
        assert (__import__("os").stat(path).st_mode & 0o777) == 0o600
    finally:
        __import__("os").remove(path)


def test_rejects_garbage(monkeypatch):
    monkeypatch.delenv("GCP_CREDENTIALS_PATH", raising=False)
    monkeypatch.setenv("GCP_CREDENTIALS_JSON", "not a key")
    with pytest.raises(ValueError):
        materialize_gcp_credentials()
