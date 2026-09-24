"""
`habeny support-bundle`: diagnostics for support, without secrets.
"""
import json
import tarfile

from app import cli


def test_bundle_has_diagnostics_and_no_secrets(app, tmp_path, capsys, monkeypatch):
    log = tmp_path / "habeny.log"
    log.write_text("line one\nline two\n")
    monkeypatch.setenv("HABENY_LOG_FILE", str(log))
    monkeypatch.setenv("HABENY_SMTP_PASSWORD", "super-secret-smtp-pw")
    assert cli.main(["support-bundle", "--out", str(tmp_path)]) == 0
    path = next(tmp_path.glob("habeny-support-*.tar.gz"))
    assert (path.stat().st_mode & 0o777) == 0o600
    assert "Support bundle:" in capsys.readouterr().out
    with tarfile.open(path) as tar:
        names = {m.name.split("/", 1)[1]: m for m in tar.getmembers()}
        assert set(names) == {"README.txt", "diagnostics.json", "server.log"}
        diag = json.loads(tar.extractfile(names["diagnostics.json"]).read())
        raw = tar.extractfile(names["diagnostics.json"]).read().decode()
        assert tar.extractfile(names["server.log"]).read().decode().endswith("line two\n")
    assert diag["habeny_version"] and diag["database"]["current"] >= 1
    assert diag["license"]["state"] and "server_id" in diag["license"]
    smtp = next(s for s in diag["settings"] if s["name"] == "HABENY_SMTP_PASSWORD")
    assert smtp["value"] == "(set, hidden)" and "super-secret-smtp-pw" not in raw
    assert "secret.key" not in names and "platform.db" not in names


def test_one_failing_check_doesnt_stop_the_bundle(app, tmp_path, monkeypatch):
    from app.services import support
    monkeypatch.setattr(support, "_disk", lambda: 1 / 0)
    diag = support.collect()
    assert "ZeroDivisionError" in diag["disk"]["error"] and diag["database"]
