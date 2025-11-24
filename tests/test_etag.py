def test_etag_304_roundtrip(app_client, monkeypatch):
    # app_client: Flask test client fixture
    # Arrange: ensure some deterministic response for user 2 (placeholder mock enabled)
    monkeypatch.setenv("HDT_ALLOW_PLACEHOLDER_MOCKS", "1")

    r1 = app_client.get("/get_walk_data?user_id=2", headers={"Authorization": "Bearer MODEL_DEVELOPER_1"})
    assert r1.status_code == 200
    etag = r1.headers.get("ETag")
    assert etag

    r2 = app_client.get("/get_walk_data?user_id=2", headers={
        "Authorization": "Bearer MODEL_DEVELOPER_1",
        "If-None-Match": etag
    })
    assert r2.status_code == 304
    assert r2.get_data(as_text=True) == ""
