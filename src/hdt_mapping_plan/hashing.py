from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


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


def is_hex64(s: str) -> bool:
    if len(s) != 64:
        return False
    try:
        int(s, 16)
        return s.lower() == s
    except Exception:
        return False
