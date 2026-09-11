"""Persistência de multas raspadas do Detran-DF (model Fine, em models.py).

Contrato único entre a raspagem (detran_df.py / detran_df_multas.py) e o
banco: quem consulta o Detran-DF nunca grava direto no model, só chama
upsert_fine() com o dict que extraiu da página.
"""
from datetime import datetime

from extensions import db
from models import Fine


def upsert_fine(car, dados, consulted_at=None):
    """Cria ou atualiza uma Fine a partir de dados extraídos da consulta ao Detran-DF.

    `dados` é um dict com chaves: numero_ait (obrigatória), data_infracao, local,
    descricao, valor, vencimento, pontos, orgao_status, raw_response.

    Casa por (car_id, numero_ait). Se já existir, atualiza só os campos
    extracted_*/raw_response/consulted_at — nunca sobrescreve confirmed_valor,
    confirmed_vencimento, status, notes ou paid_date, que são humanos.

    Não commita: quem chama decide o momento do commit (permite consultar
    vários carros e comitar 1x, ou 1 commit por carro pra isolar falhas).

    Retorna (fine, is_new).
    """
    fine = Fine.query.filter_by(car_id=car.id, numero_ait=dados["numero_ait"]).first()
    is_new = fine is None
    if is_new:
        fine = Fine(car_id=car.id, numero_ait=dados["numero_ait"])
        db.session.add(fine)

    fine.extracted_data_infracao = dados.get("data_infracao")
    fine.extracted_local = dados.get("local")
    fine.extracted_descricao = dados.get("descricao")
    fine.extracted_valor = dados.get("valor")
    fine.extracted_vencimento = dados.get("vencimento")
    fine.extracted_pontos = dados.get("pontos")
    fine.extracted_orgao_status = dados.get("orgao_status")
    fine.raw_response = dados.get("raw_response")
    fine.consulted_at = consulted_at or datetime.utcnow()
    return fine, is_new
