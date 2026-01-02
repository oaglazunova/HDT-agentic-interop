import hdt_sources_mcp.connectors.gamebus.walk_fetch as wf
import hdt_sources_mcp.connectors.google_fit.walk_fetch as gf


def test_gamebus_adapter_monkeypatched_module(monkeypatch):
    # prevent network
    def fake_get_json(endpoint, headers=None, params=None):
        return {"any": "json"}  # parser is stubbed, so shape doesn't matter

    monkeypatch.setattr(wf.DEFAULT_HTTP_CLIENT, "get_json", fake_get_json)

    # parser stub -> deterministic output
    monkeypatch.setattr(
        wf,
        "parse_walk_activities",
        lambda raw: [{"date": "2025-11-03", "steps": 321}],
    )

    out = wf.fetch_walk_data("p-1", auth_bearer=None)
    assert out and out[0]["steps"] == 321



def test_google_fit_adapter_monkeypatched_module(monkeypatch):
    monkeypatch.setenv("HDT_TZ", "UTC")

    def fake_get_json(url, headers=None, params=None):
        return {"any": "json"}

    monkeypatch.setattr(gf.DEFAULT_HTTP_CLIENT, "get_json", fake_get_json)
    monkeypatch.setattr(
        gf,
        "parse_google_fit_walk_data",
        lambda raw: [{"date": "2025-11-04", "steps": 654}],
    )

    out = gf.fetch_google_fit_walk_data("p-2", auth_bearer=None, start_date="2025-11-04", end_date="2025-11-05")
    assert out and out[0]["steps"] == 654

