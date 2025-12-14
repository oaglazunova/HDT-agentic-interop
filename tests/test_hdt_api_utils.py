from hdt_api.hdt_api_utils import paginate, _build_url_with_params

def test_paginate_unknown_total_needs_returned_count():
    page, has_next = paginate(None, 3, 0, returned_count=3)
    assert has_next is True
    page, has_next = paginate(None, 3, 0, returned_count=2)
    assert has_next is False

def test_build_url_merges_params():
    u = _build_url_with_params("http://x/a?user_id=1", limit=10, offset=20)
    assert "user_id=1" in u and "limit=10" in u and "offset=20" in u
