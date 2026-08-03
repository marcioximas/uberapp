from datetime import date
from decimal import Decimal
from collections import defaultdict

from flask import Blueprint, render_template
from flask_login import login_required

from models import (
    Car,
    ExpectedCharge,
    MaintenanceItem,
    RentalAgreement,
    RecurringItem,
    RecurringOccurrence,
    AdHocEntry,
)
from importador import gerar_cobrancas_esperadas, atualizar_status_cobrancas
from contas_fixas import gerar_ocorrencias

dashboard_bp = Blueprint("dashboard", __name__)


def _margem_por_carro():
    hoje = date.today()
    inicio_mes = date(hoje.year, hoje.month, 1)
    fim_mes = date(hoje.year + 1, 1, 1) if hoje.month == 12 else date(hoje.year, hoje.month + 1, 1)

    margem = defaultdict(Decimal)

    cobrancas = (
        ExpectedCharge.query.join(RentalAgreement)
        .filter(
            ExpectedCharge.status == "matched",
            ExpectedCharge.due_date >= inicio_mes,
            ExpectedCharge.due_date < fim_mes,
        )
        .all()
    )
    for c in cobrancas:
        margem[c.agreement.car_id] += Decimal(c.amount_expected)

    ocorrencias = (
        RecurringOccurrence.query.join(RecurringItem)
        .filter(
            RecurringOccurrence.status == "paid",
            RecurringOccurrence.due_date >= inicio_mes,
            RecurringOccurrence.due_date < fim_mes,
        )
        .all()
    )
    for o in ocorrencias:
        sinal = 1 if o.item.type == "income" else -1
        margem[o.item.car_id] += sinal * Decimal(o.amount)

    avulsos = AdHocEntry.query.filter(
        AdHocEntry.entry_date >= inicio_mes, AdHocEntry.entry_date < fim_mes
    ).all()
    for a in avulsos:
        sinal = 1 if a.type == "income" else -1
        margem[a.car_id] += sinal * Decimal(a.amount)

    cars_by_id = {c.id: c for c in Car.query.filter_by(active=True).all()}
    ranking = [
        (cars_by_id[car_id], valor) for car_id, valor in margem.items() if car_id in cars_by_id
    ]
    ranking.sort(key=lambda par: par[1], reverse=True)
    return ranking


@dashboard_bp.route("/")
@login_required
def index():
    gerar_cobrancas_esperadas()
    gerar_ocorrencias()
    atualizar_status_cobrancas()

    resumo_cobrancas = {"pending": 0, "late": 0, "missing": 0, "matched": 0}
    for cobranca in ExpectedCharge.query.all():
        resumo_cobrancas[cobranca.status] = resumo_cobrancas.get(cobranca.status, 0) + 1

    hoje = date.today()
    alertas_manutencao = []
    for carro in Car.query.filter_by(active=True).all():
        for item in MaintenanceItem.query.filter_by(car_id=carro.id, active=True).all():
            status = item.status_alerta(carro.current_km, hoje)
            if status in ("atencao", "atrasado"):
                alertas_manutencao.append((carro, item, status))

    total_carros = Car.query.filter_by(active=True).count()
    ranking_margem = _margem_por_carro()

    return render_template(
        "dashboard/index.html",
        resumo_cobrancas=resumo_cobrancas,
        alertas_manutencao=alertas_manutencao,
        total_carros=total_carros,
        ranking_margem=ranking_margem,
    )
