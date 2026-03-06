from __future__ import annotations

import json
from pathlib import Path

from hdt_mapping_plan.vault_catalog import get_dataset_schema, load_vault_catalog


def test_placeholder_vault_catalog_has_expected_daily_profile_schema() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    catalog = load_vault_catalog(str(repo_root / "datasets" / "vault_catalog.json"))

    cols, types = get_dataset_schema(
        catalog,
        dataset_id="vault_dataset_A",
        table_name="daily_profile",
    )

    assert {"txn_id", "dob", "date", "steps", "calories_in", "water_ml"}.issubset(cols)
    assert types["txn_id"] == "string"
    assert types["steps"] == "int64"
    assert types["calories_in"] == "float64"
    assert types["water_ml"] == "int64"


def test_placeholder_vault_catalog_marks_logical_source() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    raw = json.loads((repo_root / "datasets" / "vault_catalog.json").read_text(encoding="utf-8"))

    assert raw["source"]["kind"] == "logical-placeholder"
    assert raw["datasets"][0]["schema_version"] == "draft-1"
