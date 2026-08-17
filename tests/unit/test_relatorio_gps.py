from datetime import datetime, timedelta, timezone

import relatorio_gps as rg


def _linha_relatorio(dispositivo, inicio, fim, distancia, vel_max='0 KM',
                      tempo_desloc='0h 0min 0s', tempo_parado='0h 0min 0s'):
    return f'''<!DOCTYPE html>
<html><body class="reports">
<div class="panel panel-default">
  <div class="panel-heading">Tipo de relatório: Informações gerais (resumo)</div>
  <div class="panel-body no-padding">
    <table class="table table-hover">
      <thead><tr>
        <th>Dispositivo</th><th>Início Route</th><th>Rota final</th>
        <th>Distância do percurso</th><th>Tempo de deslocamento</th>
        <th>Tempo Parado</th><th>Velocidade máxima</th>
      </tr></thead>
      <tbody>
        <tr>
          <td>{dispositivo}</td>
          <td>{inicio}</td>
          <td>{fim}</td>
          <td>{distancia}</td>
          <td>{tempo_desloc}</td>
          <td>{tempo_parado}</td>
          <td>{vel_max}</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
</body></html>'''


class TestParsearRelatorioHtml:
    def test_extrai_dispositivo_placa_e_apelido(self):
        html = _linha_relatorio(
            'HENRIQUE - FJU-4E83 - HB20S',
            '10-08-2026 04:55:00', '16-08-2026 23:15:31', '1509 Km',
        )
        dados = rg.parsear_relatorio_html(html)
        assert dados['motorista'] == 'HENRIQUE'
        assert dados['placa'] == 'FJU-4E83'
        assert dados['apelido'] == 'HB20S'

    def test_km_com_ponto_decimal_nao_e_confundido_com_milhar(self):
        # Regressão: "248.64 Km" já foi lido como 24864.0 (ponto tratado
        # como separador de milhar). O relatório usa ponto como decimal.
        html = _linha_relatorio(
            'HENRIQUE - FJU-4E83 - HB20S',
            '16-08-2026 13:56:03', '17-08-2026 13:54:23', '248.64 Km',
        )
        dados = rg.parsear_relatorio_html(html)
        assert dados['km_rodados'] == 248.64

    def test_km_inteiro_sem_decimal(self):
        html = _linha_relatorio(
            'HENRIQUE - FJU-4E83 - HB20S',
            '10-08-2026 04:55:00', '16-08-2026 23:15:31', '1509 Km',
        )
        dados = rg.parsear_relatorio_html(html)
        assert dados['km_rodados'] == 1509.0

    def test_velocidade_maxima_extraida(self):
        html = _linha_relatorio(
            'HENRIQUE - FJU-4E83 - HB20S',
            '10-08-2026 04:55:00', '16-08-2026 23:15:31', '10 Km',
            vel_max='146 KM',
        )
        dados = rg.parsear_relatorio_html(html)
        assert dados['velocidade_maxima'] == 146.0

    def test_tempo_de_deslocamento_convertido_em_minutos(self):
        html = _linha_relatorio(
            'HENRIQUE - FJU-4E83 - HB20S',
            '10-08-2026 04:55:00', '16-08-2026 23:15:31', '10 Km',
            tempo_desloc='2h 30min 45s',
        )
        dados = rg.parsear_relatorio_html(html)
        assert dados['tempo_em_movimento_minutos'] == 2 * 60 + 30 + 1  # 45s arredonda p/ 1min

    def test_datas_convertidas_para_formato_do_banco(self):
        html = _linha_relatorio(
            'HENRIQUE - FJU-4E83 - HB20S',
            '10-08-2026 04:55:00', '16-08-2026 23:15:31', '10 Km',
        )
        dados = rg.parsear_relatorio_html(html)
        assert dados['periodo_inicio'] == '2026-08-10 04:55'
        assert dados['periodo_fim'] == '2026-08-16 23:15'

    def test_retorna_none_quando_tipo_de_relatorio_nao_bate(self):
        html = '<html><body>Tipo de relatório: Rotas</body></html>'
        assert rg.parsear_relatorio_html(html) is None

    def test_retorna_none_sem_tbody(self):
        html = '<html><body>Informações gerais (resumo) mas sem tabela</body></html>'
        assert rg.parsear_relatorio_html(html) is None

    def test_retorna_none_com_linha_incompleta(self):
        html = '''<html><body>Informações gerais (resumo)
        <table><tbody><tr><td>só uma célula</td></tr></tbody></table>
        </body></html>'''
        assert rg.parsear_relatorio_html(html) is None

    def test_dispositivo_sem_todas_as_partes_nao_quebra(self):
        html = _linha_relatorio('SÓ_UM_NOME', '10-08-2026 04:55:00',
                                 '16-08-2026 23:15:31', '10 Km')
        dados = rg.parsear_relatorio_html(html)
        assert dados['motorista'] == 'SÓ_UM_NOME'
        assert dados['placa'] is None
        assert dados['apelido'] is None

    def test_data_invalida_vira_none_em_vez_de_quebrar(self):
        html = _linha_relatorio('HENRIQUE - FJU-4E83 - HB20S', 'não-é-uma-data',
                                 '16-08-2026 23:15:31', '10 Km')
        dados = rg.parsear_relatorio_html(html)
        assert dados['periodo_inicio'] is None
        assert dados['periodo_fim'] == '2026-08-16 23:15'


class TestPeriodoUltimas24h:
    def test_intervalo_tem_exatamente_24_horas(self):
        inicio_str, fim_str = rg.periodo_ultimas_24h()
        fmt = '%Y-%m-%d %H:%M'
        inicio = datetime.strptime(inicio_str, fmt)
        fim = datetime.strptime(fim_str, fmt)
        assert fim - inicio == timedelta(hours=24)

    def test_fim_e_proximo_do_agora(self):
        _, fim_str = rg.periodo_ultimas_24h()
        fim = datetime.strptime(fim_str, '%Y-%m-%d %H:%M')
        agora_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        # Compara sem timezone: só garante que não está grosseiramente errado
        # (fim está em horário de Brasília, agora_utc está em UTC).
        assert abs((agora_utc_naive - fim).total_seconds()) < 6 * 3600


class FakeResponse:
    def __init__(self, text='', status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


class FakeSession:
    """Substitui requests.Session nos testes, sem tocar a rede."""

    def __init__(self, login_html='', report_html='', login_status=302):
        self.cookies = {'XSRF-TOKEN': 'token%3Dabc'}
        self.headers = {}
        self._login_html = login_html
        self._report_html = report_html
        self._login_status = login_status
        self.calls = []

    def get(self, url):
        self.calls.append(('GET', url))
        return FakeResponse(self._login_html, 200)

    def post(self, url, headers=None, files=None):
        self.calls.append(('POST', url, headers, files))
        if 'authentication/store' in url:
            return FakeResponse('', self._login_status)
        return FakeResponse(self._report_html, 200)


class TestLogin:
    def test_extrai_csrf_token_e_poe_credenciais_no_post(self, monkeypatch):
        monkeypatch.setenv('SITE_EMAIL', 'user@example.com')
        monkeypatch.setenv('SITE_PASSWORD', 'segredo')
        login_html = '<script>window.setup={"csrf_token":"tok123","version":"4"}</script>'
        session = FakeSession(login_html=login_html)

        token = rg.login(session)

        assert token == 'tok123'
        metodo, url, headers, files = session.calls[1]
        assert url.endswith('/ui/authentication/store')
        assert files['identifier'] == (None, 'user@example.com')
        assert files['password'] == (None, 'segredo')
        assert files['_token'] == (None, 'tok123')

    def test_sem_csrf_token_na_pagina_levanta_erro(self, monkeypatch):
        monkeypatch.setenv('SITE_EMAIL', 'user@example.com')
        monkeypatch.setenv('SITE_PASSWORD', 'segredo')
        session = FakeSession(login_html='<html>sem token nenhum</html>')

        try:
            rg.login(session)
            assert False, 'deveria ter levantado RuntimeError'
        except RuntimeError:
            pass

    def test_login_com_status_de_erro_levanta_excecao(self, monkeypatch):
        monkeypatch.setenv('SITE_EMAIL', 'user@example.com')
        monkeypatch.setenv('SITE_PASSWORD', 'errada')
        login_html = '<script>window.setup={"csrf_token":"tok123"}</script>'
        session = FakeSession(login_html=login_html, login_status=422)

        try:
            rg.login(session)
            assert False, 'deveria ter levantado RuntimeError'
        except RuntimeError:
            pass


class TestGerarRelatorioHtml:
    def test_envia_device_id_e_tipo_corretos(self):
        session = FakeSession(report_html='<html>relatorio</html>')

        resultado = rg.gerar_relatorio_html(session, 'tok123', 22633,
                                             '2026-08-16 08:00', '2026-08-17 08:00')

        assert resultado == '<html>relatorio</html>'
        metodo, url, headers, files = session.calls[0]
        assert url.endswith('/ui/report')
        assert files['selected_devices[]'] == (None, 'id;true;22633')
        assert files['type'] == (None, rg.TYPE_INFORMACOES_GERAIS_RESUMO)
        assert files['datetime_from'] == (None, '2026-08-16 08:00')
        assert files['datetime_to'] == (None, '2026-08-17 08:00')
        assert files['_token'] == (None, 'tok123')
