from datetime import date

from models import Car, Fine
from fines import upsert_fine


def test_upsert_fine_creates_new(db):
    car = Car(plate="ABC1D23")
    db.session.add(car)
    db.session.commit()

    fine, is_new = upsert_fine(car, {"numero_ait": "AIT1", "valor": 100, "vencimento": date(2026, 1, 1)})
    db.session.commit()

    assert is_new
    assert Fine.query.filter_by(numero_ait="AIT1").count() == 1
    assert fine.extracted_valor == 100


def test_upsert_fine_updates_extracted_without_touching_confirmed(db):
    car = Car(plate="ABC1D23")
    db.session.add(car)
    db.session.commit()

    fine, _ = upsert_fine(car, {"numero_ait": "AIT1", "valor": 100})
    fine.status = "confirmed"
    fine.confirmed_valor = 90
    db.session.commit()

    fine2, is_new = upsert_fine(car, {"numero_ait": "AIT1", "valor": 150})
    db.session.commit()

    assert not is_new
    assert fine2.id == fine.id
    assert fine2.extracted_valor == 150
    assert fine2.confirmed_valor == 90  # correção humana não é sobrescrita
    assert fine2.status == "confirmed"  # status não é sobrescrito


def test_upsert_fine_different_ait_creates_separate_record(db):
    car = Car(plate="ABC1D23")
    db.session.add(car)
    db.session.commit()

    upsert_fine(car, {"numero_ait": "AIT1", "valor": 100})
    upsert_fine(car, {"numero_ait": "AIT2", "valor": 200})
    db.session.commit()

    assert Fine.query.filter_by(car_id=car.id).count() == 2
