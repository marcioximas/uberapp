from datetime import date

from contas_fixas import gerar_ocorrencias
from models import Car, RecurringItem, RecurringOccurrence


def test_gerar_ocorrencias_creates_monthly_rows(db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    item = RecurringItem(
        car_id=car.id,
        name="Prestação financiamento",
        amount=650,
        type="expense",
        frequency="monthly",
        day_of_month=15,
        start_date=date(2026, 6, 15),
    )
    db.session.add(item)
    db.session.commit()

    gerar_ocorrencias(until_date=date(2026, 8, 31))

    ocorrencias = RecurringOccurrence.query.filter_by(recurring_item_id=item.id).order_by(
        RecurringOccurrence.due_date
    ).all()
    assert [o.due_date for o in ocorrencias] == [
        date(2026, 6, 15),
        date(2026, 7, 15),
        date(2026, 8, 15),
    ]
    assert all(o.status == "pending" for o in ocorrencias)
    assert all(o.amount == 650 for o in ocorrencias)


def test_gerar_ocorrencias_is_idempotent(db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    item = RecurringItem(
        car_id=car.id,
        name="Seguro",
        amount=200,
        type="expense",
        frequency="monthly",
        day_of_month=1,
        start_date=date(2026, 7, 1),
    )
    db.session.add(item)
    db.session.commit()

    gerar_ocorrencias(until_date=date(2026, 7, 31))
    gerar_ocorrencias(until_date=date(2026, 7, 31))

    ocorrencias = RecurringOccurrence.query.filter_by(recurring_item_id=item.id).all()
    assert len(ocorrencias) == 1


def test_gerar_ocorrencias_ignores_inactive_items(db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    item = RecurringItem(
        car_id=car.id,
        name="Item desativado",
        amount=100,
        type="expense",
        frequency="monthly",
        day_of_month=1,
        start_date=date(2026, 7, 1),
        active=False,
    )
    db.session.add(item)
    db.session.commit()

    gerar_ocorrencias(until_date=date(2026, 7, 31))

    assert RecurringOccurrence.query.filter_by(recurring_item_id=item.id).count() == 0
