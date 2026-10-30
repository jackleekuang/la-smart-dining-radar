"""Make GCP credentials usable by every tool in the flow, wherever the flow runs.

On Prefect's managed work pool the service-account key arrives as the env var
GCP_CREDENTIALS_JSON (filled from a Prefect Secret block, see prefect.yaml). The
BigQuery client reads that directly, but dbt (profiles.yml) and Soda
(soda/configuration.yml) need a key *file*, so the JSON is written to a private temp
file and GCP_CREDENTIALS_PATH is pointed at it. Locally, where GCP_CREDENTIALS_PATH
is already set, nothing changes.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile


def _normalize_key(raw: str) -> str:
    """Return the key as JSON text.

    A Secret block that stores the key as a JSON object can reach the env var as a
    Python dict repr (single quotes), which json.loads rejects; accept both forms.
    """
    try:
        return json.dumps(json.loads(raw))
    except ValueError:
        value = ast.literal_eval(raw)  # raises ValueError/SyntaxError on anything else
        if not isinstance(value, dict):
            raise ValueError("GCP_CREDENTIALS_JSON is not a service-account key object")
        return json.dumps(value)


def materialize_gcp_credentials() -> str | None:
    """Write GCP_CREDENTIALS_JSON to a key file if no key file is configured.

    Returns:
        The key file path now in GCP_CREDENTIALS_PATH, or None if there is nothing to do.

    Raises:
        ValueError: GCP_CREDENTIALS_JSON is set but is not a key object (fail before any step runs).
    """
    if os.getenv("GCP_CREDENTIALS_PATH"):
        return os.environ["GCP_CREDENTIALS_PATH"]
    raw = os.getenv("GCP_CREDENTIALS_JSON")
    if not raw:
        return None
    try:
        key_json = _normalize_key(raw)
    except (ValueError, SyntaxError) as exc:
        raise ValueError("GCP_CREDENTIALS_JSON is not valid key JSON") from exc
    os.environ["GCP_CREDENTIALS_JSON"] = key_json  # the BigQuery client parses this too
    fd, path = tempfile.mkstemp(prefix="gcp-sa-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(key_json)
    os.chmod(path, 0o600)
    os.environ["GCP_CREDENTIALS_PATH"] = path
    return path


def ensure_distutils() -> None:
    """Make `import distutils` work before importing Soda Core on Python 3.12+.

    Soda Core still imports distutils, which Python 3.12 removed. setuptools ships a
    replacement, normally activated by a .pth file at interpreter start. On Prefect's
    managed pool the packages are installed inside the already-running process, so the
    .pth hook never fires; importing setuptools activates the same replacement directly.
    """
    import importlib

    importlib.invalidate_caches()  # see packages installed after this process started
    try:
        import distutils  # noqa: F401
    except ModuleNotFoundError:
        import setuptools  # noqa: F401  (setuptools/__init__ installs the distutils shim)
