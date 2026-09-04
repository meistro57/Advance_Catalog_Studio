"""Tests for the staging cleanup utility and routes (issue #3).

Covers containment/path-validation, per-pair and orphan removal into the
staging trash, flush, purge, missing-file tolerance, and the regression that
clearing staged files never touches files outside UPLOAD_DIR (exports, sample
data, or an "attached database" sentinel standing in for the SQL Server
container). No real database required.
"""

import os

import pytest

from utils import staging_cleanup as sc


# --- fixtures ---------------------------------------------------------------

@pytest.fixture()
def staging(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    return tmp_path, uploads


def make_pair(uploads, base, mdf_bytes=3000, ldf_bytes=2000):
    mdf = uploads / f"{base}.mdf"
    ldf = uploads / f"{base}_log.ldf"
    mdf.write_bytes(b"x" * mdf_bytes)
    ldf.write_bytes(b"y" * ldf_bytes)
    return base, mdf, ldf


def names_of(uploads):
    return set(sc.list_catalog_files(str(uploads)))


# --- scan / classification --------------------------------------------------

def test_scan_counts_pairs_orphans_and_totals(staging):
    _tmp, uploads = staging
    make_pair(uploads, "Alpha")
    (uploads / "Lone.mdf").write_bytes(b"m")
    (uploads / "Odd_log.ldf").write_bytes(b"l")
    (uploads / "notes.txt").write_text("ignored")
    status = sc.scan_upload_dir(str(uploads))
    assert status["pair_count"] == 1
    assert status["mdf_count"] == 2
    assert status["ldf_count"] == 2
    assert status["orphan_count"] == 2
    assert set(status["orphans"]) == {"Lone.mdf", "Odd_log.ldf"}
    assert status["pairs"][0]["mdf"] == "Alpha.mdf"
    assert status["total_bytes"] == 3000 + 2000 + 1 + 1
    assert status["trash"] == {"count": 0, "bytes": 0}


def test_scan_supports_non_log_ldf_pair(staging):
    _tmp, uploads = staging
    (uploads / "Beta.mdf").write_bytes(b"a")
    (uploads / "Beta.ldf").write_bytes(b"b")
    status = sc.scan_upload_dir(str(uploads))
    assert status["pair_count"] == 1
    assert status["orphans"] == []
    assert status["pairs"][0]["ldf"] == "Beta.ldf"


# --- validation -------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "../evil.mdf", "/etc/passwd.mdf", "a\\b.mdf", "..%2fevil.mdf",
    "notes.txt", ".hidden.mdf", "evil.mdf.exe", "",
])
def test_validate_rejects_unsafe_names(name):
    assert sc.validate_name(name) is False


def test_safe_path_rejects_directory_target(staging):
    _tmp, uploads = staging
    (uploads / "folder.mdf").mkdir()
    with pytest.raises(sc.StagingCleanupError):
        sc.safe_file_path(str(uploads), "folder.mdf")


def test_safe_path_rejects_symlink_escape(staging):
    _tmp, uploads = staging
    outside = _tmp / "outside.mdf"
    outside.write_bytes(b"secret")
    os.symlink(outside, uploads / "link.mdf")
    with pytest.raises(sc.StagingCleanupError):
        sc.safe_file_path(str(uploads), "link.mdf")


# --- move to trash ----------------------------------------------------------

def test_remove_pair_to_trash_tolerates_missing(staging):
    _tmp, uploads = staging
    base, _m, _l = make_pair(uploads, "Alpha")
    result = sc.move_to_trash(str(uploads), ["Alpha.mdf", "Alpha_log.ldf", "Ghost.mdf"])
    assert sorted(result["moved"]) == ["Alpha.mdf", "Alpha_log.ldf"]
    assert result["missing"] == ["Ghost.mdf"]
    assert result["rejected"] == []
    assert names_of(uploads) == set()
    trash = sc.scan_upload_dir(str(uploads))["trash"]
    assert trash["count"] == 2 and trash["bytes"] == 5000


def test_move_to_trash_rejects_unsafe_name(staging):
    _tmp, uploads = staging
    make_pair(uploads, "Alpha")
    result = sc.move_to_trash(str(uploads), ["../evil.mdf"])
    assert result["rejected"] and result["moved"] == []
    # originals untouched
    assert "Alpha.mdf" in names_of(uploads)


def test_flush_only_touches_staged_files(staging):
    _tmp, uploads = staging
    make_pair(uploads, "Alpha")
    exports = _tmp / "exports"
    exports.mkdir()
    (exports / "Completed.mdf").write_bytes(b"export")
    sample = _tmp / "samples"
    sample.mkdir()
    (sample / "Sample.mdf").write_bytes(b"sample")
    attached_sentinel = _tmp / "attached.db"
    attached_sentinel.write_bytes(b"sql")

    files = sc.list_catalog_files(str(uploads))
    result = sc.move_to_trash(str(uploads), files)
    assert len(result["moved"]) == 2
    assert (exports / "Completed.mdf").exists()
    assert (sample / "Sample.mdf").exists()
    assert attached_sentinel.exists()
    assert names_of(uploads) == set()


def test_purge_removes_only_trash_contents(staging):
    _tmp, uploads = staging
    make_pair(uploads, "Alpha")
    files = sc.list_catalog_files(str(uploads))
    sc.move_to_trash(str(uploads), files)
    (uploads / "Keep.mdf").write_bytes(b"k")  # staged after the flush

    result = sc.purge_trash(str(uploads))
    assert result["purged"] >= 1
    assert sc.scan_upload_dir(str(uploads))["trash"]["count"] == 0
    assert names_of(uploads) == {"Keep.mdf"}


def test_purge_missing_trash_is_noop(staging):
    _tmp, uploads = staging
    assert sc.purge_trash(str(uploads)) == {"purged": 0, "bytes": 0}


# --- routes ----------------------------------------------------------------

def _csrf(client):
    with client.session_transaction() as sess:
        return sess["_csrf"]


def _seed(uploads):
    make_pair(uploads, "Alpha")
    (uploads / "Odd.ldf").write_bytes(b"o")


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    import config
    from app import app
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(config, "UPLOAD_DIR", str(uploads))
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.get("/")  # establishes the session + CSRF token
        yield client, uploads, tmp_path


def test_index_shows_staged_and_cleanup_controls(app_client):
    client, uploads, _tmp = app_client
    _seed(uploads)
    html = client.get("/").get_data(as_text=True)
    assert "Staged files (uploads/)" in html
    assert "Alpha.mdf" in html and "Alpha_log.ldf" in html
    assert "Odd.ldf" in html and "orphaned file" in html
    for token in ("Clear staged uploads", "flushModal", "purgeModal",
                  'action="/uploads/remove"', "csrf_token"):
        assert token in html, token


def test_status_endpoint_reports_counts(app_client):
    client, uploads, _tmp = app_client
    _seed(uploads)
    data = client.get("/uploads/status").get_json()
    assert data["pair_count"] == 1
    assert data["orphan_count"] == 1
    assert data["total_bytes"] > 0


def test_remove_requires_csrf(app_client):
    client, uploads, _tmp = app_client
    _seed(uploads)
    assert client.post("/uploads/remove", data={"names": "Alpha.mdf"}).status_code == 400


def test_remove_pair_flow(app_client):
    client, uploads, _tmp = app_client
    _seed(uploads)
    resp = client.post("/uploads/remove", data={
        "csrf_token": _csrf(client),
        "names": ["Alpha.mdf", "Alpha_log.ldf"],
    })
    assert resp.status_code == 302
    assert names_of(uploads) == {"Odd.ldf"}
    html = client.get("/").get_data(as_text=True)
    assert "Alpha.mdf" not in html and "Odd.ldf" in html


def test_flush_flow_keeps_outside_files(app_client):
    client, uploads, tmp_path = app_client
    _seed(uploads)
    sentinel = tmp_path / "attached.db"
    sentinel.write_bytes(b"still attached")
    resp = client.post("/uploads/flush", data={"csrf_token": _csrf(client)})
    assert resp.status_code == 302
    assert names_of(uploads) == set()
    assert sentinel.exists()
    status = client.get("/uploads/status").get_json()
    assert status["trash"]["count"] == 3


def test_purge_flow(app_client):
    client, uploads, _tmp = app_client
    _seed(uploads)
    client.post("/uploads/flush", data={"csrf_token": _csrf(client)})
    assert client.post("/uploads/purge", data={"csrf_token": _csrf(client)}).status_code == 302
    assert client.get("/uploads/status").get_json()["trash"]["count"] == 0
