"""Interpret Soda Core scan exit codes.

`soda scan` exits 0 when all checks pass, 1 when only warnings fired, 2 when a
check failed and 3 when the scan itself errored. Treating any non-zero code as
a failure (subprocess ``check=True``) would let a warn-level check halt the
whole pipeline, which defeats the point of having separate warn/fail levels.
"""

from enum import Enum


class SodaOutcome(Enum):
    """Pipeline-level meaning of a Soda scan result."""

    PASSED = "passed"
    WARNED = "warned"
    FAILED = "failed"


def interpret_soda_exit_code(returncode: int) -> SodaOutcome:
    """Map a ``soda scan`` exit code to a pipeline outcome.

    Args:
        returncode: Process exit code from ``soda scan``.

    Returns:
        PASSED for 0, WARNED for 1, FAILED for anything else (check failures,
        scan errors, or unexpected codes -- fail closed).
    """
    if returncode == 0:
        return SodaOutcome.PASSED
    if returncode == 1:
        return SodaOutcome.WARNED
    return SodaOutcome.FAILED
