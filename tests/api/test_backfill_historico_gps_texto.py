from datetime import date, datetime

import pytest

from backfill_historico_gps_texto import aplicar_relatorio
from models import Car, GPSReading


def _criar_carro(db, plate='', model='', current_km=0):
    carro = Car(plate=plate, model=model, current_km=current_km)
    db.session.add(carro)
    db.session.commit()
    return carro


def _leitura(db, carro, confirmed_km, reading_date, image_filename='teste'):
    leitura = GPSReading(
        car_id=carro.id, image_filename=image_filename, status='confirmed',
        confirmed_km=confirmed_km, reading_date=date.fromisoformat(reading_date),
    )
    db.session.add(leitura)
    db.session.commit()
    return leitura


def _dados(placa, inicio, fim, km):
    return {
        'motorista': 'HENRIQUE', 'placa': placa, 'apelido': None,
        'periodo_inicio': datetime.fromisoformat(inicio),
        'periodo_fim': datetime.fromisoformat(fim),
        'km_rodados': km,
    }


class TestAplicarRelatorio:
    def test_aplica_quando_periodo_e_anterior_a_primeira_leitura(self, app, db):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=5000)
        _leitura(db, carro, 5000, '2026-08-01', 'relatorio-gps-automatico:x')

        km = aplicar_relatorio(carro, _dados('FTE-7D54', '2026-01-01T00:00:00',
                                              '2026-07-31T23:59:59', 2245.21))

        assert km == 2245.21
        db.session.refresh(carro)
        assert carro.current_km == 7245.21

    def test_rejeita_periodo_sobreposto_a_leitura_ja_existente(self, app, db):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=5000)
        _leitura(db, carro, 5000, '2026-08-16', 'relatorio-gps-automatico:x')

        with pytest.raises(ValueError, match='se sobrepõe'):
            aplicar_relatorio(carro, _dados('FTE-7D54', '2026-08-23T00:00:00',
                                             '2026-08-29T23:59:59', 2245.21))

        # nada deve ter sido gravado nem alterado
        assert GPSReading.query.filter_by(car_id=carro.id).count() == 1
        db.session.refresh(carro)
        assert carro.current_km == 5000

    def test_rejeita_periodo_que_termina_no_mesmo_dia_da_primeira_leitura(self, app, db):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=5000)
        _leitura(db, carro, 5000, '2026-08-16', 'relatorio-gps-automatico:x')

        with pytest.raises(ValueError, match='se sobrepõe'):
            aplicar_relatorio(carro, _dados('FTE-7D54', '2026-08-01T00:00:00',
                                             '2026-08-16T23:59:59', 100))

    def test_aceita_periodo_que_termina_um_dia_antes_da_primeira_leitura(self, app, db):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=5000)
        _leitura(db, carro, 5000, '2026-08-16', 'relatorio-gps-automatico:x')

        km = aplicar_relatorio(carro, _dados('FTE-7D54', '2026-08-01T00:00:00',
                                              '2026-08-15T23:59:59', 100))

        assert km == 100

    def test_sem_leitura_nenhuma_ainda_aceita_qualquer_periodo(self, app, db):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=0)

        km = aplicar_relatorio(carro, _dados('FTE-7D54', '2026-08-23T00:00:00',
                                              '2026-08-29T23:59:59', 2245.21))

        assert km == 2245.21

    def test_relatorio_ja_aplicado_e_rejeitado(self, app, db):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=0)
        dados = _dados('FTE-7D54', '2026-08-01T00:00:00', '2026-08-15T23:59:59', 100)

        aplicar_relatorio(carro, dados)

        with pytest.raises(ValueError, match='já foi aplicado'):
            aplicar_relatorio(carro, dados)
