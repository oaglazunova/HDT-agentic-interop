import pytest
from validation import sanitize_walk_record, sanitize_walk_records, ValidationError

def test_date_only_ok():
    assert sanitize_walk_record({"date":"2025-11-24","steps":1})["date"] == "2025-11-24"

def test_datetime_ok():
    assert sanitize_walk_record({"date":"2025-11-24 12:34:56","steps":0})["date"] == "2025-11-24 12:34:56"

def test_tz_rejected():
    with pytest.raises(ValidationError):
        sanitize_walk_record({"date":"2025-11-24T12:00:00+01:00","steps":10})

def test_steps_non_negative():
    with pytest.raises(ValidationError):
        sanitize_walk_record({"date":"2025-11-24","steps":-1})

def test_numeric_coercion():
    r = sanitize_walk_record({
        "date":"2025-11-24",
        "steps":"12",
        "distance_meters":"3.5",
        "kcalories":"1"
    })
    assert r["steps"] == 12 and r["distance_meters"] == 3.5 and r["kcalories"] == 1.0
