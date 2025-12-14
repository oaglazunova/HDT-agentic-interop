from __future__ import annotations
import os
import warnings
import time
from datetime import date, timedelta

import pytest

from hdt_mcp import vault


def _init_tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "v_more.db"
    monkeypatch.setenv("HDT_VAULT_PATH", str(db))
    vault.init()
    return db


def test_read_walk_between_inclusive_and_order(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    uid = 101
    d1 = (date.today() - timedelta(days=2)).isoformat()
    d2 = (date.today() - timedelta(days=1)).isoformat()
    d3 = date.today().isoformat()
    vault.write_walk(uid, [
        {"date": d1, "steps": 1},
        {"date": d2, "steps": 2},
        {"date": d3, "steps": 3},
    ])
    rows = vault.read_walk_between(uid, d2, d3)
    # inclusive range and ordered oldest→newest
    assert [r["steps"] for r in rows] == [2, 3]


def test_retain_last_days_global_and_per_user(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    # two users
    old = "2000-01-01"
    future = "2099-01-01"
    vault.write_walk(1, [{"date": old, "steps": 10}, {"date": future, "steps": 20}])
    vault.write_walk(2, [{"date": old, "steps": 30}, {"date": future, "steps": 40}])

    # Global retention (user_id None)
    deleted_global = vault.retain_last_days(1)  # anything older than ~yesterday gets pruned
    assert deleted_global >= 2

    # Per-user retention (only user 2 should be considered here)
    deleted_user = vault.retain_last_days(1, user_id=2)
    assert deleted_user == 0  # user 2's old already removed by global step above

    # Remaining should be the future-dated records for both users
    assert vault.count_walk_records() == 2
    assert vault.count_walk_records(1) == 1
    assert vault.count_walk_records(2) == 1


def test_count_purge_compact_and_close_paths(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    uid = 55
    vault.write_walk(uid, [
        {"date": "2025-01-01", "steps": 1},
        {"date": "2025-01-02", "steps": 2},
    ])
    assert vault.count_walk_records(uid) == 2

    # compact should run without error when connection exists
    vault.compact()

    # purge this user
    deleted = vault.purge_user(uid)
    assert deleted >= 1
    assert vault.count_walk_records(uid) == 0

    # calling compact safely when connection is closed (covers early return)
    vault.close()
    vault.compact()


def test_init_path_resolution_and_legacy_env(monkeypatch, tmp_path):
    # Prefer HDT_VAULT_PATH when provided
    p = tmp_path / "picked.db"
    monkeypatch.setenv("HDT_VAULT_PATH", str(p))
    vault.init()
    assert vault.get_db_path() and str(p) in vault.get_db_path()

    # If HDT_VAULT_PATH absent, honor legacy HDT_VAULT_DB with a warning
    vault.close()
    monkeypatch.delenv("HDT_VAULT_PATH", raising=False)
    legacy = tmp_path / "legacy.db"
    monkeypatch.setenv("HDT_VAULT_DB", str(legacy))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        vault.init()
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert vault.get_db_path() and str(legacy) in vault.get_db_path()
