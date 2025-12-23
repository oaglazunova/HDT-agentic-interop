"""Create a deterministic local vault (SQLite) with synthetic walk records.

The vault is intended for offline demos (artifact evaluation / IEEE paper).
It stores only synthetic records and can be safely distributed.

Usage:
  python scripts/init_sample_vault.py
  python scripts/init_sample_vault.py --db artifacts/vault/demo.sqlite
  python scripts/init_sample_vault.py --user-id 1
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hdt_config.settings import repo_root
from hdt_mcp import vault_store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db",
        default=None,
        help="Path to SQLite file (default: artifacts/vault/hdt_vault_ieee_demo.sqlite)",
    )
    ap.add_argument("--user-id", type=int, default=1)
    args = ap.parse_args()

    root = repo_root()
    db_path = Path(args.db) if args.db else (root / "artifacts" / "vault" / "hdt_vault_ieee_demo.sqlite")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    vault_store.init(str(db_path))

    # Small, deterministic sample window (matches the mock source dates).
    records = [
        {"date": "2025-11-01", "steps": 2310, "distance_meters": 1520.0, "duration": 900.0, "kcalories": 110.5},
        {"date": "2025-11-02", "steps": 5421, "distance_meters": 3510.0, "duration": 2100.0, "kcalories": 255.2},
        {"date": "2025-11-03", "steps": 123, "distance_meters": 80.0, "duration": 120.0, "kcalories": 7.0},
    ]

    out = vault_store.upsert_walk(int(args.user_id), records, source="gamebus")
    print(f"Vault DB: {db_path}")
    print(f"Upsert result: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
