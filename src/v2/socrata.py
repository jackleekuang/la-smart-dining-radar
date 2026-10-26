"""Incremental extraction from a Socrata (SODA 2.x) dataset.

Pure logic only: the HTTP call is injected so the pagination and watermark handling can be
unit-tested without network access. Retries live on the Prefect task, not here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

FetchPage = Callable[[str, dict[str, str], dict[str, str]], list[dict[str, Any]]]


def build_params(
    naics_field: str,
    naics_prefix: str,
    watermark: str | None,
    limit: int,
    offset: int,
) -> dict[str, str]:
    """Build SoQL query parameters for one page.

    Args:
        naics_field: Column holding the NAICS code in the source dataset.
        naics_prefix: Keep only rows whose NAICS starts with this prefix (e.g. "722").
        watermark: ISO timestamp; only rows whose Socrata system field ``:updated_at`` is
            strictly later are returned. ``None`` means a full load.
        limit: Page size.
        offset: Row offset for pagination.

    Returns:
        Query-string parameters. ``:updated_at`` and ``:id`` are requested explicitly so the
        loader can store a watermark and a stable row id.
    """
    if not naics_field.replace("_", "").isalnum():
        raise ValueError(f"Unsafe field name: {naics_field!r}")
    if not naics_prefix.isdigit():
        raise ValueError(f"NAICS prefix must be digits: {naics_prefix!r}")

    where = f"{naics_field} like '{naics_prefix}%'"
    if watermark:
        where += f" AND :updated_at > '{_soql_timestamp(watermark)}'"
    return {
        "$select": ":id, :updated_at, *",
        "$where": where,
        "$order": ":id",
        "$limit": str(limit),
        "$offset": str(offset),
    }


def _soql_timestamp(value: str) -> str:
    """Normalize an ISO timestamp to SoQL's floating timestamp format (no timezone suffix)."""
    value = value.strip().replace(" ", "T")
    for suffix in ("+00:00", "Z"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    if not value[:4].isdigit():
        raise ValueError(f"Not an ISO timestamp: {value!r}")
    return value


def iter_pages(
    fetch_page: FetchPage,
    url: str,
    naics_field: str,
    naics_prefix: str,
    watermark: str | None,
    page_size: int,
    headers: dict[str, str] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield pages of rows until the source returns a short page."""
    offset = 0
    while True:
        params = build_params(naics_field, naics_prefix, watermark, page_size, offset)
        rows = fetch_page(url, params, headers or {})
        if rows:
            yield rows
        if len(rows) < page_size:
            return
        offset += page_size


def to_raw_rows(rows: list[dict[str, Any]], loaded_at_iso: str) -> list[dict[str, Any]]:
    """Map Socrata rows to the raw table shape: keep the full payload, lift out keys we index on.

    The payload is stored untouched (ELT): if the city renames a column, nothing is lost at
    load time and the change surfaces in dbt/Soda instead of silently dropping data.
    """
    import json

    out = []
    for row in rows:
        out.append(
            {
                "source_row_id": row.get(":id"),
                "source_updated_at": row.get(":updated_at"),
                "payload": json.dumps(row, ensure_ascii=False, sort_keys=True),
                "_loaded_at": loaded_at_iso,
            }
        )
    return out
