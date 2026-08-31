from datetime import date

import pytest

import conferencia_semanal_gps as cs
from models import Car, GPSReading


def _criar_carro(db, plate='', model='', current_km=0):
    carro = Car(plate=plate, model=model, current_km=current_km)
    db.session.add(carro)
    db.session.commit()
    return carro


def _leitura(db, carro, confirmed_km, reading_date):
    leitura = GPSReading(
        car_id=carro.id, image_filename='teste', status='confirmed',
        confirmed_km=confirmed_km, reading_date=date.fromisoformat(reading_date),
    )
    db.session.add(leitura)
    db.session.commit()
    return leitura


class TestKmRegistradoPeriodo:
    def test_soma_avanco_dentro_do_periodo(self, app, db):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol')
        _leitura(db, carro, 1000, '2026-08-16')  # antes do período
        _leitura(db, carro, 1300, '2026-08-23')  # dentro do período

        km = cs.km_registrado_periodo(carro, date(2026, 8, 17), date(2026, 8, 23))

        assert km == 300

    def test_sem_leitura_anterior_usa_zero_como_base(self, app, db):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol')
        _leitura(db, carro, 300, '2026-08-20')

        km = cs.km_registrado_periodo(carro, date(2026, 8, 17), date(2026, 8, 23))

        assert km == 300

    def test_retorna_none_sem_leitura_no_periodo(self, app, db):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol')
        _leitura(db, carro, 1000, '2026-08-10')  # só antes do período

        km = cs.km_registrado_periodo(carro, date(2026, 8, 17), date(2026, 8, 23))

        assert km is None


class TestProcessar:
    def _html_para(self, placa, apelido, km):
        return f'''<html><body>Tipo de relatório: Informações gerais (resumo)
        <table><tbody><tr>
          <td>HENRIQUE - {placa} - {apelido}</td>
          <td>16-08-2026 08:00:00</td>
          <td>23-08-2026 08:00:00</td>
          <td>{km} Km</td>
          <td>1h 0min 0s</td>
          <td>23h 0min 0s</td>
          <td>80 KM</td>
        </tr></tbody></table>
        </body></html>'''

    def _preparar(self, monkeypatch, device_id=222, km_rastreador='300'):
        monkeypatch.setattr(cs, 'CARROS_MONITORADOS', [
            {'placa': 'FTE-7D54', 'device_id': device_id},
        ])
        monkeypatch.setattr(cs, 'login', lambda session: 'tok123')
        monkeypatch.setattr(
            cs, 'gerar_relatorio_html',
            lambda session, token, dev_id, dfrom, dto: self._html_para(
                'FTE-7D54', 'VOYAGE', km_rastreador),
        )
        monkeypatch.setattr(
            cs, 'periodo_ultima_semana',
            lambda: ('2026-08-16 08:00', '2026-08-23 08:00'),
        )

    def test_nao_grava_nada_no_banco(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage')
        _leitura(db, carro, 300, '2026-08-20')
        self._preparar(monkeypatch, km_rastreador='300')

        cs.processar(app)

        assert GPSReading.query.filter_by(car_id=carro.id).count() == 1

    def test_sem_divergencia_nao_levanta_erro(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage')
        _leitura(db, carro, 300, '2026-08-20')
        self._preparar(monkeypatch, km_rastreador='300')

        cs.processar(app)  # não deve levantar SystemExit

    def test_divergencia_acima_da_tolerancia_levanta_erro(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage')
        _leitura(db, carro, 400, '2026-08-20')  # nosso: 400, rastreador: 300
        self._preparar(monkeypatch, km_rastreador='300')

        with pytest.raises(SystemExit):
            cs.processar(app)

    def test_placa_sem_leitura_no_periodo_nao_levanta_erro(self, app, db, monkeypatch):
        _criar_carro(db, plate='FTE-7D54', model='Voyage')
        self._preparar(monkeypatch, km_rastreador='300')

        cs.processar(app)  # sem leitura pra comparar, só avisa e segue
