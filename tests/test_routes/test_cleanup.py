"""
Options that were accepted but did nothing are gone, and refuse clearly instead of
silently doing something else.
"""
import pytest

from app.core.os_images import get_os_config


@pytest.fixture(autouse=True)
def lxc_access(app):
    """CI runs unprivileged; these tests are about validation, not the root check."""
    from app.core.common import check_root
    app.dependency_overrides[check_root] = lambda: True
    yield
    app.dependency_overrides.pop(check_root, None)


def test_unknown_os_is_an_error_not_ubuntu():
    assert get_os_config("debian_12")["release"] == "bookworm"
    with pytest.raises(ValueError, match="Unsupported OS type 'debian_10'"):
        get_os_config("debian_10")


def test_deploy_refuses_os_without_an_image(client):
    for retired in ("debian_10", "debian_11", "ubuntu_20_04", "centos_8"):
        resp = client.post("/agents/deploy", json={"count": 1, "siem_type": "none", "os_type": retired})
        assert resp.status_code == 422, retired


def test_benchmark_refuses_os_without_an_image(client):
    resp = client.post("/benchmarks/start", json={"scenario_id": "linear_scale", "os_type": "debian_10"})
    assert resp.status_code == 422


@pytest.mark.parametrize("operation", ["restart", "freeze", "unfreeze"])
def test_bulk_only_offers_what_it_does(client, operation):
    resp = client.post(f"/agents/bulk/{operation}", json={"container_names": ["x"], "operation": operation})
    assert resp.status_code in (400, 422)


def test_log_upload_ignores_the_old_log_type_field(client, container, attach):
    resp = client.post(f"/agents/{container}/logs/upload", json={
        "content": "hello\n", "destination_path": "/var/log/app.log", "log_type": "auth"})
    assert resp.status_code == 200, resp.text


def test_every_os_type_has_an_image():
    from app.core.os_images import OS_IMAGES
    from app.models import OSType

    assert [o.value for o in OSType] == list(OS_IMAGES)
    assert {i["release"] for i in OS_IMAGES.values()} == {"jammy", "noble", "bookworm"}


def test_profiles_move_off_retired_images(tmp_path):
    import sqlite3

    from app import migrations

    db = tmp_path / "platform.db"
    migrations.migrate(db, make_backup=False)
    migrations.downgrade(db, 9)
    conn = sqlite3.connect(db)
    conn.executemany("INSERT INTO managers (manager_id, name, siem_type, os_type) VALUES (?, ?, 'wazuh', ?)",
                     [(o, o, o) for o in ("ubuntu_20_04", "debian_11", "centos_8", "ubuntu_22_04")])
    conn.commit()
    conn.close()
    migrations.migrate(db, make_backup=False)
    rows = dict(sqlite3.connect(db).execute("SELECT name, os_type FROM managers"))
    assert rows == {"ubuntu_20_04": "ubuntu_24_04", "debian_11": "debian_12", "centos_8": "ubuntu_22_04",
                    "ubuntu_22_04": "ubuntu_22_04"}
