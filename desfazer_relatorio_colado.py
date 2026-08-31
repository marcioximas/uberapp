"""
Desfaz um relatório colado aplicado por engano (via backfill_historico_gps_texto.py
/ tela "Aplicar relatório" da aba Carros) quando o período colado se sobrepunha
a leituras que a automação diária/semanal já tinha gravado — contando aquele
trecho de KM duas vezes.

Reverte exatamente a operação que aplicar_relatorio fez: subtrai o KM daquele
relatório de todas as outras leituras confirmadas do carro (que tinham sido
deslocadas pra cima quando o relatório foi aplicado), apaga a leitura que o
relatório colado criou, e tira o mesmo valor do current_km do carro.

Uso:
  python desfazer_relatorio_colado.py <tag>            # simulação
  python desfazer_relatorio_colado.py <tag> --apply    # grava de fato

<tag> é o image_filename da leitura a desfazer, no formato
  relatorio-gps-manual:PLACA:AAAA-MM-DD_a_AAAA-MM-DD
(veja em diagnostico_gps.py ou na tela "Histórico de leituras GPS" do sistema).

Precisa de DATABASE_URL no ambiente apontando pro banco de produção.
"""
import sys

from extensions import db
from models import GPSReading


def desfazer(tag, aplicar=False):
    leitura_colada = GPSReading.query.filter_by(image_filename=tag).first()
    if leitura_colada is None:
        raise ValueError(f"Nenhuma leitura encontrada com a tag '{tag}'.")
    if leitura_colada.confirmed_km is None:
        raise ValueError(f"Leitura '{tag}' não tem confirmed_km — nada a desfazer.")

    km_aplicado = leitura_colada.confirmed_km
    carro = leitura_colada.car

    outras = GPSReading.query.filter(
        GPSReading.car_id == carro.id,
        GPSReading.id != leitura_colada.id,
        GPSReading.confirmed_km.isnot(None),
    ).all()

    km_atual_novo = (carro.current_km or 0) - km_aplicado
    print(
        f"{carro.plate}: desfazendo '{tag}' ({km_aplicado:.2f} km) -> vai subtrair "
        f"{km_aplicado:.2f} km de {len(outras)} leitura(s) e do current_km "
        f"({carro.current_km:.2f} -> {km_atual_novo:.2f}), e apagar a leitura da tag."
    )

    if not aplicar:
        print(f"{carro.plate}: simulação (sem --apply, nada foi gravado).")
        return

    for leitura in outras:
        leitura.confirmed_km -= km_aplicado
        if leitura.extracted_km is not None:
            leitura.extracted_km -= km_aplicado

    carro.current_km = km_atual_novo
    db.session.delete(leitura_colada)
    db.session.commit()
    print(f"{carro.plate}: desfeito.")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python desfazer_relatorio_colado.py <tag> [--apply]")
        sys.exit(1)

    from app import app as flask_app
    with flask_app.app_context():
        desfazer(sys.argv[1], aplicar='--apply' in sys.argv)
