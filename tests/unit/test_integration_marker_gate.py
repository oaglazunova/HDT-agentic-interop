import pytest

pytestmark = pytest.mark.integration


def test_integration_marker_is_gated() -> None:
    # This test should be skipped unless --run-integration is set.
    assert True
