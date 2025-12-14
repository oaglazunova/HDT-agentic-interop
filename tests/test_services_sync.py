from hdt_mcp.domain.services import HDTService
from hdt_mcp.domain.models import WalkRecord


class StubWalkSource:
    def fetch_walk(self, user_id: int, *, from_iso=None, to_iso=None, limit=None, offset=None):
        if user_id == 1:  # simulate "gamebus"
            return [WalkRecord.model_validate({"date": "2025-11-01", "steps": 100})]
        if user_id == 2:  # simulate "google fit"
            return [WalkRecord.model_validate({"date": "2025-11-02", "steps": 200})]
        if user_id == 3:  # "placeholder-demo"
            return [WalkRecord.model_validate({"date": "1970-01-01", "steps": 0})]
        return []


def test_walk_stream_routes_with_stub():
    svc = HDTService(walk_source=StubWalkSource())

    v1 = svc.walk_stream(user_id=1)
    v2 = svc.walk_stream(user_id=2)
    v3 = svc.walk_stream(user_id=3)
    vX = svc.walk_stream(user_id=999)

    assert v1.records and v1.records[0].steps == 100
    assert v2.records and v2.records[0].steps == 200
    assert isinstance(v3.records, list) and len(v3.records) >= 1
    assert vX.records == []
