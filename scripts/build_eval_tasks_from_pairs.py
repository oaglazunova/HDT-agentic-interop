from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _require_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return dict(value)


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"{field_name} must be a non-empty string")
    return s


def _normalize_columns(columns_value: Any, *, field_name: str) -> list[dict[str, str]]:
    if not isinstance(columns_value, list) or not columns_value:
        raise ValueError(f"{field_name} must be a non-empty list")

    out: list[dict[str, str]] = []
    seen: set[str] = set()

    for idx, item in enumerate(columns_value):
        col = _require_mapping(item, field_name=f"{field_name}[{idx}]")
        name = _require_non_empty_string(col.get("name"), field_name=f"{field_name}[{idx}].name")
        typ = _require_non_empty_string(col.get("type"), field_name=f"{field_name}[{idx}].type")

        if name in seen:
            raise ValueError(f"{field_name} contains duplicate column name: {name}")
        seen.add(name)

        out.append({"name": name, "type": typ})

    return out


def _pointer_parts(ptr: str) -> list[str]:
    if not ptr.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {ptr}")
    parts = [p for p in ptr.split("/")[1:] if p]
    if not parts:
        raise ValueError(f"JSON pointer must not be empty: {ptr}")
    return parts


def _insert_pointer_schema(root: dict[str, Any], ptr: str, leaf_type: str, leaf_format: str | None) -> None:
    parts = _pointer_parts(ptr)
    node = root

    for idx, part in enumerate(parts):
        is_leaf = idx == len(parts) - 1

        node.setdefault("type", "object")
        props = node.setdefault("properties", {})
        if not isinstance(props, dict):
            raise ValueError("internal schema construction error: properties must be an object")

        if is_leaf:
            leaf_schema: dict[str, Any] = {"type": leaf_type}
            if leaf_format:
                leaf_schema["format"] = leaf_format
            props[part] = leaf_schema
            req = node.setdefault("required", [])
            if part not in req:
                req.append(part)
        else:
            child = props.get(part)
            if not isinstance(child, dict):
                child = {"type": "object", "properties": {}, "required": []}
                props[part] = child
            req = node.setdefault("required", [])
            if part not in req:
                req.append(part)
            node = child


def _build_contract_input_schema(required_fields: list[dict[str, Any]]) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    for idx, field in enumerate(required_fields):
        rec = _require_mapping(field, field_name=f"required_fields[{idx}]")
        ptr = _require_non_empty_string(rec.get("pointer"), field_name=f"required_fields[{idx}].pointer")
        leaf_type = _require_non_empty_string(rec.get("type"), field_name=f"required_fields[{idx}].type")
        leaf_format_raw = rec.get("format")
        leaf_format = str(leaf_format_raw).strip() if leaf_format_raw is not None else None
        if leaf_format == "":
            leaf_format = None
        _insert_pointer_schema(schema, ptr, leaf_type, leaf_format)

    return schema


def _normalize_pair_record(item: Any) -> dict[str, Any]:
    rec = _require_mapping(item, field_name="pair item")

    pair_id = _require_non_empty_string(rec.get("pair_id"), field_name="pair_id")

    contract = _require_mapping(rec.get("contract"), field_name=f"{pair_id}.contract")

    dataset = _require_mapping(rec.get("dataset"), field_name=f"{pair_id}.dataset")
    dataset_id = _require_non_empty_string(dataset.get("dataset_id"), field_name=f"{pair_id}.dataset.dataset_id")
    table_name = _require_non_empty_string(dataset.get("table_name"), field_name=f"{pair_id}.dataset.table_name")
    columns = _normalize_columns(dataset.get("columns"), field_name=f"{pair_id}.dataset.columns")

    required_fields_raw = rec.get("required_fields")
    if not isinstance(required_fields_raw, list) or not required_fields_raw:
        raise ValueError(f"{pair_id}.required_fields must be a non-empty list")

    contract_input_schema = _build_contract_input_schema(required_fields_raw)

    task = {
        "task_id": pair_id,
        "contract": contract,
        "contract_input_schema": contract_input_schema,
        "dataset_spec": {
            "dataset_id": dataset_id,
            "table_name": table_name,
            "columns": columns,
        },
    }

    # Optional passthrough metadata for later analysis / provenance.
    if rec.get("metadata") is not None:
        task["metadata"] = rec["metadata"]

    return task


def load_pairs_json(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        items = raw.get("pairs")
        if not isinstance(items, list):
            raise ValueError("pairs JSON object must contain a 'pairs' list")
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError("pairs JSON must be either a list or an object with a 'pairs' list")

    tasks = [_normalize_pair_record(item) for item in items]
    if not tasks:
        raise ValueError("pairs JSON must contain at least one pair")

    seen: set[str] = set()
    for task in tasks:
        task_id = str(task["task_id"])
        if task_id in seen:
            raise ValueError(f"duplicate pair_id/task_id: {task_id}")
        seen.add(task_id)

    return tasks


def write_eval_tasks_json(*, tasks: list[dict[str, Any]], out_path: Path) -> None:
    payload = {"tasks": tasks}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build evaluation task JSON from normalized benchmark-pair records."
    )
    parser.add_argument("--pairs-json", required=True, help="Input normalized benchmark-pairs JSON file.")
    parser.add_argument("--out", required=True, help="Output eval task JSON file.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    tasks = load_pairs_json(Path(args.pairs_json))
    out_path = Path(args.out)
    write_eval_tasks_json(tasks=tasks, out_path=out_path)

    summary = {
        "pairs_in": len(tasks),
        "tasks_out": len(tasks),
        "out": str(out_path),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())