# scripts/smoke_mcp.py
import json, os, sys, time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

API_URL = os.environ.get("HDT_API_BASE", "http://localhost:5000")
API_KEY = os.environ.get("MODEL_DEVELOPER_1_API_KEY", "MODEL_DEVELOPER_1")

def get(path, headers=None, timeout=5):
    url = API_URL.rstrip("/") + path
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:
        data = r.read().decode("utf-8")
        return r.getcode(), r.headers, data

def main():
    print(f"[smoke] API_URL={API_URL}")
    # 1) health
    try:
        code, hdrs, body = get("/healthz")
        print(f"[smoke] /healthz -> {code}")
        if code != 200:
            print(body)
            return 1
        payload = json.loads(body)
        assert payload.get("status") in ("ok", "OK"), "healthz not ok"
    except (URLError, HTTPError) as e:
        print(f"[smoke] /healthz failed: {e}")
        return 1

    # 2) walk data with auth
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "X-API-KEY": API_KEY,
    }
    # Try placeholder user 2 (created by the init script)
    try:
        code, hdrs, body = get("/get_walk_data?user_id=2", headers=headers)
        print(f"[smoke] /get_walk_data?user_id=2 -> {code}")
        if code != 200:
            print(body)
            return 1
        data = json.loads(body)
        # Accept either error or data, but the call must succeed syntactically (HTTP 200 or 207)
        if not isinstance(data, (list, dict)):
            print("[smoke] unexpected JSON shape")
            return 1
    except (URLError, HTTPError) as e:
        print(f"[smoke] /get_walk_data failed: {e}")
        return 1

    print("[smoke] OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())
# scripts/smoke_mcp.py
import json, os, sys, time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

API_URL = os.environ.get("HDT_API_BASE", "http://localhost:5000")
API_KEY = os.environ.get("MODEL_DEVELOPER_1_API_KEY", "MODEL_DEVELOPER_1")

def get(path, headers=None, timeout=5):
    url = API_URL.rstrip("/") + path
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:
        data = r.read().decode("utf-8")
        return r.getcode(), r.headers, data

def main():
    print(f"[smoke] API_URL={API_URL}")
    # 1) health
    try:
        code, hdrs, body = get("/healthz")
        print(f"[smoke] /healthz -> {code}")
        if code != 200:
            print(body)
            return 1
        payload = json.loads(body)
        assert payload.get("status") in ("ok", "OK"), "healthz not ok"
    except (URLError, HTTPError) as e:
        print(f"[smoke] /healthz failed: {e}")
        return 1

    # 2) walk data with auth
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "X-API-KEY": API_KEY,
    }
    # Try placeholder user 2 (created by the init script)
    try:
        code, hdrs, body = get("/get_walk_data?user_id=2", headers=headers)
        print(f"[smoke] /get_walk_data?user_id=2 -> {code}")
        if code != 200:
            print(body)
            return 1
        data = json.loads(body)
        # Accept either error or data, but the call must succeed syntactically (HTTP 200 or 207)
        if not isinstance(data, (list, dict)):
            print("[smoke] unexpected JSON shape")
            return 1
    except (URLError, HTTPError) as e:
        print(f"[smoke] /get_walk_data failed: {e}")
        return 1

    print("[smoke] OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())
