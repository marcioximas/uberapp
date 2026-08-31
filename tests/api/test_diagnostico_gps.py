from datetime import date

import diagnostico_gps as dg
from models import Car, GPSReading


def _criar_carro(db, plate='', model='', current_km=0, active=True):
    carro = Car(plate=plate, model=model, current_km=current_km, active=active)
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


class TestSelecionarCarros:
    def test_placa_vazia_retorna_todos_ativos(self, app, db):
        ativo = _criar_carro(db, plate='FTE-7D54', model='Voyage')
        _criar_carro(db, plate='XXX-0000', model='Inativo', active=False)

        carros = dg.selecionar_carros(None)

        assert [c.id for c in carros] == [ativo.id]

    def test_todos_e_tratado_igual_a_vazio(self, app, db):
        ativo = _criar_carro(db, plate='FTE-7D54', model='Voyage')

        carros = dg.selecionar_carros('todos')

        assert [c.id for c in carros] == [ativo.id]

    def test_placa_especifica_filtra_por_substring(self, app, db):
        _criar_carro(db, plate='FTE-7D54', model='Voyage')
        gol = _criar_carro(db, plate='GHV-7A82', model='Gol')

        carros = dg.selecionar_carros('GHV')

        assert [c.id for c in carros] == [gol.id]


class TestProcessar:
    def test_placa_sem_carro_correspondente_nao_quebra(self, app, db, capsys):
        _criar_carro(db, plate='FTE-7D54', model='Voyage')

        dg.processar(app, 'ZZZ-9999')  # não deve levantar exceção

        saida = capsys.readouterr().out
        assert 'Nenhum carro encontrado' in saida

    def test_lista_deltas_e_sinaliza_km_negativo(self, app, db, capsys):
        carro = _criar_carro(db, plate='FTE-7D54', model='Voyage', current_km=150)
        _leitura(db, carro, 100, '2026-08-20', 'relatorio-gps-automatico:a')
        _leitura(db, carro, 80, '2026-08-21', 'relatorio-gps-automatico:b')  # KM recuou

        dg.processar(app, 'FTE-7D54')

        saida = capsys.readouterr().out
        assert 'current_km = 150' in saida
        assert 'KM RECUOU' in saida
