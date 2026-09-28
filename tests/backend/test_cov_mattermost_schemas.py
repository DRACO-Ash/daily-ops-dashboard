"""Ask spec validation: the rules that stop a bad ask being saved."""

from datetime import date

import pytest
from app.schemas.mattermost import MAX_PATTERN_LENGTH, AskCreate, AskSpec
from pydantic import ValidationError


def test_entries_are_trimmed_and_blanks_dropped() -> None:
    spec = AskSpec(terms=["  COSMOS 2589 ", "", "   "], authors=[" a "])
    assert (spec.terms, spec.authors) == (["COSMOS 2589"], ["a"])


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({}, "at least one of terms, any_terms, authors or channels"),
        ({"terms": ["   "]}, "at least one of"),
        ({"terms": ["x" * 101]}, "100 characters or fewer"),
        ({"terms": ["x"], "after": date(2026, 2, 1), "before": date(2026, 1, 1)}, "on or before"),
        ({"terms": ["x"], "extract": {"pattern": "("}}, "Invalid pattern"),
        ({"terms": ["x"], "extract": {"pattern": "(a)(b)"}}, "at most one capture group"),
        ({"terms": ["x"], "extract": {"pattern": "a" * (MAX_PATTERN_LENGTH + 1)}}, "at most"),
        ({"terms": ["x"], "scope": "everything"}, "scope"),
        ({"terms": ["x"], "unknown": 1}, "Extra inputs"),
        ({"terms": [str(n) for n in range(21)]}, "at most 20"),
    ],
)
def test_invalid_specs_are_rejected(fields: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AskSpec(**fields)


def test_any_terms_alone_narrow_the_pull() -> None:
    assert AskSpec(any_terms=["flare"]).include_archived is True


@pytest.mark.parametrize("minutes", [14, 10081])
def test_refresh_interval_is_bounded(minutes: int) -> None:
    with pytest.raises(ValidationError):
        AskCreate(name="n", spec=AskSpec(terms=["x"]), refresh_minutes=minutes)
