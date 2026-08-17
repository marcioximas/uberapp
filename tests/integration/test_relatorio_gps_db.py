import relatorio_gps as rg


def _criar_carro(conn, nome, placa='', km_atual=0):
    conn.execute("INSERT INTO carros (nome, placa, km_atual) VALUES (?, ?, ?)", (nome, placa, km_atual))
    conn.commit()
    return conn.execute("SELECT id FROM carros WHERE nome=?", (nome,)).fetchone()['id']


class TestResolverCarro:
    def test_encontra_por_placa_exata(self, conn):
        carro_id = _criar_carro(conn, 'Gol', placa='GHV-7A82')
        dados = {'placa': 'GHV-7A82', 'apelido': 'GOL'}

        assert rg.resolver_carro(conn.cursor(), '?', dados) == carro_id

    def test_encontra_por_placa_ignorando_espacos_e_caixa(self, conn):
        carro_id = _criar_carro(conn, 'Gol', placa='GHV-7A82')
        dados = {'placa': 'ghv 7a82', 'apelido': 'GOL'}

        assert rg.resolver_carro(conn.cursor(), '?', dados) == carro_id

    def test_fallback_por_apelido_quando_placa_nao_bate(self, conn):
        carro_id = _criar_carro(conn, 'HB 20', placa='')
        dados = {'placa': 'FJU-4E83', 'apelido': 'HB20S'}

        assert rg.resolver_carro(conn.cursor(), '?', dados) == carro_id

    def test_fallback_por_apelido_corrige_placa_no_banco(self, conn):
        carro_id = _criar_carro(conn, 'HB 20', placa='')
        dados = {'placa': 'FJU-4E83', 'apelido': 'HB20S'}

        rg.resolver_carro(conn.cursor(), '?', dados)
        conn.commit()

        placa_gravada = conn.execute("SELECT placa FROM carros WHERE id=?", (carro_id,)).fetchone()['placa']
        assert placa_gravada == 'FJU-4E83'

    def test_retorna_none_quando_nao_acha_nada(self, conn):
        _criar_carro(conn, 'Voyage', placa='FTE-7D54')
        dados = {'placa': 'XXX-9999', 'apelido': 'DESCONHECIDO'}

        assert rg.resolver_carro(conn.cursor(), '?', dados) is None


class TestSalvarTelemetria:
    def test_grava_linha_e_atualiza_km_atual(self, conn):
        carro_id = _criar_carro(conn, 'Gol', placa='GHV-7A82', km_atual=1000)
        dados = {
            'motorista': 'HENRIQUE', 'placa': 'GHV-7A82', 'apelido': 'GOL',
            'periodo_inicio': '2026-08-16 08:00', 'periodo_fim': '2026-08-17 08:00',
            'km_rodados': 60.7, 'duracao_movimento': '2h 0min 0s',
            'tempo_parado': '22h 0min 0s', 'velocidade_maxima': 90.0, 'horas_motor': None,
        }

        rg.salvar_telemetria(dados, carro_id, conn, 'sqlite')

        row = conn.execute("SELECT * FROM telemetria WHERE carro_id=?", (carro_id,)).fetchone()
        assert row['km_rodados'] == 60.7
        assert row['placa'] == 'GHV-7A82'
        assert row['motorista_nome'] == 'HENRIQUE'

        km_atual = conn.execute("SELECT km_atual FROM carros WHERE id=?", (carro_id,)).fetchone()['km_atual']
        assert km_atual == 1060.7

    def test_dispara_alerta_de_manutencao(self, conn):
        carro_id = _criar_carro(conn, 'Gol', placa='GHV-7A82', km_atual=6900)
        conn.execute(
            "INSERT INTO manutencoes (carro_id, tipo, km_proximo, concluido) VALUES (?, 'oleo', 7000, 0)",
            (carro_id,),
        )
        conn.commit()
        dados = {
            'motorista': 'HENRIQUE', 'placa': 'GHV-7A82', 'apelido': 'GOL',
            'periodo_inicio': '2026-08-16 08:00', 'periodo_fim': '2026-08-17 08:00',
            'km_rodados': 200, 'duracao_movimento': None, 'tempo_parado': None,
            'velocidade_maxima': None, 'horas_motor': None,
        }

        rg.salvar_telemetria(dados, carro_id, conn, 'sqlite')

        alerta = conn.execute("SELECT * FROM alertas_manutencao WHERE carro_id=?", (carro_id,)).fetchone()
        assert alerta is not None


class TestProcessar:
    def _preparar_carros(self, conn):
        id_gol = _criar_carro(conn, 'Gol', placa='GHV-7A82')
        id_voyage = _criar_carro(conn, 'Voyage', placa='FTE-7D54')
        return id_gol, id_voyage

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

    def test_grava_todos_os_carros_monitorados(self, conn, monkeypatch):
        id_gol, id_voyage = self._preparar_carros(conn)

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

        rg.processar()

        assert conn.execute("SELECT COUNT(*) c FROM telemetria WHERE carro_id=?", (id_gol,)).fetchone()['c'] == 1
        assert conn.execute("SELECT COUNT(*) c FROM telemetria WHERE carro_id=?", (id_voyage,)).fetchone()['c'] == 1

    def test_falha_em_um_carro_nao_impede_os_outros(self, conn, monkeypatch):
        id_gol, id_voyage = self._preparar_carros(conn)

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

        rg.processar()  # não deve levantar exceção

        assert conn.execute("SELECT COUNT(*) c FROM telemetria WHERE carro_id=?", (id_gol,)).fetchone()['c'] == 0
        assert conn.execute("SELECT COUNT(*) c FROM telemetria WHERE carro_id=?", (id_voyage,)).fetchone()['c'] == 1

    def test_placa_nao_cadastrada_e_pulada_sem_quebrar(self, conn, monkeypatch):
        monkeypatch.setattr(rg, 'CARROS_MONITORADOS', [
            {'placa': 'ZZZ-0000', 'device_id': 333},
        ])
        monkeypatch.setattr(rg, 'login', lambda session: 'tok123')
        monkeypatch.setattr(
            rg, 'gerar_relatorio_html',
            lambda session, token, device_id, dfrom, dto: self._html_para('ZZZ-0000', 'DESCONHECIDO', '5'),
        )

        rg.processar()  # não deve levantar exceção mesmo sem nenhum carro no banco

        assert conn.execute("SELECT COUNT(*) c FROM telemetria").fetchone()['c'] == 0
