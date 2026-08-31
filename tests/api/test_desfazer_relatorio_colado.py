from datetime import date

import pytest

from desfazer_relatorio_colado import desfazer
from models import Car, GPSReading


def _criar_carro(db, plate='', model='', current_km=0):
    carro = Car(plate=plate, model=model, current_km=current_km)
    db.session.add(carro)
    db.session.commit()
    return carro


def _leitura(db, carro, confirmed_km, reading_date, image_filename):
    leitura = GPSReading(
        car_id=carro.id, image_filename=image_filename, status='confirmed',
        confirmed_km=confirmed_km, reading_date=date.fromisoformat(reading_date),
    )
    db.session.add(leitura)
    db.session.commit()
    return leitura


class TestDesfazer:
    def _preparar_cenario_corrompido(self, db):
        """Simula o estado do banco depois que um relatório colado se
        sobrepôs a leituras que já existiam: tudo deslocado +2245.21."""
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=12567.61)
        baseline = _leitura(db, carro, 12245.21, '2026-08-01', 'relatorio-gps-automatico:baseline')
        semana = _leitura(db, carro, 12567.61, '2026-08-29', 'relatorio-gps-automatico:x')
        colado = _leitura(db, carro, 2245.21, '2026-08-29',
                           'relatorio-gps-manual:FTE-7D54:2026-08-23_a_2026-08-29')
        return carro, baseline, semana, colado

    def test_simulacao_nao_grava_nada(self, app, db):
        carro, baseline, semana, colado = self._preparar_cenario_corrompido(db)

        desfazer('relatorio-gps-manual:FTE-7D54:2026-08-23_a_2026-08-29', aplicar=False)

        db.session.refresh(carro)
        assert carro.current_km == 12567.61
        assert GPSReading.query.filter_by(car_id=carro.id).count() == 3

    def test_apply_reverte_exatamente_o_deslocamento(self, app, db):
        carro, baseline, semana, colado = self._preparar_cenario_corrompido(db)

        desfazer('relatorio-gps-manual:FTE-7D54:2026-08-23_a_2026-08-29', aplicar=True)

        db.session.refresh(carro)
        assert carro.current_km == pytest.approx(10322.40)

        restantes = GPSReading.query.filter_by(car_id=carro.id).order_by(GPSReading.reading_date).all()
        assert len(restantes) == 2
        assert restantes[0].confirmed_km == pytest.approx(10000.0)
        assert restantes[1].confirmed_km == pytest.approx(10322.40)

    def test_tag_inexistente_levanta_erro(self, app, db):
        _criar_carro(db, plate='FTE-7D54', model='Voyage')

        with pytest.raises(ValueError, match='Nenhuma leitura'):
            desfazer('relatorio-gps-manual:FTE-7D54:2026-01-01_a_2026-01-02', aplicar=False)
