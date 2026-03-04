from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


_NON_STRUCTURAL_SCHEMA_KEYS = {
    "$id",
    "title",
    "description",
    "examples",
    "default",
    "$comment",
}


def canonical_json_bytes(obj: Any) -> bytes:
    """
    Canonical JSON encoding for hashing:
      - sort_keys=True
      - separators=(',', ':')
      - UTF-8
      - ensure_ascii=False (stable in your project)
    """
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return s.encode("utf-8")


def sha256_hex_of_json(obj: Any) -> str:
    """
    Returns 64 lowercase hex chars (no 'sha256:' prefix).
    """
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def strip_non_structural_schema_metadata(node: Any) -> Any:
    """
    Return a deep-copied schema-like object with clearly non-structural
    metadata removed.

    This is intentionally a conservative blacklist, not an allowlist:
    we only drop keys that are presentation / annotation oriented and
    should not affect executable mapping compatibility.
    """
    if isinstance(node, list):
        return [strip_non_structural_schema_metadata(x) for x in node]

    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _NON_STRUCTURAL_SCHEMA_KEYS:
            continue
        out[key] = strip_non_structural_schema_metadata(value)
    return out


def sha256_hex_of_structural_schema(schema_obj: Mapping[str, Any]) -> str:
    """
    Hash a provider contract schema after removing clearly cosmetic metadata.

    This keeps contract hashes stable across harmless edits such as changing
    descriptions or examples, while still changing when structural content
    changes.
    """
    stripped = strip_non_structural_schema_metadata(schema_obj)
    return sha256_hex_of_json(stripped)


def is_hex64(s: str) -> bool:
    if len(s) != 64:
        return False
    try:
        int(s, 16)
        return s.lower() == s
    except Exception:
        return False
