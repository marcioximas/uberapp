from datetime import date

from blueprints.dashboard import _km_rodado_por_mes, _grafico_km_svg
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


class TestKmRodadoPorMes:
    def test_soma_deltas_dentro_do_mesmo_mes(self, app, db, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        car = Car(plate="AAA0001", model="Onix")
        db.session.add(car)
        db.session.commit()

        _leitura(db, car.id, date(2026, 8, 1), 100)
        _leitura(db, car.id, date(2026, 8, 15), 350)

        resultado = {d["label"]: d["km"] for d in _km_rodado_por_mes(meses=1)}
        assert resultado["Ago/26"] == 250

    def test_delta_e_atribuido_ao_mes_da_leitura_mais_recente(self, app, db, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        car = Car(plate="AAA0001", model="Onix")
        db.session.add(car)
        db.session.commit()

        _leitura(db, car.id, date(2026, 7, 28), 500)  # início do avanço
        _leitura(db, car.id, date(2026, 8, 3), 900)  # avanço "cai" em agosto

        dados = {d["label"]: d["km"] for d in _km_rodado_por_mes(meses=2)}
        assert dados["Jul/26"] == 0
        assert dados["Ago/26"] == 400

    def test_soma_varios_carros_no_mesmo_mes(self, app, db, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        c1 = Car(plate="AAA0001", model="Onix")
        c2 = Car(plate="BBB0002", model="Gol")
        db.session.add_all([c1, c2])
        db.session.commit()

        _leitura(db, c1.id, date(2026, 8, 1), 0)
        _leitura(db, c1.id, date(2026, 8, 10), 100)
        _leitura(db, c2.id, date(2026, 8, 1), 0)
        _leitura(db, c2.id, date(2026, 8, 10), 60)

        dados = {d["label"]: d["km"] for d in _km_rodado_por_mes(meses=1)}
        assert dados["Ago/26"] == 160

    def test_ignora_leitura_que_regride_o_odometro(self, app, db, monkeypatch):
        # Não deveria acontecer na prática, mas uma leitura ruim não pode
        # gerar "km negativo" no gráfico.
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        car = Car(plate="AAA0001", model="Onix")
        db.session.add(car)
        db.session.commit()

        _leitura(db, car.id, date(2026, 8, 1), 500)
        _leitura(db, car.id, date(2026, 8, 10), 100)  # regressão

        dados = {d["label"]: d["km"] for d in _km_rodado_por_mes(meses=1)}
        assert dados["Ago/26"] == 0

    def test_sem_leituras_retorna_zero_para_todos_os_meses(self, app, db, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        assert all(d["km"] == 0 for d in _km_rodado_por_mes(meses=6))

    def test_retorna_meses_na_ordem_cronologica(self, app, db, monkeypatch):
        monkeypatch.setattr("blueprints.dashboard.date", _FakeDate)
        labels = [d["label"] for d in _km_rodado_por_mes(meses=3)]
        assert labels == ["Jun/26", "Jul/26", "Ago/26"]


class TestGraficoKmSvg:
    def test_barra_sem_km_nao_gera_path(self):
        g = _grafico_km_svg([{"label": "Jan/26", "km": 0}])
        assert g["barras"][0]["path"] is None

    def test_barra_com_km_gera_path_e_altura_proporcional_ao_maximo(self):
        dados = [{"label": "Jan/26", "km": 100}, {"label": "Fev/26", "km": 400}]
        g = _grafico_km_svg(dados)
        barra_menor, barra_maior = g["barras"]
        # a barra do mês com mais km fica mais alta (y menor, mais perto do topo)
        assert barra_maior["y"] < barra_menor["y"]

    def test_ultimo_mes_marcado_para_rotulo_direto(self):
        dados = [{"label": "Jan/26", "km": 10}, {"label": "Fev/26", "km": 20}]
        g = _grafico_km_svg(dados)
        assert g["barras"][0]["eh_ultimo"] is False
        assert g["barras"][1]["eh_ultimo"] is True

    def test_grades_incluem_zero_e_o_topo(self):
        g = _grafico_km_svg([{"label": "Jan/26", "km": 300}])
        valores = [grade["valor"] for grade in g["grades"]]
        assert valores[0] == 0
        assert valores[-1] > 0
