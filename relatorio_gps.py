"""
Gera diariamente (via GitHub Actions) o relatório "Informações gerais (resumo)"
de cada carro direto na API do site de rastreamento (Rastreamento BSB / MyBSB),
cobrindo sempre as últimas 24 horas, e grava os dados na tabela `telemetria`.

Não depende de e-mail: loga no site, pede o relatório de cada veículo via HTTP
e já recebe o HTML de volta na resposta.

Variáveis de ambiente esperadas:
  SITE_EMAIL     - e-mail de login do site de rastreamento
  SITE_PASSWORD  - senha de login do site de rastreamento
"""
import os
import re
from datetime import datetime, timedelta
from urllib.parse import unquote

import requests

from models import get_db
from gps_reader import verificar_alertas

BASE_URL = 'https://mybsb.rastreamentobsb.com.br'
TZ_SP = 'America/Sao_Paulo'

# Carros monitorados: placa (como aparece no site) -> id do rastreador na plataforma.
# Descoberto em /ui/payload/select/report/object-grouped. Se a frota mudar,
# atualize aqui (ou troque por uma consulta dinâmica a esse endpoint).
CARROS_MONITORADOS = [
    {'placa': 'FJU-4E83', 'device_id': 22633},  # HB20S
    {'placa': 'FTE-7D54', 'device_id': 14892},  # Voyage
    {'placa': 'GHV-7A82', 'device_id': 14874},  # Gol
    {'placa': 'SGU-6H82', 'device_id': 20115},  # 208
]

TYPE_INFORMACOES_GERAIS_RESUMO = '2'


def periodo_ultimas_24h():
    try:
        from zoneinfo import ZoneInfo
        agora = datetime.now(ZoneInfo(TZ_SP))
    except Exception:
        # Fallback sem tzdata instalado: Brasília é UTC-3 o ano todo (sem horário de verão).
        from datetime import timezone
        agora = datetime.now(timezone.utc) - timedelta(hours=3)
    inicio = agora - timedelta(hours=24)
    fmt = '%Y-%m-%d %H:%M'
    return inicio.strftime(fmt), agora.strftime(fmt)


def login(session):
    resp = session.get(f'{BASE_URL}/ui/auth/login')
    resp.raise_for_status()
    m = re.search(r'"csrf_token":"([^"]+)"', resp.text)
    if not m:
        raise RuntimeError('Não achei o csrf_token na página de login.')
    csrf_token = m.group(1)

    xsrf = unquote(session.cookies.get('XSRF-TOKEN', ''))
    headers = {
        'X-XSRF-TOKEN': xsrf,
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/plain, */*',
        'Referer': f'{BASE_URL}/ui/auth/login',
    }
    fields = {
        '_token': (None, csrf_token),
        'identifier': (None, os.environ['SITE_EMAIL']),
        'password': (None, os.environ['SITE_PASSWORD']),
        'remember_me': (None, '1'),
        '_method': (None, 'post'),
    }
    resp = session.post(f'{BASE_URL}/ui/authentication/store', headers=headers, files=fields)
    if resp.status_code not in (200, 302):
        raise RuntimeError(f'Falha no login: HTTP {resp.status_code}')
    return csrf_token


def gerar_relatorio_html(session, csrf_token, device_id, datetime_from, datetime_to):
    xsrf = unquote(session.cookies.get('XSRF-TOKEN', ''))
    headers = {
        'X-XSRF-TOKEN': xsrf,
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/plain, */*',
        'Referer': f'{BASE_URL}/ui/map/reports/report',
    }
    fields = {
        '_token': (None, csrf_token),
        'title': (None, ''),
        'type': (None, TYPE_INFORMACOES_GERAIS_RESUMO),
        'format': (None, 'html'),
        'datetime_from': (None, datetime_from),
        'datetime_to': (None, datetime_to),
        'period_weekdays[]': (None, ''),
        'selected_devices[]': (None, f'id;true;{device_id}'),
        'speed_limit': (None, ''),
        'skip_blank_results': (None, '0'),
        'send_to_email[]': (None, ''),
        'daily': (None, '0'),
        'daily_time': (None, ''),
        'weekly': (None, '0'),
        'weekly_time': (None, ''),
        'monthly': (None, '0'),
        'monthly_time': (None, ''),
        '_method': (None, 'put'),
        'generate': (None, '1'),
        'id': (None, ''),
    }
    resp = session.post(f'{BASE_URL}/ui/report', headers=headers, files=fields)
    resp.raise_for_status()
    return resp.text


def parsear_relatorio_html(html):
    """Extrai a única linha de dados do relatório 'Informações gerais (resumo)'."""
    if 'Informações gerais (resumo)' not in html:
        return None

    linha = re.search(r'<tbody>(.*?)</tbody>', html, re.S)
    if not linha:
        return None
    celulas = re.findall(r'<td[^>]*>(.*?)</td>', linha.group(1), re.S)
    celulas = [re.sub(r'\s+', ' ', c).strip() for c in celulas]
    if len(celulas) < 7:
        return None

    dispositivo, inicio, fim, distancia, tempo_desloc, tempo_parado, vel_max = celulas[:7]

    partes = [p.strip() for p in dispositivo.split(' - ')]
    motorista = partes[0] if len(partes) > 0 else None
    placa = partes[1] if len(partes) > 1 else None
    apelido = partes[2] if len(partes) > 2 else None

    def parse_num(texto):
        # O relatório usa ponto como separador decimal (ex: "248.64 Km"), sem
        # separador de milhar — só troca vírgula por ponto por segurança.
        m = re.search(r'([\d.,]+)', texto)
        return float(m.group(1).replace(',', '.')) if m else None

    def parse_data(texto):
        try:
            return datetime.strptime(texto, '%d-%m-%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M')
        except ValueError:
            return None

    return {
        'motorista': motorista,
        'placa': placa,
        'apelido': apelido,
        'periodo_inicio': parse_data(inicio),
        'periodo_fim': parse_data(fim),
        'km_rodados': parse_num(distancia),
        'duracao_movimento': tempo_desloc or None,
        'tempo_parado': tempo_parado or None,
        'velocidade_maxima': parse_num(vel_max),
        'horas_motor': None,
    }


def resolver_carro(cur, ph, dados):
    """Acha o carro pela placa; se não achar, tenta casar o apelido do carro
    (nome) dentro do texto do dispositivo e, nesse caso, já corrige a placa."""
    placa = (dados.get('placa') or '').strip()
    if placa:
        cur.execute(f"SELECT id FROM carros WHERE UPPER(REPLACE(placa,' ','')) = {ph}",
                     (placa.upper().replace(' ', ''),))
        row = cur.fetchone()
        if row:
            return row['id'] if hasattr(row, 'keys') else row[0]

    apelido = (dados.get('apelido') or '').replace(' ', '').upper()
    if apelido:
        cur.execute("SELECT id, nome, placa FROM carros")
        for row in cur.fetchall():
            nome = (row['nome'] if hasattr(row, 'keys') else row[1]) or ''
            carro_id = row['id'] if hasattr(row, 'keys') else row[0]
            nome_norm = nome.replace(' ', '').upper()
            if nome_norm and (nome_norm in apelido or apelido in nome_norm):
                if placa:
                    cur.execute(f"UPDATE carros SET placa = {ph} WHERE id = {ph}", (placa, carro_id))
                return carro_id
    return None


def salvar_telemetria(dados, carro_id, conn, driver):
    ph = '%s' if driver == 'pg' else '?'
    semana_ref = None
    if dados.get('periodo_fim'):
        try:
            dt = datetime.strptime(dados['periodo_fim'][:10], '%Y-%m-%d')
            semana_ref = dt.strftime('%Y-W%W')
        except ValueError:
            pass

    cur = conn.cursor()
    cur.execute(f'''
        INSERT INTO telemetria
        (carro_id, periodo_inicio, periodo_fim, semana_ref, km_rodados,
         duracao_movimento, tempo_parado, velocidade_maxima, horas_motor,
         motorista_nome, placa, imagem_path)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
    ''', (
        carro_id,
        dados.get('periodo_inicio'),
        dados.get('periodo_fim'),
        semana_ref,
        dados.get('km_rodados'),
        dados.get('duracao_movimento'),
        dados.get('tempo_parado'),
        dados.get('velocidade_maxima'),
        dados.get('horas_motor'),
        dados.get('motorista'),
        dados.get('placa'),
        'relatorio_gps@rastreamento',
    ))

    if dados.get('km_rodados'):
        cur.execute(f'UPDATE carros SET km_atual = km_atual + {ph} WHERE id = {ph}',
                    (dados['km_rodados'], carro_id))

    conn.commit()
    verificar_alertas(carro_id, conn, driver)


def processar():
    datetime_from, datetime_to = periodo_ultimas_24h()

    session = requests.Session()
    session.headers['User-Agent'] = 'uberapp-relatorio-gps/1.0'
    csrf_token = login(session)

    conn, driver = get_db()
    cur = conn.cursor()
    ph = '%s' if driver == 'pg' else '?'

    gravados = 0
    for carro in CARROS_MONITORADOS:
        html = gerar_relatorio_html(session, csrf_token, carro['device_id'], datetime_from, datetime_to)
        dados = parsear_relatorio_html(html)
        if not dados or not dados.get('placa'):
            print(f"Não consegui extrair dados para a placa {carro['placa']}")
            continue

        carro_id = resolver_carro(cur, ph, dados)
        if carro_id is None:
            print(f"Carro não encontrado no banco para a placa {dados['placa']}")
            continue

        salvar_telemetria(dados, carro_id, conn, driver)
        gravados += 1
        print(f"OK: placa={dados['placa']} km={dados.get('km_rodados')} "
              f"periodo={dados.get('periodo_inicio')} -> {dados.get('periodo_fim')}")

    conn.close()
    print(f'{gravados} relatório(s) gravado(s).')


if __name__ == '__main__':
    processar()
