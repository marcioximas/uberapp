from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import db
from forms import FineReviewForm
from models import Car, Fine

fines_bp = Blueprint("fines", __name__, url_prefix="/multas")


@fines_bp.route("/")
@login_required
def alertas():
    hoje = date.today()
    linhas = []
    for car in Car.query.filter_by(active=True).all():
        for fine in Fine.query.filter_by(car_id=car.id).all():
            status = fine.status_display(hoje)
            if status not in ("paga", "recorrida", "rejected"):
                linhas.append((car, fine, status))
    linhas.sort(key=lambda x: 0 if x[2] == "vencida" else 1)
    return render_template("fines/alertas.html", linhas=linhas)


@fines_bp.route("/<int:fine_id>/revisar", methods=["GET", "POST"])
@login_required
def revisar(fine_id):
    fine = Fine.query.get_or_404(fine_id)
    form = FineReviewForm(
        confirmed_valor=fine.confirmed_valor if fine.confirmed_valor is not None else fine.extracted_valor,
        confirmed_vencimento=fine.confirmed_vencimento or fine.extracted_vencimento,
        notes=fine.notes,
    )
    if form.validate_on_submit():
        fine.confirmed_valor = form.confirmed_valor.data
        fine.confirmed_vencimento = form.confirmed_vencimento.data
        fine.notes = form.notes.data
        fine.status = "confirmed"
        fine.reviewed_by_user_id = current_user.id
        db.session.commit()
        flash("Multa confirmada.", "success")
        return redirect(url_for("cars.detail", car_id=fine.car_id))
    return render_template("fines/revisar.html", fine=fine, form=form)


@fines_bp.route("/<int:fine_id>/pagar", methods=["POST"])
@login_required
def marcar_paga(fine_id):
    fine = Fine.query.get_or_404(fine_id)
    fine.status = "paga"
    fine.paid_date = date.today()
    db.session.commit()
    flash(f"Multa {fine.numero_ait} marcada como paga.", "success")
    return redirect(request.referrer or url_for("cars.detail", car_id=fine.car_id))


@fines_bp.route("/<int:fine_id>/recorrer", methods=["POST"])
@login_required
def marcar_recorrida(fine_id):
    fine = Fine.query.get_or_404(fine_id)
    fine.status = "recorrida"
    if request.form.get("notes"):
        fine.notes = request.form["notes"]
    db.session.commit()
    flash(f"Multa {fine.numero_ait} marcada como recorrida.", "info")
    return redirect(request.referrer or url_for("cars.detail", car_id=fine.car_id))


@fines_bp.route("/<int:fine_id>/rejeitar", methods=["POST"])
@login_required
def rejeitar(fine_id):
    fine = Fine.query.get_or_404(fine_id)
    fine.status = "rejected"
    fine.reviewed_by_user_id = current_user.id
    db.session.commit()
    flash("Registro de multa descartado.", "info")
    return redirect(request.referrer or url_for("cars.detail", car_id=fine.car_id))
