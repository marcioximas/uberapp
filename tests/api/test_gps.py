import io

import pytest
from PIL import Image

from models import Car, GPSReading


def _fake_jpeg_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (50, 50), color=(100, 150, 200)).save(buffer, format="JPEG")
    buffer.seek(0)
    return buffer


@pytest.fixture()
def mock_extrair_dados(monkeypatch):
    def _fake(caminho_imagem):
        return {
            "extracted_km": 15000,
            "extracted_max_speed": 110,
            "extracted_moving_time_minutes": 300,
            "confidence_note": "Confiança: alta.",
            "raw_ai_response": '{"km_rodado": 15000}',
        }

    monkeypatch.setattr("blueprints.gps.extrair_dados", _fake)
    return _fake


def test_upload_gps_creates_pending_review(auth_client, db, mock_extrair_dados):
    car = Car(plate="ABC1D23", model="Onix", current_km=10000)
    db.session.add(car)
    db.session.commit()

    resp = auth_client.post(
        "/manutencao/gps/upload",
        data={"car_id": str(car.id), "image": (_fake_jpeg_bytes(), "print.jpg")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    reading = GPSReading.query.filter_by(car_id=car.id).first()
    assert reading is not None
    assert reading.status == "pending_review"
    assert reading.extracted_km == 15000


def test_confirmar_leitura_atualiza_km_quando_maior(auth_client, db, mock_extrair_dados):
    car = Car(plate="ABC1D23", model="Onix", current_km=10000)
    db.session.add(car)
    db.session.commit()
    reading = GPSReading(car_id=car.id, image_filename="fake.jpg", extracted_km=15000)
    db.session.add(reading)
    db.session.commit()

    auth_client.post(
        f"/manutencao/gps/{reading.id}/revisar",
        data={
            "reading_date": "2026-08-01",
            "confirmed_km": "15000",
            "confirmed_max_speed": "110",
            "confirmed_moving_time_minutes": "300",
        },
        follow_redirects=True,
    )
    db.session.refresh(car)
    db.session.refresh(reading)
    assert car.current_km == 15000
    assert reading.status == "confirmed"


def test_confirmar_leitura_nao_regride_km_quando_menor(auth_client, db, mock_extrair_dados):
    car = Car(plate="ABC1D23", model="Onix", current_km=20000)
    db.session.add(car)
    db.session.commit()
    reading = GPSReading(car_id=car.id, image_filename="fake.jpg", extracted_km=15000)
    db.session.add(reading)
    db.session.commit()

    resp = auth_client.post(
        f"/manutencao/gps/{reading.id}/revisar",
        data={
            "reading_date": "2026-08-01",
            "confirmed_km": "15000",
            "confirmed_max_speed": "110",
            "confirmed_moving_time_minutes": "300",
        },
        follow_redirects=True,
    )
    db.session.refresh(car)
    db.session.refresh(reading)
    assert car.current_km == 20000  # não regrediu
    assert reading.status == "confirmed"
    assert "NÃO foi alterado".encode() in resp.data


def test_rejeitar_leitura(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    reading = GPSReading(car_id=car.id, image_filename="fake.jpg")
    db.session.add(reading)
    db.session.commit()

    auth_client.post(f"/manutencao/gps/{reading.id}/rejeitar", follow_redirects=True)
    db.session.refresh(reading)
    assert reading.status == "rejected"
