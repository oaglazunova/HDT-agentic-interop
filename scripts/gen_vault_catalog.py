from __future__ import annotations

import argparse
from hdt_mapping_plan.vault_catalog import generate_vault_catalog


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Generate a temporary vault_catalog.json from a concrete SQLite schema. "
            "Secondary path for Phase-1; preferred path is a hand-authored logical --vault-catalog."
        )
    )
    ap.add_argument("--vault-db", required=True)
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--table",
        action="append",
        default=None,
        help="repeatable; limit to specific table(s) when generating a temporary catalog from SQLite",
    )
    args = ap.parse_args()

    generate_vault_catalog(
        vault_db_path=args.vault_db,
        dataset_id=args.dataset_id,
        out_path=args.out,
        only_tables=args.table,
    )


if __name__ == "__main__":
    main()
