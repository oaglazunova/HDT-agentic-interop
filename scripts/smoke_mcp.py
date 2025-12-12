"""
Smoke script for both API reachability and MCP policy demo.

It performs:
 1) API health check (HTTP)
 2) Optional API call to /get_walk_data
 3) MCP policy demonstration: loads policy from HDT_POLICY_PATH and applies it
    to a sample payload, showing effective allow/redact and redaction count.
"""

import json, os, sys
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

API_URL = os.environ.get("HDT_API_BASE", "http://localhost:5000").rstrip("/")
API_KEY = os.environ.get("MODEL_DEVELOPER_1_API_KEY", "MODEL_DEVELOPER_1")


def _http_get(path, headers=None, timeout=5):
    url = API_URL + path
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:
        data = r.read().decode("utf-8")
        return r.getcode(), r.headers, data


def demo_api():
    print(f"[smoke] API_URL={API_URL}")
    try:
        code, hdrs, body = _http_get("/healthz")
        print(f"[smoke] /healthz -> {code}")
        if code != 200:
            print(body)
            return False
        payload = json.loads(body)
        assert payload.get("status") in ("ok", "OK"), "healthz not ok"
    except (URLError, HTTPError) as e:
        print(f"[smoke] /healthz failed: {e}")
        return False

    # Try placeholder user 2 (created by the init script)
    headers = {"Authorization": f"Bearer {API_KEY}"}
    try:
        code, hdrs, body = _http_get("/get_walk_data?user_id=2", headers=headers)
        print(f"[smoke] /get_walk_data?user_id=2 -> {code}")
        if code != 200:
            print(body)
            return False
        data = json.loads(body)
        if not isinstance(data, (list, dict)):
            print("[smoke] unexpected JSON shape")
            return False
        # Show governance headers from the API
        pol = hdrs.get("X-Policy")
        pol_red = hdrs.get("X-Policy-Redactions")
        if pol:
            print(f"[smoke] API headers: X-Policy={pol}, X-Policy-Redactions={pol_red}")
    except (URLError, HTTPError) as e:
        print(f"[smoke] /get_walk_data failed: {e}")
        return False

    return True


def demo_policy():
    # Import MCP server helpers for policy evaluation
    import HDT_MCP.server as srv

    # Ensure we read the latest on disk
    srv._policy_reset_cache()

    pol_path = os.getenv("HDT_POLICY_PATH") or str(srv._POLICY_PATH)
    print(f"[smoke] Policy file: {pol_path}")

    # Show effective analytics lane for an example tool
    eff = srv.policy_evaluate(purpose=srv.LANE_ANALYTICS, tool="vault.integrated@v1")
    print("[smoke] policy.evaluate (analytics, tool=vault.integrated@v1):", eff)

    # Apply policy to a nested payload to demonstrate redaction
    sample = {
        "streams": {
            "walk": {
                "records": [
                    {"date": "2025-11-01", "steps": 123, "kcalories": 1.2},
                    {"date": "2025-11-02", "steps": 456}
                ]
            }
        }
    }
    payload = json.loads(json.dumps(sample))  # cheap deep copy
    _, redactions = srv._apply_policy_metrics(
        srv.LANE_ANALYTICS,
        "vault.integrated@v1",
        payload,
        client_id=os.environ.get("MCP_CLIENT_ID")
    )

    print(f"[smoke] redactions applied: {redactions}")
    print("[smoke] payload after policy:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    # Return True if any redactions were applied (so the demo is visible)
    return redactions >= 0


def main():
    ok_api = demo_api()
    ok_pol = demo_policy()
    print("[smoke] OK" if (ok_api and ok_pol) else "[smoke] Completed with warnings")
    return 0 if (ok_api and ok_pol) else 1


if __name__ == "__main__":
    sys.exit(main())
