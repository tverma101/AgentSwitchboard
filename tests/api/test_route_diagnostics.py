from fastapi.testclient import TestClient

from free_claude_code.config.settings import Settings
from tests.api.support import create_test_app


def _local_client(app):
    return TestClient(app, client=("127.0.0.1", 50000))


def test_admin_route_diagnostic_is_local_zero_network_and_uncached() -> None:
    settings = Settings()
    settings.model = "opencode_go/muse-spark-1.2-contributor"
    app = create_test_app(settings)

    response = _local_client(app).post(
        "/admin/api/diagnostics/route",
        json={"shapes": ["text"]},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["network"] == "none"
    assert body["billable_requests"] == 0
    assert body["controller"]["provider"] == "opencode_go"
    assert body["controller"]["model"] == "muse-spark-1.2-contributor"
    assert "synthetic diagnostic request" not in response.text


def test_admin_route_diagnostic_rejects_unknown_shapes() -> None:
    response = _local_client(create_test_app()).post(
        "/admin/api/diagnostics/route",
        json={"shapes": ["raw-prompt"]},
    )

    assert response.status_code == 422
    assert "unknown synthetic request shape" in response.json()["detail"]


def test_admin_route_diagnostic_is_loopback_only() -> None:
    app = create_test_app()
    remote = TestClient(app, client=("203.0.113.10", 50000))

    response = remote.post(
        "/admin/api/diagnostics/route",
        json={"shapes": ["text"]},
    )

    assert response.status_code == 403
