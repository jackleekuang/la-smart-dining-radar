"""max_timestamp must keep sub-second precision (re-load bug found on the first managed-pool runs)."""

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

bq = pytest.importorskip("src.v2.bq")


def _client_returning(value):
    client = MagicMock()
    client.query.return_value.result.return_value = iter([SimpleNamespace(wm=value)])
    return client


def test_watermark_keeps_milliseconds():
    value = dt.datetime(2026, 10, 16, 16, 48, 50, 123000, tzinfo=dt.timezone.utc)
    with patch.object(bq, "get_bigquery_client", return_value=_client_returning(value)):
        assert bq.max_timestamp("raw_la_city_businesses", "source_updated_at") == "2026-10-16T16:48:50.123"


def test_watermark_none_for_empty_table():
    with patch.object(bq, "get_bigquery_client", return_value=_client_returning(None)):
        assert bq.max_timestamp("raw_la_city_businesses", "source_updated_at") is None
