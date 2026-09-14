"""
Gera diariamente (via GitHub Actions) o relatório "Informações gerais (resumo)"
de cada carro direto na API do site de rastreamento (Rastreamento BSB / MyBSB),
cobrindo sempre as últimas 24 horas, e grava uma GPSReading já confirmada
(vem da API do rastreador, não de IA lendo um print — não precisa de revisão
humana como o fluxo de upload manual).

Variáveis de ambiente esperadas:
  SITE_EMAIL     - e-mail de login do site de rastreamento
  SITE_PASSWORD  - senha de login do site de rastreamento
"""
import os
import re
import sys
from datetime import date, datetime, timedelta
from urllib.parse import unquote

import requests

from extensions import db
from models import Car, GPSReading

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


def _agora_brasilia():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TZ_SP))
    except Exception:
        # Fallback sem tzdata instalado: Brasília é UTC-3 o ano todo (sem horário de verão).
        from datetime import timezone
        return datetime.now(timezone.utc) - timedelta(hours=3)


def periodo_ultimas_24h():
    agora = _agora_brasilia()
    inicio = agora - timedelta(hours=24)
    fmt = '%Y-%m-%d %H:%M'
    return inicio.strftime(fmt), agora.strftime(fmt)


def periodo_ultima_semana():
    agora = _agora_brasilia()
    inicio = agora - timedelta(days=7)
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


def _parse_num(texto):
    # O relatório usa ponto como separador decimal (ex: "248.64 Km"), sem
    # separador de milhar — só troca vírgula por ponto por segurança.
    m = re.search(r'([\d.,]+)', texto or '')
    return float(m.group(1).replace(',', '.')) if m else None


def _parse_data(texto):
    try:
        return datetime.strptime(texto, '%d-%m-%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return None


def _parse_duracao_minutos(texto):
    """Converte '34h 6min 18s' em minutos totais (arredondando os segundos)."""
    if not texto:
        return None
    h = re.search(r'(\d+)\s*h', texto)
    m = re.search(r'(\d+)\s*min', texto)
    s = re.search(r'(\d+)\s*s', texto)
    if not (h or m or s):
        return None
    total = 0
    if h:
        total += int(h.group(1)) * 60
    if m:
        total += int(m.group(1))
    if s:
        total += round(int(s.group(1)) / 60)
    return total


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

    return {
        'motorista': motorista,
        'placa': placa,
        'apelido': apelido,
        'periodo_inicio': _parse_data(inicio),
        'periodo_fim': _parse_data(fim),
        'km_rodados': _parse_num(distancia),
        'tempo_em_movimento_minutos': _parse_duracao_minutos(tempo_desloc),
        'velocidade_maxima': _parse_num(vel_max),
    }


def _normalizar_placa(placa):
    return (placa or '').upper().replace(' ', '').replace('-', '')


def resolver_carro(placa, apelido):
    """Acha o Car pela placa; se não achar, tenta casar o apelido do carro
    (Car.model) dentro do texto do dispositivo e, nesse caso, já corrige a placa."""
    placa_norm = _normalizar_placa(placa)
    if placa_norm:
        for carro in Car.query.filter_by(active=True).all():
            if _normalizar_placa(carro.plate) == placa_norm:
                return carro

    apelido_norm = (apelido or '').replace(' ', '').upper()
    if apelido_norm:
        for carro in Car.query.filter_by(active=True).all():
            modelo_norm = (carro.model or '').replace(' ', '').upper()
            if modelo_norm and (modelo_norm in apelido_norm or apelido_norm in modelo_norm):
                if placa:
                    carro.plate = placa
                    db.session.commit()
                return carro
    return None


def _periodo_fim_da_ultima_automatica(carro):
    """Devolve o periodo_fim (datetime) embutido na tag da última leitura
    automática confirmada do carro, ou None se não houver nenhuma."""
    ultima = GPSReading.query.filter(
        GPSReading.car_id == carro.id,
        GPSReading.confirmed_km.isnot(None),
        GPSReading.image_filename.like('relatorio-gps-automatico:%'),
        GPSReading.image_filename.notlike('relatorio-gps-automatico:baseline:%'),
    ).order_by(GPSReading.reading_date.desc(), GPSReading.created_at.desc()).first()
    if not ultima:
        return None

    partes = ultima.image_filename.split(':', 2)
    if len(partes) < 3:
        return None
    try:
        return datetime.strptime(partes[2], '%Y-%m-%d %H:%M')
    except ValueError:
        return None


def salvar_leitura_automatica(dados, carro):
    """Grava uma GPSReading já 'confirmed' (sem revisão humana) a partir do
    relatório da API do rastreador, e atualiza o current_km do carro (o
    relatório dá KM rodado no período, então soma ao km atual — e só avança
    o odômetro do carro se o resultado for maior que o atual, mesma regra
    usada na revisão manual).

    Se o período deste relatório começar antes do período coberto pela
    última leitura automática (ex.: o workflow foi disparado de novo menos
    de 24h depois, manualmente), a janela se sobrepõe à anterior e o mesmo
    trecho de KM seria contado duas vezes — nesse caso não grava nada e
    devolve None."""
    periodo_inicio_str = dados.get('periodo_inicio')
    if periodo_inicio_str:
        periodo_fim_ultima = _periodo_fim_da_ultima_automatica(carro)
        if periodo_fim_ultima:
            try:
                periodo_inicio_novo = datetime.strptime(periodo_inicio_str, '%Y-%m-%d %H:%M')
            except ValueError:
                periodo_inicio_novo = None
            if periodo_inicio_novo and periodo_inicio_novo < periodo_fim_ultima:
                return None

    km_delta = dados.get('km_rodados') or 0
    km_base = carro.current_km or 0
    km_confirmado = km_base + km_delta

    vel = dados.get('velocidade_maxima')
    vel_int = round(vel) if vel is not None else None

    # O relatório automático cobre as últimas ~24h: rodando às 08:00, ele vai
    # de ontem 08:00 até hoje 08:00 — ou seja, é quase inteiramente o KM que o
    # carro rodou ONTEM. Datar a leitura pelo fim do período (hoje) jogava esse
    # KM no dia seguinte na visão "por dia" do gráfico; usa-se o início do
    # período pra o KM cair no dia em que o carro realmente rodou.
    reading_date = date.today() - timedelta(days=1)
    if dados.get('periodo_inicio'):
        try:
            reading_date = datetime.strptime(dados['periodo_inicio'][:10], '%Y-%m-%d').date()
        except ValueError:
            pass
    elif dados.get('periodo_fim'):
        try:
            reading_date = (
                datetime.strptime(dados['periodo_fim'][:10], '%Y-%m-%d').date()
                - timedelta(days=1)
            )
        except ValueError:
            pass

    tem_leitura_confirmada = GPSReading.query.filter(
        GPSReading.car_id == carro.id, GPSReading.confirmed_km.isnot(None)
    ).first() is not None

    if not tem_leitura_confirmada:
        # Primeira leitura confirmada do carro: sem uma leitura anterior pra
        # comparar, o gráfico de KM por mês (que soma avanços entre leituras
        # consecutivas) não teria como calcular nenhum delta hoje. Grava uma
        # leitura baseline com o KM que o carro já tinha antes do período
        # coberto por este relatório, pra já existir o par.
        baseline_date = reading_date - timedelta(days=1)
        db.session.add(GPSReading(
            car_id=carro.id,
            image_filename=f"relatorio-gps-automatico:baseline:{dados.get('placa')}",
            extracted_km=km_base,
            confidence_note="Leitura baseline gerada automaticamente (primeira leitura confirmada do carro).",
            status='confirmed',
            confirmed_km=km_base,
            reading_date=baseline_date,
        ))

    leitura = GPSReading(
        car_id=carro.id,
        image_filename=f"relatorio-gps-automatico:{dados.get('placa')}:{dados.get('periodo_fim')}",
        extracted_km=km_confirmado,
        extracted_max_speed=vel_int,
        extracted_moving_time_minutes=dados.get('tempo_em_movimento_minutos'),
        raw_ai_response=None,
        confidence_note=f"Gerado automaticamente via API do rastreador (placa {dados.get('placa')}).",
        status='confirmed',
        confirmed_km=km_confirmado,
        confirmed_max_speed=vel_int,
        confirmed_moving_time_minutes=dados.get('tempo_em_movimento_minutos'),
        reading_date=reading_date,
    )
    db.session.add(leitura)

    if km_confirmado > km_base:
        carro.current_km = km_confirmado

    db.session.commit()
    return leitura


def processar(app):
    datetime_from, datetime_to = periodo_ultimas_24h()

    session = requests.Session()
    session.headers['User-Agent'] = 'uberapp-relatorio-gps/1.0'
    csrf_token = login(session)

    gravados = 0
    falhas = []
    with app.app_context():
        for carro_cfg in CARROS_MONITORADOS:
            try:
                html = gerar_relatorio_html(session, csrf_token, carro_cfg['device_id'],
                                             datetime_from, datetime_to)
                dados = parsear_relatorio_html(html)
                if not dados or not dados.get('placa'):
                    print(f"Não consegui extrair dados para a placa {carro_cfg['placa']}")
                    falhas.append(carro_cfg['placa'])
                    continue

                carro = resolver_carro(dados.get('placa'), dados.get('apelido'))
                if carro is None:
                    print(f"Carro não encontrado no banco para a placa {dados['placa']}")
                    falhas.append(dados['placa'])
                    continue

                leitura = salvar_leitura_automatica(dados, carro)
                if leitura is None:
                    print(f"PULADO (período sobreposto à última leitura automática): "
                          f"placa={dados['placa']} periodo={dados.get('periodo_inicio')} "
                          f"-> {dados.get('periodo_fim')}")
                    continue
                gravados += 1
                print(f"OK: placa={dados['placa']} km_rodados={dados.get('km_rodados')} "
                      f"km_atual={carro.current_km} periodo={dados.get('periodo_inicio')} "
                      f"-> {dados.get('periodo_fim')}")
            except Exception as exc:
                # Um carro falhar (rede, sessão, etc.) não deve impedir os demais,
                # mas precisa deixar o job vermelho (ver sys.exit abaixo) — senão a
                # falha só aparece dias depois, na conferência semanal.
                print(f"Falha ao processar placa {carro_cfg['placa']}: {exc}")
                falhas.append(carro_cfg['placa'])

    print(f'{gravados} leitura(s) gravada(s).')

    if falhas:
        print(f"\n{len(falhas)} carro(s) com falha na leitura de hoje: {', '.join(falhas)}")
        sys.exit(1)


if __name__ == '__main__':
    from app import app as flask_app
    processar(flask_app)
