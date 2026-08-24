from pathlib import Path

from fastapi.testclient import TestClient

from tests.api.support import create_test_app

ADMIN_STATIC = Path("src/free_claude_code/api/admin_static")


def _local_client():
    return TestClient(create_test_app(), client=("127.0.0.1", 50000))


def test_admin_v2_assets_are_served_uncached():
    client = _local_client()

    for path in (
        "/admin/assets/admin-v2.css",
        "/admin/assets/admin-ui-v2.js",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"


def test_admin_page_loads_density_layer_after_base_assets():
    html = (ADMIN_STATIC / "index.html").read_text(encoding="utf-8")

    base_css = html.index("/admin/assets/admin.css")
    v2_css = html.index("/admin/assets/admin-v2.css")
    base_js = html.index("/admin/assets/admin.js")
    v2_js = html.index("/admin/assets/admin-ui-v2.js")

    assert base_css < v2_css
    assert base_js < v2_js
    assert 'id="providerSearch"' in html
    assert 'data-provider-filter="configured"' in html
    assert 'data-provider-filter="setup"' in html


def test_admin_v2_filter_is_local_ui_only():
    script = (ADMIN_STATIC / "admin-ui-v2.js").read_text(encoding="utf-8")

    assert "fetch(" not in script
    assert "MutationObserver" in script
    assert 'event.key !== "/"' in script
    assert "card.hidden = !show" in script
    assert 'pill?.classList.contains("ok")' in script
