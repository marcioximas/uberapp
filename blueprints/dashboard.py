from datetime import date

from flask import Blueprint, render_template
from flask_login import login_required

from models import Car, ExpectedCharge, MaintenanceItem
from importador import gerar_cobrancas_esperadas, atualizar_status_cobrancas

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    gerar_cobrancas_esperadas()
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
    total_motoristas_ativos = (
        Car.query.filter_by(active=True)
        .join(Car.rental_agreements)
        .count()
    )

    return render_template(
        "dashboard/index.html",
        resumo_cobrancas=resumo_cobrancas,
        alertas_manutencao=alertas_manutencao,
        total_carros=total_carros,
    )
