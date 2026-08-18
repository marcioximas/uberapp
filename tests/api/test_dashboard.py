from datetime import date

from blueprints.dashboard import (
    _km_deltas_por_carro_e_mes,
    _km_por_carro_no_mes,
    _meses_disponiveis,
    _grafico_km_svg,
)
from models import Car, GPSReading


class _FakeDate(date):
    @classmethod
    def today(cls):
        return date(2026, 8, 17)


def _leitura(db, car_id, dia, km):
    r = GPSReading(car_id=car_id, image_filename="x", confirmed_km=km,
                    reading_date=dia, status="confirmed")
    db.session.add(r)
    db.session.commit()
    return r


class TestKmDeltasPorCarroEMes:
    def test_soma_deltas_dentro_do_mesmo_mes(self, app, db):
        car = Car(plate="AAA0001", model="Onix")
        db.session.add(car)
        db.session.commit()

        _leitura(db, car.id, date(2026, 8, 1), 100)
        _leitura(db, car.id, date(2026, 8, 15), 350)

        deltas = _km_deltas_por_carro_e_mes()
        assert deltas[(car.id, 2026, 8)] == 250

    def test_delta_e_atribuido_ao_mes_da_leitura_mais_recente(self, app, db):
        car = Car(plate="AAA0001", model="Onix")
        db.session.add(car)
        db.session.commit()

        _leitura(db, car.id, date(2026, 7, 28), 500)  # início do avanço
        _leitura(db, car.id, date(2026, 8, 3), 900)  # avanço "cai" em agosto

        deltas = _km_deltas_por_carro_e_mes()
        assert (car.id, 2026, 7) not in deltas
        assert deltas[(car.id, 2026, 8)] == 400

    def test_nao_mistura_carros_diferentes(self, app, db):
        c1 = Car(plate="AAA0001", model="Onix")
        c2 = Car(plate="BBB0002", model="Gol")
        db.session.add_all([c1, c2])
        db.session.commit()

        _leitura(db, c1.id, date(2026, 8, 1), 0)
        _leitura(db, c1.id, date(2026, 8, 10), 100)
        _leitura(db, c2.id, date(2026, 8, 1), 0)
        _leitura(db, c2.id, date(2026, 8, 10), 60)

        deltas = _km_deltas_por_carro_e_mes()
        assert deltas[(c1.id, 2026, 8)] == 100
        assert deltas[(c2.id, 2026, 8)] == 60

    def test_ignora_leitura_que_regride_o_odometro(self, app, db):
        # Não deveria acontecer na prática, mas uma leitura ruim não pode
        # gerar "km negativo" no gráfico.
        car = Car(plate="AAA0001", model="Onix")
        db.session.add(car)
        db.session.commit()

        _leitura(db, car.id, date(2026, 8, 1), 500)
        _leitura(db, car.id, date(2026, 8, 10), 100)  # regressão

        deltas = _km_deltas_por_carro_e_mes()
        assert (car.id, 2026, 8) not in deltas


class TestKmPorCarroNoMes:
    def test_retorna_um_item_por_carro_na_ordem_recebida(self, app, db):
        c1 = Car(plate="AAA0001", model="Onix")
        c2 = Car(plate="BBB0002", model="Gol")
        db.session.add_all([c1, c2])
        db.session.commit()

        _leitura(db, c1.id, date(2026, 8, 1), 500)
        _leitura(db, c1.id, date(2026, 8, 10), 900)
        _leitura(db, c2.id, date(2026, 8, 1), 100)
        _leitura(db, c2.id, date(2026, 8, 10), 250)

        dados = _km_por_carro_no_mes(2026, 8, [c1, c2])
        assert dados == [
            {"label": "Onix", "km": 400},
            {"label": "Gol", "km": 150},
        ]

    def test_carro_sem_leitura_no_mes_aparece_com_zero(self, app, db):
        car = Car(plate="AAA0001", model="Onix")
        db.session.add(car)
        db.session.commit()

        dados = _km_por_carro_no_mes(2026, 8, [car])
        assert dados == [{"label": "Onix", "km": 0}]

    def test_carro_sem_modelo_cai_pra_placa(self, app, db):
        car = Car(plate="AAA0001", model=None)
        db.session.add(car)
        db.session.commit()

        dados = _km_por_carro_no_mes(2026, 8, [car])
        assert dados == [{"label": "AAA0001", "km": 0}]


class TestMesesDisponiveis:
    def test_retorna_do_mes_atual_pro_mais_antigo(self, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        meses = _meses_disponiveis(quantidade=3)
        assert [m["value"] for m in meses] == ["2026-08", "2026-07", "2026-06"]
        assert [m["label"] for m in meses] == ["Ago/26", "Jul/26", "Jun/26"]

    def test_atravessa_virada_de_ano(self, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        meses = _meses_disponiveis(quantidade=10)
        ultimo = meses[-1]
        assert ultimo["value"] == "2025-11"
        assert ultimo["label"] == "Nov/25"


class TestGraficoKmSvg:
    def test_barra_sem_km_nao_gera_path(self):
        g = _grafico_km_svg([{"label": "AAA0001", "km": 0}])
        assert g["barras"][0]["path"] is None

    def test_barra_com_km_gera_path_e_altura_proporcional_ao_maximo(self):
        dados = [{"label": "AAA0001", "km": 100}, {"label": "BBB0002", "km": 400}]
        g = _grafico_km_svg(dados)
        barra_menor, barra_maior = g["barras"]
        # a barra do carro com mais km fica mais alta (y menor, mais perto do topo)
        assert barra_maior["y"] < barra_menor["y"]

    def test_grades_incluem_zero_e_o_topo(self):
        g = _grafico_km_svg([{"label": "AAA0001", "km": 300}])
        valores = [grade["valor"] for grade in g["grades"]]
        assert valores[0] == 0
        assert valores[-1] > 0


class TestFiltroNaRota:
    def test_km_mes_invalido_cai_pro_mes_atual(self, auth_client, db, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        resp = auth_client.get("/?km_mes=lixo")
        assert resp.status_code == 200
        assert b'value="2026-08" selected' in resp.data

    def test_filtro_por_mes_troca_titulo_do_grafico(self, auth_client, db, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        resp = auth_client.get("/?km_mes=2026-06")
        assert resp.status_code == 200
        assert "KM rodado por carro (Jun/26)".encode() in resp.data
