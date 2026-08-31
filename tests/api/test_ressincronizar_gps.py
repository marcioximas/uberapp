from datetime import date

import ressincronizar_gps as rs
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


class TestProcessar:
    def _preparar(self, monkeypatch, km_por_dia):
        monkeypatch.setattr(rs, 'CARROS_MONITORADOS', [{'placa': 'FTE-7D54', 'device_id': 222}])
        monkeypatch.setattr(rs, 'login', lambda session: 'tok123')

        def gerar_relatorio_html_fake(session, token, device_id, dfrom, dto):
            return dfrom  # devolve o datetime_from pra decidir o km no parsear fake

        monkeypatch.setattr(rs, 'gerar_relatorio_html', gerar_relatorio_html_fake)
        monkeypatch.setattr(
            rs, 'parsear_relatorio_html',
            lambda html: {'km_rodados': km_por_dia.get(html[:10], 0)},
        )

    def test_simulacao_nao_altera_banco(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=1500)
        _leitura(db, carro, 1000, '2026-08-20', 'relatorio-gps-automatico:a')
        _leitura(db, carro, 1200, '2026-08-21', 'relatorio-gps-automatico:b')  # duplicado/corrompido
        _leitura(db, carro, 1500, '2026-08-22', 'relatorio-gps-automatico:c')  # duplicado/corrompido
        self._preparar(monkeypatch, {'2026-08-21': 80, '2026-08-22': 90})

        rs.processar(app, 'FTE-7D54', date(2026, 8, 21), date(2026, 8, 22), aplicar=False)

        db.session.refresh(carro)
        assert carro.current_km == 1500
        assert GPSReading.query.filter_by(car_id=carro.id).count() == 3

    def test_apply_substitui_leituras_do_periodo_pelas_corretas(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=1500)
        _leitura(db, carro, 1000, '2026-08-20', 'relatorio-gps-automatico:a')
        _leitura(db, carro, 1200, '2026-08-21', 'relatorio-gps-automatico:b')  # errado (deveria ser 1080)
        _leitura(db, carro, 1500, '2026-08-22', 'relatorio-gps-automatico:c')  # errado (deveria ser 1170)
        self._preparar(monkeypatch, {'2026-08-21': 80, '2026-08-22': 90})

        rs.processar(app, 'FTE-7D54', date(2026, 8, 21), date(2026, 8, 22), aplicar=True)

        db.session.refresh(carro)
        assert carro.current_km == 1170  # 1000 + 80 + 90

        leituras = GPSReading.query.filter_by(car_id=carro.id).order_by(GPSReading.reading_date).all()
        assert len(leituras) == 3
        assert leituras[0].confirmed_km == 1000  # fora do período, intocada
        assert leituras[1].reading_date.isoformat() == '2026-08-21'
        assert leituras[1].confirmed_km == 1080
        assert leituras[2].reading_date.isoformat() == '2026-08-22'
        assert leituras[2].confirmed_km == 1170

    def test_nao_mexe_se_houver_leitura_depois_do_fim_pedido(self, app, db, monkeypatch):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=1500)
        _leitura(db, carro, 1000, '2026-08-20', 'relatorio-gps-automatico:a')
        _leitura(db, carro, 1500, '2026-08-25', 'relatorio-gps-automatico:b')  # depois do fim pedido
        self._preparar(monkeypatch, {'2026-08-21': 80})

        rs.processar(app, 'FTE-7D54', date(2026, 8, 21), date(2026, 8, 21), aplicar=True)

        db.session.refresh(carro)
        assert carro.current_km == 1500  # nada mudou
        assert GPSReading.query.filter_by(car_id=carro.id).count() == 2
