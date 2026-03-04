from __future__ import annotations

import json
from importlib import resources
from typing import Any, Mapping, Sequence

from hdt_mapping_plan.validate import compute_contract_schema_hash
from hdt_mapping_plan.candidate_retrieval import build_pointer_candidate_cols



_PROMPT_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "items",
    "prefixItems",
    "additionalProperties",
    "enum",
    "const",
    "format",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "$ref",
    "$defs",
    "definitions",
    "allOf",
    "anyOf",
    "oneOf",
}

_SCHEMA_NAME_PRESERVING_KEYS = {"properties", "$defs", "definitions"}


# === helpers: ===============


def _extract_dataset_schema(
    vault_catalog: Mapping[str, Any],
    dataset_id: str,
    table_name: str,
) -> tuple[set[str], dict[str, str]]:
    cols: set[str] = set()
    types: dict[str, str] = {}

    for ds in vault_catalog.get("datasets", []) or []:
        if not isinstance(ds, dict) or ds.get("dataset_id") != dataset_id:
            continue
        for tbl in ds.get("tables", []) or []:
            if not isinstance(tbl, dict) or tbl.get("table_name") != table_name:
                continue
            for c in tbl.get("columns", []) or []:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or "")
                if not name:
                    continue
                cols.add(name)
                t = c.get("type")
                if isinstance(t, str) and t:
                    types[name] = t
            return cols, types

    return cols, types


def _leaf_contract_pointers(schema: Mapping[str, Any], prefix: str = "") -> list[str]:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    out: list[str] = []
    for k, sub in props.items():
        p = f"{prefix}/{k}"
        sub_props = sub.get("properties") if isinstance(sub, dict) else None
        if isinstance(sub_props, dict) and sub_props:
            out.extend(_leaf_contract_pointers(sub, p))
        else:
            out.append(p)
    return out


def _required_leaf_pointers(schema: dict, prefix: str = "") -> list[str]:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []

    required = set(schema.get("required") or [])
    out: list[str] = []

    for name, sub in props.items():
        p = f"{prefix}/{name}"
        if isinstance(sub, dict) and "properties" in sub:
            # If the object itself is required, recurse and collect required leaves under it
            # (and rely on nested "required" to pick leaves)
            if name in required:
                out.extend(_required_leaf_pointers(sub, p))
        else:
            if name in required:
                out.append(p)

    return out


def _sanitize_schema_for_prompt(node: Any) -> Any:
    """
    Keep only structural JSON Schema content for prompting.

    Drops free-text / presentation metadata such as:
      - title
      - description
      - examples
      - default
      - $comment

    Important:
    - This is for LLM prompt context only.
    - Validation and hashing must still use the original schema.
    """
    if isinstance(node, list):
        return [_sanitize_schema_for_prompt(x) for x in node]

    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}

    for key, value in node.items():
        if key in _SCHEMA_NAME_PRESERVING_KEYS and isinstance(value, dict):
            # Preserve arbitrary property names / definition names,
            # but sanitize each subschema beneath them.
            cleaned_children: dict[str, Any] = {}
            for child_name, child_schema in value.items():
                cleaned_children[str(child_name)] = _sanitize_schema_for_prompt(child_schema)
            out[key] = cleaned_children
            continue

        if key in _PROMPT_SCHEMA_KEYS:
            out[key] = _sanitize_schema_for_prompt(value)

    return out

# === end helpers =========================

def load_mapping_plan_schema() -> dict[str, Any]:
    p = resources.files("hdt_mapping_plan").joinpath("schema/mapping-plan.llm.schema.json")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_mapping_plan_llm_schema() -> dict[str, Any]:
    """
    Schema used ONLY for Ollama structured outputs.

    mapping-plan.schema.json contains $ref; Ollama structured outputs often
    don't resolve refs reliably. mapping-plan.llm.schema.json is a flattened,
    LLM-safe schema.
    """
    p = resources.files("hdt_mapping_plan").joinpath("schema/mapping-plan.llm.schema.json")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_base_messages(
    *,
    contract: Mapping[str, Any],
    contract_input_schema: Mapping[str, Any],
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None,
    expected_contract_hash: str,
    dataset_id: str,
    table_name: str,
    dataset_columns: set[str] | None = None,
    dataset_column_types: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:

    contract_input_schema_dict = dict(contract_input_schema)
    prompt_contract_input_schema = _sanitize_schema_for_prompt(contract_input_schema_dict)
    req_ptrs = _required_leaf_pointers(contract_input_schema_dict)
    contract_schema_for_retrieval = contract_input_schema_dict

    # If caller didn't provide schema details for the selected dataset/table, extract them
    # from the vault catalog.
    if dataset_columns is None or dataset_column_types is None:
        extracted_cols, extracted_types = _extract_dataset_schema(
            vault_catalog=vault_catalog,
            dataset_id=dataset_id,
            table_name=table_name,
        )
        if dataset_columns is None:
            dataset_columns = extracted_cols
        if dataset_column_types is None:
            dataset_column_types = extracted_types

    cols = sorted(dataset_columns or [])

    types = {k: dataset_column_types[k] for k in sorted(dataset_column_types or {})}
    algo_id = str(contract.get("algo_id") or "")

    # Use the original contract schema structure (not the prompt-sanitized copy)
    # so retrieval can still see type/format hints.
    contract_schema_for_retrieval = dict(contract_input_schema)

    pointer_to_candidate_cols = build_pointer_candidate_cols(
        required_pointers=req_ptrs,
        dataset_columns=cols,
        dataset_column_types=types,
        contract_input_schema=contract_schema_for_retrieval,
        algo_id=algo_id,
        top_k=3,
    )

    types = {k: dataset_column_types[k] for k in sorted(dataset_column_types or {})}

    return [
        {
            "role": "system",
            "content": (
                "You output ONLY a single JSON object that matches the MappingPlan JSON Schema. "
                "No markdown, no comments, no extra keys. "
                "record_mapping values MUST be expression objects with an 'op'."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Create a Mapping Plan JSON that will pass deterministic validation.",
                    "immutables": {
                        "plan_version": "1.0",
                        "algo": {"algo_id": contract["algo_id"], "algo_version": contract["algo_version"]},
                        "dataset": {"dataset_id": dataset_id, "table_name": table_name},
                        "contract": {
                            "contract_hash": expected_contract_hash,
                            "contract_ref": "oci://local/contracts/UNKNOWN",
                            "input_schema_ref": "oci://local/contracts/UNKNOWN#input.schema.json",
                        },
                    },
                    "contract_input_schema": prompt_contract_input_schema,
                    "contract_required_leaf_pointers": req_ptrs,
                    "pointer_to_candidate_cols": pointer_to_candidate_cols,
                    "dataset_columns": cols,
                    "dataset_column_types": types,
                    "constraints": [
                      "record_mapping is a map: contract JSON Pointer -> expression.",
                      "record_mapping keys MUST be JSON Pointers (start with '/')",
                      "record_mapping MUST include ALL pointers in contract_required_leaf_pointers.",
                      "record_mapping MUST NOT include pointers outside contract_required_leaf_pointers.",
                      "For op:'column', you MUST include {'op':'column','name':'<column>'}.",
                      "For /day/date you MUST output a date-typed expression. If the source column is a string (TEXT), wrap it: {'op':'parse_date','format':'%Y-%m-%d','args':[{'op':'column','name':'date'}]}.",
                      "For /person/birthDate you MUST output a date-typed expression. If the source column is a string (TEXT), wrap it: {'op':'parse_date','format':'%Y-%m-%d','args':[{'op':'column','name':'dob'}]}.",
                      "If pointer_to_candidate_cols has an entry for a pointer AND that column exists in dataset_columns, you MUST use op:'column' with that column name (do NOT use const).",
                      "required_columns MUST contain every referenced column name used by op:'column', and ONLY those.",
                      "If a required pointer cannot be sourced from dataset_columns, use op:'const' instead of inventing a column.",
                      "output.destination MUST start with 'vault://'.",
                      "contract.contract_hash MUST equal exactly the provided expected hash.",
                      "recordId MUST be per-row. If dataset_columns contains 'txn_id', then /recordId MUST be {'op':'column','name':'txn_id'}. Do NOT use const for /recordId in that case.",
                    ],
                    "defaults": {
                        "output": {
                            "destination": "vault://results/job_${JOB_ID}.jsonl",
                            "format": "jsonl",
                            "result_schema_ref": "oci://local/contracts/UNKNOWN#output.schema.json",
                        },
                        "limits": {
                            "max_rows": 10000,
                            "batch_rows": 2000,
                            "max_record_bytes": 8192,
                            "max_total_output_bytes": 10000000,
                        },
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True
            ),
        },
    ]


def generate_mapping_plan_candidate(
    *,
    client,
    base_messages: Sequence[Mapping[str, Any]] | None = None,
    contract: Mapping[str, Any] | None = None,
    contract_input_schema: Mapping[str, Any] | None = None,
    vault_catalog: Mapping[str, Any] | None = None,
    allowed_ops_profile: Mapping[str, Any] | None = None,
    # Optional convenience parameters (used only when base_messages is None)
    expected_contract_hash: str | None = None,
    dataset_id: str | None = None,
    table_name: str | None = None,
    dataset_columns: set[str] | None = None,
    dataset_column_types: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if base_messages is None:
        if contract is None or contract_input_schema is None or vault_catalog is None:
            raise TypeError("pass base_messages OR contract+contract_input_schema+vault_catalog")

        if expected_contract_hash is None:
            expected_contract_hash = compute_contract_schema_hash(contract_input_schema)

        # Infer dataset/table only if unambiguous
        if dataset_id is None or table_name is None:
            datasets = [ds for ds in (vault_catalog.get("datasets", []) or []) if isinstance(ds, dict)]
            if len(datasets) != 1:
                raise TypeError(
                    "vault_catalog contains multiple datasets; pass dataset_id and table_name explicitly "
                    "(or pre-build base_messages via build_base_messages)."
                )
            ds0 = datasets[0]
            tables = [t for t in (ds0.get("tables", []) or []) if isinstance(t, dict)]
            if len(tables) != 1:
                raise TypeError(
                    "vault_catalog contains multiple tables; pass dataset_id and table_name explicitly "
                    "(or pre-build base_messages via build_base_messages)."
                )
            dataset_id = str(ds0.get("dataset_id") or "")
            table_name = str(tables[0].get("table_name") or "")
            if not dataset_id or not table_name:
                raise TypeError("vault_catalog is missing dataset_id/table_name for the selected dataset/table")

        base_messages = build_base_messages(
            contract=contract,
            contract_input_schema=contract_input_schema,
            vault_catalog=vault_catalog,
            allowed_ops_profile=allowed_ops_profile,
            expected_contract_hash=expected_contract_hash,
            dataset_id=dataset_id,
            table_name=table_name,
            dataset_columns=dataset_columns,
            dataset_column_types=dataset_column_types,
        )

    messages = list(base_messages) + [
        {"role": "user", "content": "Return ONE Mapping Plan JSON object only (no markdown, no commentary)."}
    ]
    schema = load_mapping_plan_llm_schema()
    return client.chat_json(messages, json_schema=schema)