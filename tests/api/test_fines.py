from models import Car, Fine


def _car_com_multa(db, status="confirmed", vencimento=None):
    car = Car(plate="ABC1D23")
    db.session.add(car)
    db.session.commit()
    fine = Fine(
        car_id=car.id, numero_ait="AIT1", status=status,
        extracted_valor=100, extracted_vencimento=vencimento,
    )
    db.session.add(fine)
    db.session.commit()
    return car, fine


def test_alertas_lists_pending_fine(auth_client, db):
    car, fine = _car_com_multa(db, status="pending_review")
    resp = auth_client.get("/multas/")
    assert resp.status_code == 200
    assert fine.numero_ait.encode() in resp.data


def test_alertas_hides_paid_fine(auth_client, db):
    car, fine = _car_com_multa(db, status="paga")
    resp = auth_client.get("/multas/")
    assert fine.numero_ait.encode() not in resp.data


def test_marcar_paga(auth_client, db):
    car, fine = _car_com_multa(db)
    auth_client.post(f"/multas/{fine.id}/pagar", follow_redirects=True)
    db.session.refresh(fine)
    assert fine.status == "paga"
    assert fine.paid_date is not None


def test_marcar_recorrida(auth_client, db):
    car, fine = _car_com_multa(db)
    auth_client.post(f"/multas/{fine.id}/recorrer", data={"notes": "recurso protocolado"}, follow_redirects=True)
    db.session.refresh(fine)
    assert fine.status == "recorrida"
    assert fine.notes == "recurso protocolado"


def test_rejeitar(auth_client, db):
    car, fine = _car_com_multa(db, status="pending_review")
    auth_client.post(f"/multas/{fine.id}/rejeitar", follow_redirects=True)
    db.session.refresh(fine)
    assert fine.status == "rejected"


def test_revisar_confirma_multa(auth_client, db):
    car, fine = _car_com_multa(db, status="pending_review")
    auth_client.post(
        f"/multas/{fine.id}/revisar",
        data={"confirmed_valor": "120.00", "confirmed_vencimento": "", "notes": ""},
        follow_redirects=True,
    )
    db.session.refresh(fine)
    assert fine.status == "confirmed"
    assert float(fine.confirmed_valor) == 120.00


def test_car_form_saves_renavam(auth_client, db):
    auth_client.post(
        "/carros/novo",
        data={"plate": "ABC1D23", "renavam": "12345678901"},
        follow_redirects=True,
    )
    car = Car.query.filter_by(plate="ABC1D23").first()
    assert car is not None
    assert car.renavam == "12345678901"


def test_car_detail_shows_fines(auth_client, db):
    car, fine = _car_com_multa(db, status="pending_review")
    resp = auth_client.get(f"/carros/{car.id}")
    assert resp.status_code == 200
    assert fine.numero_ait.encode() in resp.data


def test_car_list_shows_pending_fine_count(auth_client, db):
    car, fine = _car_com_multa(db, status="pending_review")
    resp = auth_client.get("/carros/")
    assert resp.status_code == 200
    assert b">1<" in resp.data


def test_car_list_hides_count_for_resolved_fine(auth_client, db):
    car, fine = _car_com_multa(db, status="paga")
    resp = auth_client.get("/carros/")
    assert resp.status_code == 200
    assert b">1<" not in resp.data


def test_global_alert_shows_when_fine_pending_review(auth_client, db):
    _car_com_multa(db, status="pending_review")
    resp = auth_client.get("/")
    assert resp.status_code == 200
    assert "multa nova encontrada".encode() in resp.data


def test_global_alert_hidden_when_no_pending_review_fine(auth_client, db):
    _car_com_multa(db, status="confirmed")
    resp = auth_client.get("/")
    assert resp.status_code == 200
    assert "aguardando revisão".encode() not in resp.data
