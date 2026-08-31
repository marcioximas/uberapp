"""
Roda semanalmente (via GitHub Actions, todo domingo às 23h de Brasília) e
confere se o KM que a API do rastreador reporta para os últimos 7 dias bate
com o que o relatório diário automático (relatorio_gps.py) já gravou pro
carro no mesmo período.

Não grava nada no banco — é só uma conferência. Se algo divergir (a rotina
diária falhou em algum dia, alguém colou um relatório manual sobreposto,
etc.) o job termina com erro, e o GitHub notifica por e-mail.

Variáveis de ambiente esperadas: as mesmas de relatorio_gps.py
(SITE_EMAIL, SITE_PASSWORD, DATABASE_URL).
"""
import sys
from datetime import datetime

import requests

from models import GPSReading
from relatorio_gps import (
    CARROS_MONITORADOS,
    gerar_relatorio_html,
    login,
    parsear_relatorio_html,
    periodo_ultima_semana,
    resolver_carro,
)

TOLERANCIA_KM = 5.0


def km_registrado_periodo(carro, inicio_date, fim_date):
    """Soma o que o nosso banco já tem gravado pro carro no período, usando
    a diferença entre o confirmed_km (odômetro acumulado) na última leitura
    do período e na última leitura anterior a ele. Retorna None se não
    houver nenhuma leitura confirmada dentro do período pra comparar."""
    anterior = GPSReading.query.filter(
        GPSReading.car_id == carro.id,
        GPSReading.confirmed_km.isnot(None),
        GPSReading.reading_date < inicio_date,
    ).order_by(GPSReading.reading_date.desc()).first()

    ultima_no_periodo = GPSReading.query.filter(
        GPSReading.car_id == carro.id,
        GPSReading.confirmed_km.isnot(None),
        GPSReading.reading_date >= inicio_date,
        GPSReading.reading_date <= fim_date,
    ).order_by(GPSReading.reading_date.desc()).first()

    if not ultima_no_periodo:
        return None

    base = anterior.confirmed_km if anterior else 0
    return ultima_no_periodo.confirmed_km - base


def processar(app):
    datetime_from, datetime_to = periodo_ultima_semana()
    inicio_date = datetime.strptime(datetime_from, '%Y-%m-%d %H:%M').date()
    fim_date = datetime.strptime(datetime_to, '%Y-%m-%d %H:%M').date()

    session = requests.Session()
    session.headers['User-Agent'] = 'uberapp-conferencia-semanal/1.0'
    csrf_token = login(session)

    divergencias = []
    with app.app_context():
        for carro_cfg in CARROS_MONITORADOS:
            try:
                html = gerar_relatorio_html(session, csrf_token, carro_cfg['device_id'],
                                             datetime_from, datetime_to)
                dados = parsear_relatorio_html(html)
                if not dados or not dados.get('placa'):
                    print(f"Não consegui extrair dados para a placa {carro_cfg['placa']}")
                    continue

                carro = resolver_carro(dados.get('placa'), dados.get('apelido'))
                if carro is None:
                    print(f"Carro não encontrado no banco para a placa {dados['placa']}")
                    continue

                km_rastreador = dados.get('km_rodados') or 0
                km_nosso = km_registrado_periodo(carro, inicio_date, fim_date)

                if km_nosso is None:
                    print(f"{carro.plate}: sem leitura automática no período pra comparar "
                          f"(rastreador reporta {km_rastreador:.1f} km).")
                    continue

                diff = km_nosso - km_rastreador
                divergente = abs(diff) > TOLERANCIA_KM
                status = "DIVERGENTE" if divergente else "OK"
                print(f"{carro.plate}: rastreador={km_rastreador:.1f} km, "
                      f"nosso={km_nosso:.1f} km, diff={diff:+.1f} km [{status}]")

                if divergente:
                    divergencias.append(carro.plate)
            except Exception as exc:
                # Um carro falhar (rede, sessão, etc.) não deve impedir os demais.
                print(f"Falha ao conferir placa {carro_cfg['placa']}: {exc}")
                divergencias.append(carro_cfg['placa'])

    if divergencias:
        print(f"\n{len(divergencias)} carro(s) com divergência: {', '.join(divergencias)}")
        sys.exit(1)

    print("\nTodos os carros conferem dentro da tolerância.")


if __name__ == '__main__':
    from app import app as flask_app
    processar(flask_app)
