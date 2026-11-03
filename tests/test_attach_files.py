"""Attaching a catalog copies it in under the database name.

Attaching the same upload twice under two names used to give both databases the
same physical mdf, because the file was copied in under its uploaded name. SQL
Server can only give one database a pair of files, so the second one ended up in
RECOVERY_PENDING ("Access is denied" on the mdf). No SQL Server here: the copy
and attach calls are stubbed.
"""


def _client_with_csrf():
    from app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_csrf"] = "tok"
    return client


def _stub(monkeypatch, attached_names):
    import app as app_module

    copies = []

    monkeypatch.setattr(app_module.docker_ops, "copy_into_container",
                        lambda src, name: copies.append((src, name)))
    monkeypatch.setattr(app_module.db, "attach_database",
                        lambda name, mdf, ldf: attached_names.append((name, mdf, ldf)))
    monkeypatch.setattr(app_module.db, "guess_catalog_type", lambda name: "drawing style")
    monkeypatch.setattr(app_module.metadata, "library_kind", lambda name: "")
    monkeypatch.setattr(app_module.metadata, "set_meta", lambda *a, **k: None)
    return copies


def test_attach_uses_the_database_name_for_the_container_files(monkeypatch):
    attached = []
    copies = _stub(monkeypatch, attached)
    client = _client_with_csrf()

    resp = client.post("/attach", data={
        "csrf_token": "tok",
        "base": "Marks_6_-_Railing_Mp_is_Handrail",
        "mdf": "Marks_6_-_Railing_Mp_is_Handrail.mdf",
        "ldf": "Marks_6_-_Railing_Mp_is_Handrail_log.ldf",
        "db_name": "marks_rail",
    })

    assert resp.status_code == 302
    assert attached == [("marks_rail", "marks_rail.mdf", "marks_rail_log.ldf")]
    assert [name for _src, name in copies] == ["marks_rail.mdf", "marks_rail_log.ldf"]


def test_attaching_the_same_file_under_two_names_keeps_files_apart(monkeypatch):
    attached = []
    _stub(monkeypatch, attached)
    client = _client_with_csrf()
    form = {
        "csrf_token": "tok",
        "base": "Marks_6_-_Railing_Mp_is_Handrail",
        "mdf": "Marks_6_-_Railing_Mp_is_Handrail.mdf",
        "ldf": "Marks_6_-_Railing_Mp_is_Handrail_log.ldf",
    }

    client.post("/attach", data={**form, "db_name": "first_copy"})
    client.post("/attach", data={**form, "db_name": "second_copy"})

    mdf_names = [mdf for _name, mdf, _ldf in attached]
    assert mdf_names == ["first_copy.mdf", "second_copy.mdf"]
    assert len(set(mdf_names)) == 2


def test_attach_refuses_an_unsafe_database_name(monkeypatch):
    attached = []
    _stub(monkeypatch, attached)
    client = _client_with_csrf()

    resp = client.post("/attach", data={
        "csrf_token": "tok",
        "base": "SomeFile",
        "mdf": "SomeFile.mdf",
        "ldf": "SomeFile_log.ldf",
        "db_name": "bad name",
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b"Attach failed" in resp.data
    assert attached == []
