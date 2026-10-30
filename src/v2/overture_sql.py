"""SQL builders and release detection for the monthly Overture Places snapshot.

Pure functions (no BigQuery client) so they can be unit-tested offline.
"""

from __future__ import annotations

import datetime as dt
import re

_TABLE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
_RELEASE_RE = re.compile(r"\d{4}[-_]\d{2}[-_]\d{2}")


def _check_table(name: str) -> str:
    if not _TABLE_RE.match(name):
        raise ValueError(f"Expected project.dataset.table, got {name!r}")
    return name


def detect_release(labels: dict[str, str] | None, modified: dt.datetime) -> str:
    """Return a release identifier for the public table.

    CARTO puts the Overture release version in the table labels; the exact label key is not
    documented, so take the first label value that looks like a date. Fall back to the table's
    last-modified date so the snapshot key is always deterministic.
    """
    for _key, value in sorted((labels or {}).items()):
        match = _RELEASE_RE.search(value or "")
        if match:
            return match.group(0).replace("_", "-")
    return modified.date().isoformat()


def build_snapshot_insert(
    target_table: str,
    source_table: str,
    bbox: dict[str, float],
    food_regex: str,
) -> str:
    """INSERT ... SELECT that copies one release of LA food-related places into our raw table.

    The full row is stored as JSON (``payload``) so schema changes between Overture releases do
    not break the load; dbt parses the fields. Coordinates are lifted out for spatial work.
    Query parameters: ``@snapshot_release`` (STRING), ``@snapshot_date`` (DATE).
    """
    target_table = _check_table(target_table)
    source_table = _check_table(source_table)
    xmin, ymin, xmax, ymax = (float(bbox[k]) for k in ("xmin", "ymin", "xmax", "ymax"))
    return f"""
INSERT INTO `{target_table}`
  (place_id, lon, lat, payload, snapshot_release, snapshot_date, _loaded_at)
WITH in_bbox AS (
  SELECT
    * EXCEPT (geometry),
    ST_X(ST_CENTROID(geometry)) AS _lon,
    ST_Y(ST_CENTROID(geometry)) AS _lat
  FROM `{source_table}`
  WHERE ST_INTERSECTSBOX(geometry, {xmin}, {ymin}, {xmax}, {ymax})
),
as_json AS (
  SELECT id, _lon, _lat, TO_JSON_STRING(t) AS payload
  FROM in_bbox AS t
)
SELECT
  id AS place_id,
  _lon AS lon,
  _lat AS lat,
  payload,
  @snapshot_release AS snapshot_release,
  @snapshot_date AS snapshot_date,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM as_json
WHERE REGEXP_CONTAINS(LOWER(payload), r'{food_regex}')
""".strip()


def build_release_count_sql(target_table: str) -> str:
    """Count rows already loaded for a release (idempotency check). Param: ``@snapshot_release``."""
    target_table = _check_table(target_table)
    return f"SELECT COUNT(*) AS n FROM `{target_table}` WHERE snapshot_release = @snapshot_release"


def build_release_delete_sql(target_table: str) -> str:
    """Delete one release before a forced reload, so reruns never double-count."""
    target_table = _check_table(target_table)
    return f"DELETE FROM `{target_table}` WHERE snapshot_release = @snapshot_release"
