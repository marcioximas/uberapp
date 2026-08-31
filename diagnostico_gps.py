"""
Lista o histórico completo de leituras de GPS confirmadas de um carro (ou de
todos), na ordem em que foram gravadas, pra investigar de onde vem uma
diferença de KM. Só lê — não grava nada.

Uso:
  python diagnostico_gps.py                # todos os carros monitorados
  python diagnostico_gps.py FTE-7D54       # só esse carro

Precisa de DATABASE_URL no ambiente apontando pro banco que você quer inspecionar.
"""
import sys

from models import Car, GPSReading


def _periodo_da_tag(tag):
    """Extrai o período embutido na tag de relatório colado/automático, se houver."""
    partes = tag.split(':')
    if len(partes) >= 3 and partes[0] in ('relatorio-gps-manual', 'relatorio-gps-automatico'):
        return partes[-1]
    return ''


def diagnosticar_carro(carro):
    leituras = GPSReading.query.filter(
        GPSReading.car_id == carro.id, GPSReading.confirmed_km.isnot(None)
    ).order_by(GPSReading.created_at).all()

    if not leituras:
        print(f"\n{carro.plate} ({carro.model}): nenhuma leitura confirmada.")
        return

    print(f"\n{carro.plate} ({carro.model}) — current_km = {carro.current_km}")
    print(f"{'reading_date':<12} {'confirmed_km':>14} {'delta':>10}  tag")
    anterior = None
    for leitura in leituras:
        delta = leitura.confirmed_km - anterior if anterior is not None else None
        delta_str = f"{delta:+.2f}" if delta is not None else "-"
        aviso = ""
        if delta is not None and delta < 0:
            aviso = "  <-- KM RECUOU (suspeito)"
        print(f"{leitura.reading_date} {leitura.confirmed_km:>14.2f} {delta_str:>10}  "
              f"{leitura.image_filename}{aviso}")
        anterior = leitura.confirmed_km


def selecionar_carros(placa):
    """Resolve o argumento de placa (None/'' /'todos' = todos os carros ativos,
    senão busca por placa contendo o texto informado). Precisa estar dentro
    de um app_context."""
    if placa and placa.strip().lower() == 'todos':
        placa = None
    if placa:
        return Car.query.filter(Car.plate.ilike(f"%{placa}%")).all()
    return Car.query.filter_by(active=True).order_by(Car.plate).all()


def processar(app, placa):
    with app.app_context():
        carros = selecionar_carros(placa)
        if not carros:
            print(f"Nenhum carro encontrado com placa contendo '{placa}'.")
            return
        for carro in carros:
            diagnosticar_carro(carro)


if __name__ == '__main__':
    from app import app as flask_app
    processar(flask_app, sys.argv[1] if len(sys.argv) > 1 else None)
