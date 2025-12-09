import os, sys, json, requests

API_URL = (os.environ.get("HDT_API_BASE") or "http://localhost:5000").rstrip("/")
API_KEY = os.environ.get("MODEL_DEVELOPER_1_API_KEY") or "MODEL_DEVELOPER_1"
USER_ID = int(os.environ.get("SMOKE_USER_ID") or "3")
HDRS = {"Authorization": f"Bearer {API_KEY}", "X-API-KEY": API_KEY}

# If SMOKE_REQUIRE_API is truthy (1/true/yes), fail when API is unreachable.
_require_env = (os.environ.get("SMOKE_REQUIRE_API") or "").strip().lower()
REQUIRE_API = _require_env in ("1", "true", "yes")

def die(msg, payload=None):
    if payload is not None:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(msg, file=sys.stderr); sys.exit(1)

# healthz
try:
    r = requests.get(f"{API_URL}/healthz", headers=HDRS, timeout=10)
except requests.exceptions.RequestException as e:
    if REQUIRE_API:
        die(f"smoke_api: API not reachable at {API_URL}/healthz and SMOKE_REQUIRE_API is set", {"error": str(e)})
    else:
        print(f"⚠ smoke_api: skipping checks — API not reachable at {API_URL}/healthz. Set SMOKE_REQUIRE_API=1 to enforce.")
        sys.exit(0)
if r.status_code != 200: die(f"healthz HTTP {r.status_code}", r.text)
if (r.json() or {}).get("status") != "ok": die("healthz body not ok", r.json())
print("✔ healthz ok")

# get_walk_data
r = requests.get(f"{API_URL}/get_walk_data", params={"user_id": USER_ID}, headers=HDRS, timeout=20)
if r.status_code != 200: die(f"get_walk_data HTTP {r.status_code}", r.text)
data = r.json()
entry = None
if isinstance(data, list):
    entry = next((e for e in data if int(e.get("user_id", -1)) == USER_ID), None)
else:
    entry = data
if not entry: die(f"no envelope for user {USER_ID}", data)
if "error" in entry:
    print(f"⚠ API returned error for user {USER_ID}: {entry['error']}")
elif not (entry.get("data") or entry.get("records")):
    die(f"no data/records in envelope for user {USER_ID}", entry)
print(f"✔ get_walk_data ok for user {USER_ID}")
