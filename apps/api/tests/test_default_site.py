import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.modules.locations.models import SiteRow


def test_hall_without_site_lands_in_default(client):
    hall = client.post("/halls", json={"name": "H1"}).json()
    site = client.get(f"/sites/{hall['site_id']}").json()
    assert site["name"] == "Default" and site["is_default"] is True
    hall2 = client.post("/halls", json={"name": "H2"}).json()
    assert hall2["site_id"] == site["id"]  # reused, not a second default


def test_building_room_aliases_match_canonical(client):
    site = client.post("/sites", json={"name": "B1"}).json()
    a = client.post("/halls", json={"name": "A", "building_id": site["id"]})
    b = client.post("/halls", json={"name": "B", "site_id": site["id"]})
    assert a.status_code == b.status_code == 201
    assert a.json()["site_id"] == b.json()["site_id"] == site["id"]
    assert "building_id" not in a.json()  # responses are canonical
    row = client.post("/rows", json={"name": "R", "room_id": a.json()["id"]})
    assert row.status_code == 201 and row.json()["hall_id"] == a.json()["id"]
    assert client.get(f"/halls?building_id={site['id']}").json() == client.get(f"/halls?site_id={site['id']}").json()
    assert len(client.get(f"/rows?room_id={a.json()['id']}").json()) == 1


def test_conflicting_alias_and_canonical_422(client):
    s1 = client.post("/sites", json={"name": "S1"}).json()
    s2 = client.post("/sites", json={"name": "S2"}).json()
    r = client.post("/halls", json={"name": "X", "site_id": s1["id"], "building_id": s2["id"]})
    assert r.status_code == 422
    assert client.post("/halls", json={"name": "Y", "site_id": s1["id"], "building_id": s1["id"]}).status_code == 201
    assert client.get(f"/halls?site_id={s1['id']}&building_id={s2['id']}").status_code == 422


def test_default_site_protected_and_movable(client):
    default_id = client.post("/halls", json={"name": "H"}).json()["site_id"]
    assert client.delete(f"/sites/{default_id}").status_code == 409
    assert client.patch(f"/sites/{default_id}", json={"is_default": False}).status_code == 409
    other = client.post("/sites", json={"name": "Main"}).json()
    assert client.patch(f"/sites/{other['id']}", json={"is_default": True}).json()["is_default"] is True
    assert client.get(f"/sites/{default_id}").json()["is_default"] is False
    new = client.post("/sites", json={"name": "Newer", "is_default": True}).json()
    assert new["is_default"] and not client.get(f"/sites/{other['id']}").json()["is_default"]


def test_second_default_rejected_by_db(engine):
    with Session(engine) as s:
        s.add(SiteRow(name="A", is_default=True))
        s.add(SiteRow(name="B", is_default=True))
        with pytest.raises(IntegrityError):
            s.commit()
