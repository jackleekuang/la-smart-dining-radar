"""Tests for src.orchestration.soda_exit. Pure logic, no Soda install required."""

import pytest

from src.orchestration.soda_exit import SodaOutcome, interpret_soda_exit_code


def test_zero_means_passed() -> None:
    assert interpret_soda_exit_code(0) is SodaOutcome.PASSED


def test_one_means_warnings_only() -> None:
    # A warn-level check must not halt the pipeline.
    assert interpret_soda_exit_code(1) is SodaOutcome.WARNED


@pytest.mark.parametrize("code", [2, 3, 127, -9])
def test_failures_errors_and_unknown_codes_fail_closed(code: int) -> None:
    assert interpret_soda_exit_code(code) is SodaOutcome.FAILED
