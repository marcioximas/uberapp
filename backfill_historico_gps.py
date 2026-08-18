"""
Busca retroativamente, direto na API do site de rastreamento (Rastreamento
BSB / MyBSB), o KM rodado mês a mês desde janeiro do ano corrente até o dia
anterior à primeira leitura de GPS já confirmada de cada carro — preenche o
histórico que a automação diária (relatorio_gps.py, que só começou a gravar
em 2026-08) não tem.

Como GPSReading.confirmed_km guarda um "odômetro" absoluto (não um delta), os
meses recuperados viram uma cadeia nova começando do zero, e as leituras que
já existiam pro carro são deslocadas pra cima pelo total recuperado — assim
tudo continua formando um único histórico contínuo, sem duplicar nem perder
KM já registrado.

Rodar via GitHub Actions (workflow "Backfill histórico GPS", workflow_dispatch)
ou localmente com SITE_EMAIL/SITE_PASSWORD/DATABASE_URL no ambiente:
  python backfill_historico_gps.py            # simulação, só mostra o que faria
  python backfill_historico_gps.py --apply    # grava de fato
"""
import sys
from calendar import monthrange
from datetime import date, timedelta

import requests

from extensions import db
from models import GPSReading
from relatorio_gps import (
    CARROS_MONITORADOS,
    login,
    gerar_relatorio_html,
    parsear_relatorio_html,
    resolver_carro,
)


def _meses_do_ano_ate(data_limite):
    """Lista (ano, mes, inicio, fim) de cada mês desde janeiro do ano de
    `data_limite` até o mês de `data_limite` — o último item pode ser um mês
    parcial, indo só até `data_limite` (exclusive)."""
    meses = []
    ano = data_limite.year
    for mes in range(1, data_limite.month + 1):
        inicio = date(ano, mes, 1)
        if inicio >= data_limite:
            break
        fim_mes = date(ano, mes, monthrange(ano, mes)[1])
        fim = min(fim_mes + timedelta(days=1), data_limite)
        meses.append((ano, mes, inicio, fim))
    return meses


def _buscar_km_do_periodo(session, csrf_token, device_id, inicio, fim):
    datetime_from = inicio.strftime('%Y-%m-%d 00:00')
    datetime_to = fim.strftime('%Y-%m-%d 00:00')
    html = gerar_relatorio_html(session, csrf_token, device_id, datetime_from, datetime_to)
    dados = parsear_relatorio_html(html)
    if not dados:
        return 0
    return dados.get('km_rodados') or 0


def processar(app, aplicar=False):
    session = requests.Session()
    session.headers['User-Agent'] = 'uberapp-relatorio-gps/1.0'

    with app.app_context():
        csrf_token = login(session)

        for carro_cfg in CARROS_MONITORADOS:
            carro = resolver_carro(carro_cfg['placa'], None)
            if carro is None:
                print(f"Carro não encontrado no banco para a placa {carro_cfg['placa']}")
                continue

            primeira_leitura = (
                GPSReading.query.filter(
                    GPSReading.car_id == carro.id, GPSReading.confirmed_km.isnot(None)
                )
                .order_by(GPSReading.reading_date)
                .first()
            )
            data_limite = primeira_leitura.reading_date if primeira_leitura else date.today()

            meses = _meses_do_ano_ate(data_limite)
            if not meses:
                print(f"{carro.plate}: nada pra recuperar antes de {data_limite}.")
                continue

            print(f"{carro.plate}: recuperando {len(meses)} mês(es) antes de {data_limite}...")

            km_acumulado = 0
            novas_leituras = []
            try:
                for ano, mes, inicio, fim in meses:
                    km_delta = _buscar_km_do_periodo(
                        session, csrf_token, carro_cfg['device_id'], inicio, fim
                    )
                    if km_delta:
                        km_acumulado += km_delta
                        data_leitura = fim - timedelta(days=1)
                        print(f"  {ano}-{mes:02d}: {km_delta} km (acumulado {km_acumulado})")
                        novas_leituras.append(GPSReading(
                            car_id=carro.id,
                            image_filename=f"relatorio-gps-historico:{carro_cfg['placa']}:{ano}-{mes:02d}",
                            confidence_note="Leitura histórica recuperada retroativamente via API do rastreador.",
                            status='confirmed',
                            confirmed_km=km_acumulado,
                            reading_date=data_leitura,
                        ))
                    else:
                        print(f"  {ano}-{mes:02d}: sem dado no rastreador, pulando")
            except Exception as exc:
                print(f"Falha ao buscar histórico da placa {carro_cfg['placa']}: {exc}")
                continue

            if km_acumulado == 0:
                print(f"{carro.plate}: nenhum km recuperado, nada a fazer.")
                continue

            print(
                f"{carro.plate}: total recuperado = {km_acumulado} km "
                f"-> desloca leituras existentes e KM atual em +{km_acumulado}"
            )

            if aplicar:
                # Precisa deslocar as leituras que já existiam ANTES de gravar
                # as novas — senão a consulta abaixo (autoflush) pegaria as
                # leituras históricas recém-criadas junto e as deslocaria de novo.
                existentes = GPSReading.query.filter(
                    GPSReading.car_id == carro.id, GPSReading.confirmed_km.isnot(None)
                ).all()
                for leitura in existentes:
                    leitura.confirmed_km += km_acumulado
                    if leitura.extracted_km is not None:
                        leitura.extracted_km += km_acumulado
                for leitura in novas_leituras:
                    db.session.add(leitura)
                carro.current_km = (carro.current_km or 0) + km_acumulado
                db.session.commit()
                print(f"{carro.plate}: gravado.")
            else:
                print(f"{carro.plate}: simulação (sem --apply, nada foi gravado).")


if __name__ == '__main__':
    from app import app as flask_app
    processar(flask_app, aplicar='--apply' in sys.argv)
