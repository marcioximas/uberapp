from datetime import date

import backfill_historico_gps as bh
from models import Car, GPSReading


def _criar_carro(db, plate='', model='', current_km=0):
    carro = Car(plate=plate, model=model, current_km=current_km)
    db.session.add(carro)
    db.session.commit()
    return carro


def _leitura(db, car_id, dia, km):
    r = GPSReading(car_id=car_id, image_filename='x', confirmed_km=km,
                    reading_date=dia, status='confirmed')
    db.session.add(r)
    db.session.commit()
    return r


class TestMesesDoAnoAte:
    def test_meses_completos_ate_o_mes_da_data_limite(self):
        meses = bh._meses_do_ano_ate(date(2026, 3, 15))
        assert meses == [
            (2026, 1, date(2026, 1, 1), date(2026, 2, 1)),
            (2026, 2, date(2026, 2, 1), date(2026, 3, 1)),
            (2026, 3, date(2026, 3, 1), date(2026, 3, 15)),  # último mês é parcial
        ]

    def test_data_limite_no_dia_1_de_janeiro_nao_gera_nada(self):
        assert bh._meses_do_ano_ate(date(2026, 1, 1)) == []

    def test_data_limite_no_comeco_de_janeiro_gera_um_mes_parcial(self):
        assert bh._meses_do_ano_ate(date(2026, 1, 5)) == [
            (2026, 1, date(2026, 1, 1), date(2026, 1, 5)),
        ]


class TestProcessar:
    def _html_para(self, placa, apelido, km, inicio, fim):
        return f'''<html><body>Tipo de relatório: Informações gerais (resumo)
        <table><tbody><tr>
          <td>HENRIQUE - {placa} - {apelido}</td>
          <td>{inicio}</td>
          <td>{fim}</td>
          <td>{km} Km</td>
          <td>1h 0min 0s</td>
          <td>23h 0min 0s</td>
          <td>80 KM</td>
        </tr></tbody></table>
        </body></html>'''

    def _mock_relatorio_por_mes(self, monkeypatch, km_por_mes):
        """km_por_mes: dict {'YYYY-MM': km}. Devolve o km do mês de
        datetime_from, ou '0' se não estiver no dict."""
        def fake(session, token, device_id, datetime_from, datetime_to):
            chave = datetime_from[:7]
            km = km_por_mes.get(chave, 0)
            return self._html_para('GHV-7A82', 'GOL', km, '01-01-2026 00:00:00', '01-02-2026 00:00:00')
        monkeypatch.setattr(bh, 'login', lambda session: 'tok123')
        monkeypatch.setattr(bh, 'gerar_relatorio_html', fake)
        monkeypatch.setattr(bh, 'CARROS_MONITORADOS', [{'placa': 'GHV-7A82', 'device_id': 111}])

    def test_simulacao_nao_grava_nada(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol', current_km=150)
        _leitura(db, carro.id, date(2026, 3, 1), 0)  # baseline existente
        self._mock_relatorio_por_mes(monkeypatch, {'2026-01': 100, '2026-02': 50})

        bh.processar(app, aplicar=False)

        db.session.refresh(carro)
        assert carro.current_km == 150
        assert GPSReading.query.filter_by(car_id=carro.id).count() == 1

    def test_apply_cria_leituras_historicas_e_desloca_as_existentes(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol', current_km=150)
        existente = _leitura(db, carro.id, date(2026, 3, 1), 0)  # baseline existente
        self._mock_relatorio_por_mes(monkeypatch, {'2026-01': 100, '2026-02': 50})

        bh.processar(app, aplicar=True)

        historicas = (
            GPSReading.query.filter(GPSReading.car_id == carro.id, GPSReading.id != existente.id)
            .order_by(GPSReading.reading_date)
            .all()
        )
        assert len(historicas) == 2
        assert historicas[0].confirmed_km == 100
        assert historicas[0].reading_date == date(2026, 1, 31)
        assert historicas[1].confirmed_km == 150  # 100 + 50 acumulado
        assert historicas[1].reading_date == date(2026, 2, 28)

        db.session.refresh(existente)
        assert existente.confirmed_km == 150  # 0 (original) + 150 (deslocamento)

        db.session.refresh(carro)
        assert carro.current_km == 300  # 150 (original) + 150 (deslocamento)

    def test_mes_sem_dado_no_rastreador_nao_gera_leitura(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol', current_km=0)
        _leitura(db, carro.id, date(2026, 3, 1), 0)
        self._mock_relatorio_por_mes(monkeypatch, {'2026-01': 0, '2026-02': 40})

        bh.processar(app, aplicar=True)

        historicas = GPSReading.query.filter(
            GPSReading.car_id == carro.id,
            GPSReading.image_filename.like('relatorio-gps-historico:%'),
        ).all()
        assert len(historicas) == 1  # só fevereiro; janeiro não gerou leitura
        assert historicas[0].confirmed_km == 40
        assert GPSReading.query.filter_by(car_id=carro.id).count() == 2  # baseline + fevereiro

    def test_carro_sem_nenhuma_leitura_ainda_nao_quebra(self, app, db, monkeypatch):
        _criar_carro(db, plate='GHV-7A82', model='Gol', current_km=0)
        self._mock_relatorio_por_mes(monkeypatch, {})

        bh.processar(app, aplicar=True)  # não deve levantar exceção

    def test_placa_nao_cadastrada_e_pulada_sem_quebrar(self, app, db, monkeypatch):
        monkeypatch.setattr(bh, 'login', lambda session: 'tok123')
        monkeypatch.setattr(bh, 'gerar_relatorio_html', lambda *a, **k: '<html></html>')
        monkeypatch.setattr(bh, 'CARROS_MONITORADOS', [{'placa': 'ZZZ-0000', 'device_id': 333}])

        bh.processar(app, aplicar=True)  # não deve levantar exceção

        assert GPSReading.query.count() == 0
