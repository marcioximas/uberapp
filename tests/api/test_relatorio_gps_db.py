import relatorio_gps as rg
from models import Car, GPSReading


def _criar_carro(db, plate='', model='', current_km=0):
    carro = Car(plate=plate, model=model, current_km=current_km)
    db.session.add(carro)
    db.session.commit()
    return carro


class TestResolverCarro:
    def test_encontra_por_placa_exata(self, app, db):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol')

        assert rg.resolver_carro('GHV-7A82', 'GOL').id == carro.id

    def test_encontra_por_placa_ignorando_espacos_hifen_e_caixa(self, app, db):
        carro = _criar_carro(db, plate='GHV7A82', model='Gol')

        assert rg.resolver_carro('ghv 7a82', 'GOL').id == carro.id

    def test_fallback_por_apelido_quando_placa_nao_bate(self, app, db):
        carro = _criar_carro(db, plate='', model='HB20')

        assert rg.resolver_carro('FJU-4E83', 'HB20S').id == carro.id

    def test_fallback_por_apelido_corrige_placa_no_banco(self, app, db):
        carro = _criar_carro(db, plate='', model='HB20')

        rg.resolver_carro('FJU-4E83', 'HB20S')

        db.session.refresh(carro)
        assert carro.plate == 'FJU-4E83'

    def test_retorna_none_quando_nao_acha_nada(self, app, db):
        _criar_carro(db, plate='FTE-7D54', model='Voyage')

        assert rg.resolver_carro('XXX-9999', 'DESCONHECIDO') is None

    def test_ignora_carro_inativo(self, app, db):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol')
        carro.active = False
        db.session.commit()

        assert rg.resolver_carro('GHV-7A82', 'GOL') is None


class TestSalvarLeituraAutomatica:
    def test_grava_confirmada_e_soma_km_atual(self, app, db):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol', current_km=1000)
        dados = {
            'motorista': 'HENRIQUE', 'placa': 'GHV-7A82', 'apelido': 'GOL',
            'periodo_inicio': '2026-08-16 08:00', 'periodo_fim': '2026-08-17 08:00',
            'km_rodados': 60.7, 'tempo_em_movimento_minutos': 120,
            'velocidade_maxima': 90.0,
        }

        leitura = rg.salvar_leitura_automatica(dados, carro)

        assert leitura.status == 'confirmed'
        assert leitura.confirmed_km == 1061  # 1000 + round(60.7)
        assert leitura.extracted_km == 1061
        assert leitura.confirmed_max_speed == 90
        assert leitura.confirmed_moving_time_minutes == 120
        assert leitura.reading_date.isoformat() == '2026-08-17'

        db.session.refresh(carro)
        assert carro.current_km == 1061

    def test_nao_regride_km_do_carro(self, app, db):
        # Delta negativo/zero não deveria existir na prática, mas o carro não
        # pode nunca "andar pra trás" mesmo assim.
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol', current_km=5000)
        dados = {
            'placa': 'GHV-7A82', 'periodo_fim': '2026-08-17 08:00',
            'km_rodados': 0, 'tempo_em_movimento_minutos': None, 'velocidade_maxima': None,
        }

        rg.salvar_leitura_automatica(dados, carro)

        db.session.refresh(carro)
        assert carro.current_km == 5000

    def test_leitura_fica_associada_ao_carro(self, app, db):
        carro = _criar_carro(db, plate='GHV-7A82', model='Gol', current_km=0)
        dados = {
            'placa': 'GHV-7A82', 'periodo_fim': '2026-08-17 08:00',
            'km_rodados': 10, 'tempo_em_movimento_minutos': 30, 'velocidade_maxima': 80,
        }

        rg.salvar_leitura_automatica(dados, carro)

        leituras = GPSReading.query.filter_by(car_id=carro.id).all()
        assert len(leituras) == 1
        assert leituras[0].confidence_note.startswith('Gerado automaticamente')


class TestProcessar:
    def _html_para(self, placa, apelido, km):
        return f'''<html><body>Tipo de relatório: Informações gerais (resumo)
        <table><tbody><tr>
          <td>HENRIQUE - {placa} - {apelido}</td>
          <td>16-08-2026 08:00:00</td>
          <td>17-08-2026 08:00:00</td>
          <td>{km} Km</td>
          <td>1h 0min 0s</td>
          <td>23h 0min 0s</td>
          <td>80 KM</td>
        </tr></tbody></table>
        </body></html>'''

    def test_grava_todos_os_carros_monitorados(self, app, db, monkeypatch):
        carro_gol = _criar_carro(db, plate='GHV-7A82', model='Gol')
        carro_voyage = _criar_carro(db, plate='FTE-7D54', model='Voyage')

        monkeypatch.setattr(rg, 'CARROS_MONITORADOS', [
            {'placa': 'GHV-7A82', 'device_id': 111},
            {'placa': 'FTE-7D54', 'device_id': 222},
        ])
        htmls = {
            111: self._html_para('GHV-7A82', 'GOL', '60.7'),
            222: self._html_para('FTE-7D54', 'VOYAGE', '0.01'),
        }
        monkeypatch.setattr(rg, 'login', lambda session: 'tok123')
        monkeypatch.setattr(
            rg, 'gerar_relatorio_html',
            lambda session, token, device_id, dfrom, dto: htmls[device_id],
        )

        rg.processar(app)

        assert GPSReading.query.filter_by(car_id=carro_gol.id).count() == 1
        assert GPSReading.query.filter_by(car_id=carro_voyage.id).count() == 1

    def test_falha_em_um_carro_nao_impede_os_outros(self, app, db, monkeypatch):
        carro_gol = _criar_carro(db, plate='GHV-7A82', model='Gol')
        carro_voyage = _criar_carro(db, plate='FTE-7D54', model='Voyage')

        monkeypatch.setattr(rg, 'CARROS_MONITORADOS', [
            {'placa': 'GHV-7A82', 'device_id': 111},
            {'placa': 'FTE-7D54', 'device_id': 222},
        ])

        def gerar_relatorio_falho(session, token, device_id, dfrom, dto):
            if device_id == 111:
                raise RuntimeError('falha de rede simulada')
            return self._html_para('FTE-7D54', 'VOYAGE', '0.01')

        monkeypatch.setattr(rg, 'login', lambda session: 'tok123')
        monkeypatch.setattr(rg, 'gerar_relatorio_html', gerar_relatorio_falho)

        rg.processar(app)  # não deve levantar exceção

        assert GPSReading.query.filter_by(car_id=carro_gol.id).count() == 0
        assert GPSReading.query.filter_by(car_id=carro_voyage.id).count() == 1

    def test_placa_nao_cadastrada_e_pulada_sem_quebrar(self, app, db, monkeypatch):
        monkeypatch.setattr(rg, 'CARROS_MONITORADOS', [
            {'placa': 'ZZZ-0000', 'device_id': 333},
        ])
        monkeypatch.setattr(rg, 'login', lambda session: 'tok123')
        monkeypatch.setattr(
            rg, 'gerar_relatorio_html',
            lambda session, token, device_id, dfrom, dto: self._html_para('ZZZ-0000', 'DESCONHECIDO', '5'),
        )

        rg.processar(app)  # não deve levantar exceção mesmo sem nenhum carro no banco

        assert GPSReading.query.count() == 0
