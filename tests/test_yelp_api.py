"""Tests for src.extract.yelp_api. All Yelp API calls are mocked."""

import math
from unittest.mock import Mock, patch

import requests

import src.extract.yelp_api as yelp_api


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in meters."""
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def test_subdivide_returns_four_tiling_points():
    center_lat, center_lng, radius = 34.0407, -118.2468, 3000
    points = yelp_api._subdivide(center_lat, center_lng, radius)

    assert len(points) == 4
    for _lat, _lng, sub_radius in points:
        assert sub_radius == radius // 2

    # Two horizontally-adjacent sub-points (same lat offset sign) should sit
    # ~2x sub_radius apart: edge-touching, no gap and no excess overlap.
    p1, p2 = points[0], points[1]
    dist = _haversine_m(p1[0], p1[1], p2[0], p2[1])
    expected = 2 * points[0][2]
    assert abs(dist - expected) < expected * 0.05


def test_fetch_cell_discovers_and_shares_offset_cap():
    call_log = []

    def fake_search(latitude, longitude, radius, term="restaurants", limit=50, offset=0):
        call_log.append(offset)
        if offset >= 200:
            resp = requests.models.Response()
            resp.status_code = 400
            raise requests.exceptions.HTTPError(response=resp)
        return [{"id": f"biz-{offset}-{i}"} for i in range(50)]

    with patch.object(yelp_api, "_search", side_effect=fake_search), patch.object(yelp_api.time, "sleep"):
        results, discovered_cap = yelp_api.fetch_cell(34.0, -118.0, 1500, max_offset=yelp_api.MAX_OFFSET)
        assert len(results) == 200
        assert discovered_cap == 150

        call_log.clear()
        results2, discovered_cap2 = yelp_api.fetch_cell(34.1, -118.1, 1500, max_offset=discovered_cap)
        assert len(results2) == 200
        assert discovered_cap2 is None
        assert 200 not in call_log  # must not re-probe the known-doomed offset


def test_search_retries_on_429():
    responses = [Mock(status_code=429), Mock(status_code=200)]
    responses[1].json.return_value = {"businesses": [{"id": "biz-1"}]}
    responses[1].raise_for_status.return_value = None

    with patch.object(yelp_api, "YELP_API_KEY", "fake-key"), \
         patch.object(yelp_api.requests, "get", side_effect=responses), \
         patch.object(yelp_api.time, "sleep"):
        result = yelp_api._search(34.0, -118.0, 1500)

    assert result == [{"id": "biz-1"}]


def test_fetch_all_restaurants_covers_all_query_points():
    with patch.object(yelp_api, "fetch_cell", return_value=([{"id": "biz-1"}], None)) as mock_fetch_cell:
        yelp_api.fetch_all_restaurants()

    expected_points = len(yelp_api.CORE_NEIGHBORHOODS) * 4
    assert mock_fetch_cell.call_count == expected_points


def _http_error(status: int, body: str = "") -> requests.exceptions.HTTPError:
    resp = requests.models.Response()
    resp.status_code = status
    resp._content = body.encode()
    return requests.exceptions.HTTPError(f"HTTP {status}", response=resp)


def test_fetch_cell_raises_on_400_at_first_page():
    """A 400 before any page succeeded is a rejected request, not an offset cap (the 2026-10-01 bug)."""
    with patch.object(yelp_api, "_search", side_effect=_http_error(400)), patch.object(yelp_api.time, "sleep"):
        try:
            yelp_api.fetch_cell(34.0, -118.0, 1500)
        except requests.exceptions.HTTPError:
            pass
        else:
            raise AssertionError("expected the 400 to propagate")


def test_fetch_all_restaurants_refuses_empty_batch():
    with patch.object(yelp_api, "fetch_cell", return_value=([], None)):
        try:
            yelp_api.fetch_all_restaurants()
        except RuntimeError as exc:
            assert "0 listings" in str(exc)
        else:
            raise AssertionError("expected an empty extract to fail")


def test_search_error_keeps_yelp_message():
    bad = Mock(status_code=400, ok=False, text='{"error": {"code": "VALIDATION_ERROR"}}')
    with patch.object(yelp_api, "YELP_API_KEY", "fake-key"), \
         patch.object(yelp_api.requests, "get", return_value=bad), \
         patch.object(yelp_api.time, "sleep"):
        try:
            yelp_api._search(34.0, -118.0, 1500)
        except requests.exceptions.HTTPError as exc:
            assert "VALIDATION_ERROR" in str(exc)
        else:
            raise AssertionError("expected HTTPError")
