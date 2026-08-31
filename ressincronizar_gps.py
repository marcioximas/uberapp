"""
Corrige um trecho do histórico de KM de um carro que ficou com leituras
sobrepostas/duplicadas (ex.: a automação diária foi disparada manualmente
mais de uma vez no mesmo dia, antes da trava de sobreposição existir).

Busca de novo na API do rastreador o KM real dia a dia (meia-noite a
meia-noite, horário de Brasília) para cada dia do período informado, e
substitui as leituras confirmadas existentes nesse trecho pela cadeia
corrigida — preserva a granularidade diária, mas sem duplicidade, ficando
idêntico ao que o rastreador reporta.

Só funciona pra resincronizar até a leitura mais recente que o carro tem
(não deixa leituras órfãs depois do período, calculadas em cima do valor
antigo/corrompido).

Uso:
  python ressincronizar_gps.py FTE-7D54 2026-08-21 2026-08-30            # simulação
  python ressincronizar_gps.py FTE-7D54 2026-08-21 2026-08-30 --apply    # grava de fato

Precisa de SITE_EMAIL/SITE_PASSWORD/DATABASE_URL no ambiente.
"""
import sys
from datetime import date, datetime, timedelta

import requests

from extensions import db
from models import GPSReading
from relatorio_gps import (
    CARROS_MONITORADOS,
    gerar_relatorio_html,
    login,
    parsear_relatorio_html,
    resolver_carro,
)


def _buscar_km_do_dia(session, csrf_token, device_id, dia):
    datetime_from = dia.strftime('%Y-%m-%d 00:00')
    datetime_to = (dia + timedelta(days=1)).strftime('%Y-%m-%d 00:00')
    html = gerar_relatorio_html(session, csrf_token, device_id, datetime_from, datetime_to)
    dados = parsear_relatorio_html(html)
    if not dados:
        return 0.0
    return dados.get('km_rodados') or 0.0


def processar(app, placa, data_inicio, data_fim, aplicar=False):
    carro_cfg = next((c for c in CARROS_MONITORADOS if c['placa'] == placa), None)
    if carro_cfg is None:
        print(f"Placa {placa} não está em CARROS_MONITORADOS.")
        return

    session = requests.Session()
    session.headers['User-Agent'] = 'uberapp-ressincronizar-gps/1.0'

    with app.app_context():
        csrf_token = login(session)

        carro = resolver_carro(placa, None)
        if carro is None:
            print(f"Carro não encontrado no banco para a placa {placa}.")
            return

        leitura_mais_recente = GPSReading.query.filter(
            GPSReading.car_id == carro.id, GPSReading.confirmed_km.isnot(None)
        ).order_by(GPSReading.reading_date.desc()).first()

        if leitura_mais_recente and leitura_mais_recente.reading_date > data_fim:
            print(
                f"{carro.plate}: existe leitura em {leitura_mais_recente.reading_date}, "
                f"depois do fim do período pedido ({data_fim}). Ajuste data_fim pra cobrir "
                f"até a leitura mais recente, senão essa leitura fica calculada em cima "
                f"do valor antigo."
            )
            return

        leitura_anterior = GPSReading.query.filter(
            GPSReading.car_id == carro.id,
            GPSReading.confirmed_km.isnot(None),
            GPSReading.reading_date < data_inicio,
        ).order_by(GPSReading.reading_date.desc()).first()
        km_base = leitura_anterior.confirmed_km if leitura_anterior else 0

        a_apagar = GPSReading.query.filter(
            GPSReading.car_id == carro.id,
            GPSReading.confirmed_km.isnot(None),
            GPSReading.reading_date >= data_inicio,
            GPSReading.reading_date <= data_fim,
        ).all()

        print(f"{carro.plate}: recalculando dia a dia de {data_inicio} a {data_fim} "
              f"(base = {km_base:.2f} km, {len(a_apagar)} leitura(s) existente(s) nesse trecho serão substituídas)...")

        km_acumulado = km_base
        novas_leituras = []
        dia = data_inicio
        while dia <= data_fim:
            km_dia = _buscar_km_do_dia(session, csrf_token, carro_cfg['device_id'], dia)
            km_acumulado += km_dia
            print(f"  {dia}: {km_dia:.2f} km (acumulado {km_acumulado:.2f})")
            novas_leituras.append(GPSReading(
                car_id=carro.id,
                image_filename=f"relatorio-gps-ressincronizado:{placa}:{dia.isoformat()}",
                confidence_note="Leitura recalculada dia a dia pra corrigir sobreposição da automação diária.",
                status='confirmed',
                confirmed_km=km_acumulado,
                reading_date=dia,
            ))
            dia += timedelta(days=1)

        print(f"{carro.plate}: current_km atual = {carro.current_km:.2f} -> "
              f"{km_acumulado:.2f} depois da correção.")

        if not aplicar:
            print(f"{carro.plate}: simulação (sem --apply, nada foi gravado).")
            return

        for leitura in a_apagar:
            db.session.delete(leitura)
        for leitura in novas_leituras:
            db.session.add(leitura)
        carro.current_km = km_acumulado
        db.session.commit()
        print(f"{carro.plate}: corrigido.")


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Uso: python ressincronizar_gps.py <placa> <data_inicio AAAA-MM-DD> "
              "<data_fim AAAA-MM-DD> [--apply]")
        sys.exit(1)

    placa_arg = sys.argv[1]
    data_inicio_arg = datetime.strptime(sys.argv[2], '%Y-%m-%d').date()
    data_fim_arg = datetime.strptime(sys.argv[3], '%Y-%m-%d').date()

    from app import app as flask_app
    processar(flask_app, placa_arg, data_inicio_arg, data_fim_arg, aplicar='--apply' in sys.argv)
