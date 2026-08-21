"""
Aplica relatório(s) "Informações gerais" colados manualmente da UI do site de
rastreamento (quando puxar via API não é uma opção) como leitura histórica de
KM de cada carro — mesma lógica de backfill_historico_gps.py (o KM do período
vira uma nova leitura mais antiga que todas as outras, e desloca pra cima as
leituras que já existiam, pra formar um único histórico contínuo).

Uso:
  python backfill_historico_gps_texto.py relatorio.txt            # simulação
  python backfill_historico_gps_texto.py relatorio.txt --apply    # grava de fato

Precisa de DATABASE_URL no ambiente apontando pro banco de produção.

O arquivo pode conter um ou vários relatórios colados em sequência — cada um
começando com uma linha "Tipo de relatório:". Exemplo de um relatório:

  Tipo de relatório: Informações gerais
  Dispositivo:	HENRIQUE - SGU-6H82 - 208
  Início Route:	01-01-2026 02:08:27
  Rota final:	27-02-2026 23:59:57
  Distância do percurso:	13291.45 Km
  ...

É seguro rodar o mesmo arquivo mais de uma vez: cada relatório é marcado com
uma tag (placa + período) e, se essa tag já foi aplicada antes, o relatório é
pulado.
"""
import re
import sys
from datetime import datetime

from extensions import db
from models import GPSReading
from relatorio_gps import resolver_carro, _parse_num


def _parse_datahora(texto):
    if not texto:
        return None
    try:
        return datetime.strptime(texto, '%d-%m-%Y %H:%M:%S')
    except ValueError:
        return None


def parsear_relatorios_texto(texto):
    blocos = re.split(r'(?=Tipo de relatório:)', texto)
    relatorios = []
    for bloco in blocos:
        bloco = bloco.strip()
        if not bloco:
            continue

        campos = {}
        for linha in bloco.splitlines():
            m = re.match(r'^([^:]+):\s*(.*)$', linha.strip())
            if m:
                campos[m.group(1).strip()] = m.group(2).strip()

        dispositivo = campos.get('Dispositivo', '')
        partes = [p.strip() for p in dispositivo.split(' - ')]
        motorista = partes[0] if len(partes) > 0 else None
        placa = partes[1] if len(partes) > 1 else None
        apelido = partes[2] if len(partes) > 2 else None

        periodo_inicio = _parse_datahora(campos.get('Início Route'))
        periodo_fim = _parse_datahora(campos.get('Rota final'))
        km_rodados = _parse_num(campos.get('Distância do percurso'))

        if not (placa and periodo_fim and km_rodados):
            print(f"Bloco ignorado (faltou placa, período ou KM): {campos}")
            continue

        relatorios.append({
            'motorista': motorista,
            'placa': placa,
            'apelido': apelido,
            'periodo_inicio': periodo_inicio,
            'periodo_fim': periodo_fim,
            'km_rodados': km_rodados,
        })
    return relatorios


def processar(app, texto, aplicar=False):
    relatorios = parsear_relatorios_texto(texto)
    if not relatorios:
        print("Nenhum relatório reconhecido no texto.")
        return

    with app.app_context():
        for dados in relatorios:
            carro = resolver_carro(dados['placa'], dados['apelido'])
            if carro is None:
                print(f"Carro não encontrado para a placa {dados['placa']}, pulando.")
                continue

            tag = (
                f"relatorio-gps-manual:{dados['placa']}:"
                f"{dados['periodo_inicio'].date()}_a_{dados['periodo_fim'].date()}"
            )
            if GPSReading.query.filter_by(image_filename=tag).first():
                print(f"{carro.plate}: relatório {tag} já foi aplicado antes, pulando.")
                continue

            km_acumulado = dados['km_rodados']
            print(
                f"{carro.plate}: período {dados['periodo_inicio']} -> {dados['periodo_fim']}, "
                f"{km_acumulado} km -> desloca leituras existentes e KM atual em +{km_acumulado}"
            )

            if not aplicar:
                print(f"{carro.plate}: simulação (sem --apply, nada foi gravado).")
                continue

            existentes = GPSReading.query.filter(
                GPSReading.car_id == carro.id, GPSReading.confirmed_km.isnot(None)
            ).all()
            for leitura in existentes:
                leitura.confirmed_km += km_acumulado
                if leitura.extracted_km is not None:
                    leitura.extracted_km += km_acumulado

            db.session.add(GPSReading(
                car_id=carro.id,
                image_filename=tag,
                confidence_note="Leitura histórica aplicada manualmente a partir de relatório colado do rastreador.",
                status='confirmed',
                confirmed_km=km_acumulado,
                reading_date=dados['periodo_fim'].date(),
            ))
            carro.current_km = (carro.current_km or 0) + km_acumulado
            db.session.commit()
            print(f"{carro.plate}: gravado.")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python backfill_historico_gps_texto.py relatorio.txt [--apply]")
        sys.exit(1)

    with open(sys.argv[1], encoding='utf-8') as f:
        texto_relatorio = f.read()

    from app import app as flask_app
    processar(flask_app, texto_relatorio, aplicar='--apply' in sys.argv)
