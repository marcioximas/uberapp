from datetime import date

from models import Car, MaintenanceItem, MaintenanceLog


def test_create_item_requires_at_least_one_interval(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()

    resp = auth_client.post(
        f"/manutencao/{car.id}/checklist/novo",
        data={"name": "Troca de óleo", "km_interval": "", "date_interval_days": "", "notes": ""},
        follow_redirects=True,
    )
    assert "Informe ao menos um intervalo".encode() in resp.data
    assert MaintenanceItem.query.count() == 0


def test_create_item_success(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()

    auth_client.post(
        f"/manutencao/{car.id}/checklist/novo",
        data={"name": "Troca de óleo", "km_interval": "10000", "date_interval_days": "", "notes": ""},
        follow_redirects=True,
    )
    item = MaintenanceItem.query.filter_by(car_id=car.id).first()
    assert item is not None
    assert item.km_interval == 10000


def test_checklist_shows_overdue_status(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix", current_km=15000)
    db.session.add(car)
    db.session.commit()
    item = MaintenanceItem(car_id=car.id, name="Troca de óleo", km_interval=10000, last_done_km=0)
    db.session.add(item)
    db.session.commit()

    resp = auth_client.get(f"/manutencao/{car.id}/checklist")
    assert resp.status_code == 200
    assert "Atrasado".encode() in resp.data


def test_registrar_servico_updates_last_done(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix", current_km=15000)
    db.session.add(car)
    db.session.commit()
    item = MaintenanceItem(car_id=car.id, name="Troca de óleo", km_interval=10000, last_done_km=0)
    db.session.add(item)
    db.session.commit()

    auth_client.post(
        f"/manutencao/itens/{item.id}/registrar",
        data={"done_date": "2026-08-03", "done_km": "15000", "cost": "250.00", "notes": "Troca preventiva"},
        follow_redirects=True,
    )
    db.session.refresh(item)
    assert item.last_done_km == 15000
    assert item.last_done_date == date(2026, 8, 3)
    assert MaintenanceLog.query.filter_by(maintenance_item_id=item.id).count() == 1


def test_delete_item_without_logs_hard_deletes(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    item = MaintenanceItem(car_id=car.id, name="Troca de óleo", km_interval=10000)
    db.session.add(item)
    db.session.commit()

    auth_client.post(f"/manutencao/itens/{item.id}/excluir", follow_redirects=True)
    assert MaintenanceItem.query.get(item.id) is None


def test_delete_item_with_logs_soft_deactivates(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    item = MaintenanceItem(car_id=car.id, name="Troca de óleo", km_interval=10000)
    db.session.add(item)
    db.session.commit()
    log = MaintenanceLog(maintenance_item_id=item.id, done_date=date(2026, 8, 1), done_km=5000)
    db.session.add(log)
    db.session.commit()

    auth_client.post(f"/manutencao/itens/{item.id}/excluir", follow_redirects=True)
    db.session.refresh(item)
    assert item.active is False
    assert MaintenanceItem.query.get(item.id) is not None


def test_alertas_page_lists_overdue_items(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix", current_km=20000)
    db.session.add(car)
    db.session.commit()
    item = MaintenanceItem(car_id=car.id, name="Troca de óleo", km_interval=10000, last_done_km=0)
    db.session.add(item)
    db.session.commit()

    resp = auth_client.get("/manutencao/alertas")
    assert resp.status_code == 200
    assert b"ABC1D23" in resp.data
    assert "Troca de óleo".encode() in resp.data
