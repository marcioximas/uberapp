from datetime import date

from models import Car, Driver, RentalAgreement, ExpectedCharge


def test_create_car(auth_client, db):
    resp = auth_client.post(
        "/carros/novo",
        data={"plate": "abc1d23", "model": "Onix", "year": "2022"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    car = Car.query.filter_by(plate="ABC1D23").first()
    assert car is not None
    assert car.model == "Onix"


def test_create_car_rejects_duplicate_plate(auth_client, db):
    db.session.add(Car(plate="ABC1D23", model="Onix"))
    db.session.commit()

    resp = auth_client.post(
        "/carros/novo",
        data={"plate": "ABC1D23", "model": "Outro", "year": "2020"},
        follow_redirects=True,
    )
    assert "Já existe um carro com essa placa".encode() in resp.data
    assert Car.query.filter_by(plate="ABC1D23").count() == 1


def test_edit_car(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()

    auth_client.post(
        f"/carros/{car.id}/editar",
        data={"plate": "ABC1D23", "model": "Onix Turbo", "year": "2023"},
        follow_redirects=True,
    )
    db.session.refresh(car)
    assert car.model == "Onix Turbo"
    assert car.year == 2023


def test_deactivate_car(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()

    auth_client.post(f"/carros/{car.id}/desativar", follow_redirects=True)
    db.session.refresh(car)
    assert car.active is False


def test_car_detail_renders(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()

    resp = auth_client.get(f"/carros/{car.id}")
    assert resp.status_code == 200
    assert b"ABC1D23" in resp.data


def test_create_driver(auth_client, db):
    auth_client.post(
        "/motoristas/novo",
        data={"name": "João Motorista", "phone": "5511999998888", "document": "12345678900"},
        follow_redirects=True,
    )
    driver = Driver.query.filter_by(name="João Motorista").first()
    assert driver is not None
    assert driver.phone == "5511999998888"


def test_deactivate_driver(auth_client, db):
    driver = Driver(name="João")
    db.session.add(driver)
    db.session.commit()

    auth_client.post(f"/motoristas/{driver.id}/desativar", follow_redirects=True)
    db.session.refresh(driver)
    assert driver.active is False


def test_create_agreement_generates_expected_charges(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    driver = Driver(name="João")
    db.session.add_all([car, driver])
    db.session.commit()

    auth_client.post(
        f"/carros/{car.id}/contrato/novo",
        data={
            "driver_id": str(driver.id),
            "amount": "400.00",
            "frequency": "weekly",
            "weekday": "0",
            "start_date": "2026-07-01",
            "reliability_pct": "100",
        },
        follow_redirects=True,
    )
    agreement = RentalAgreement.query.filter_by(car_id=car.id).first()
    assert agreement is not None
    assert agreement.driver_id == driver.id
    assert agreement.active is True

    # a tela de conciliação gera as cobranças esperadas sob demanda
    auth_client.get("/financeiro/conciliacao")
    assert ExpectedCharge.query.filter_by(rental_agreement_id=agreement.id).count() > 0


def test_new_agreement_closes_previous_one_for_same_car(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    driver1 = Driver(name="Motorista 1")
    driver2 = Driver(name="Motorista 2")
    db.session.add_all([car, driver1, driver2])
    db.session.commit()

    agreement1 = RentalAgreement(
        car_id=car.id, driver_id=driver1.id, amount=400, frequency="weekly",
        weekday=0, start_date=date(2026, 1, 1),
    )
    db.session.add(agreement1)
    db.session.commit()

    auth_client.post(
        f"/carros/{car.id}/contrato/novo",
        data={
            "driver_id": str(driver2.id),
            "amount": "450.00",
            "frequency": "weekly",
            "weekday": "0",
            "start_date": "2026-08-01",
            "reliability_pct": "100",
        },
        follow_redirects=True,
    )

    db.session.refresh(agreement1)
    assert agreement1.active is False
    assert agreement1.end_date is not None

    current = car.current_agreement
    assert current.driver_id == driver2.id


def test_end_agreement(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    driver = Driver(name="João")
    db.session.add_all([car, driver])
    db.session.commit()
    agreement = RentalAgreement(
        car_id=car.id, driver_id=driver.id, amount=400, frequency="weekly",
        weekday=0, start_date=date(2026, 1, 1),
    )
    db.session.add(agreement)
    db.session.commit()

    auth_client.post(f"/contratos/{agreement.id}/encerrar", follow_redirects=True)
    db.session.refresh(agreement)
    assert agreement.active is False
    assert agreement.end_date == date.today()
