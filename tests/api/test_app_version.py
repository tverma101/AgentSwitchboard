import warnings

import pytest
from fastapi.testclient import TestClient

from free_claude_code.core.version import package_version
from tests.api.support import create_test_app


def test_fastapi_and_openapi_report_installed_package_version() -> None:
    app = create_test_app()

    assert app.version == package_version()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Duplicate Operation ID",
            category=UserWarning,
        )
        response = TestClient(app).get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["version"] == package_version()


def test_health_reports_running_daemon_package_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FCC_SERVER_MODE", raising=False)
    response = TestClient(create_test_app()).get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["version"] == package_version()
    assert payload["service"] == "agentswitchboard"
    assert payload["protocol"] == 1
    assert payload["mode"] == "standard"
    assert payload["lifecycle"] == "running"
    assert payload["pid"] > 0
    assert payload["uptime_seconds"] >= 0
    assert "config_dir" not in payload
