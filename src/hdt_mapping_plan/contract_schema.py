from __future__ import annotations

from typing import Any, Mapping


def required_leaf_pointers(schema: Mapping[str, Any], prefix: str = "") -> list[str]:
    """
    Collect required leaf JSON Pointers from a JSON Schema (object-only traversal).
    Only recurse into an object if that object is required at this level.
    """
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    required = set(schema.get("required") or [])
    out: list[str] = []
    for name, sub in props.items():
        p = f"{prefix}/{name}"
        if isinstance(sub, dict) and isinstance(sub.get("properties"), dict):
            if name in required:
                out.extend(required_leaf_pointers(sub, p))
        else:
            if name in required:
                out.append(p)
    return out
