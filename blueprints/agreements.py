from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required
from datetime import date

from extensions import db
from forms import RentalAgreementForm
from models import Car, Driver, RentalAgreement

agreements_bp = Blueprint("agreements", __name__)


@agreements_bp.route("/carros/<int:car_id>/contrato/novo", methods=["GET", "POST"])
@login_required
def new_agreement(car_id):
    car = Car.query.get_or_404(car_id)
    form = RentalAgreementForm()
    form.driver_id.choices = [
        (d.id, d.name) for d in Driver.query.filter_by(active=True).order_by(Driver.name).all()
    ]

    if form.validate_on_submit():
        # Encerra o contrato ativo atual, se houver, antes de criar o novo
        atual = car.current_agreement
        if atual:
            atual.end_date = date.today()
            atual.active = False

        agreement = RentalAgreement(
            car_id=car.id,
            driver_id=form.driver_id.data,
            amount=form.amount.data,
            frequency=form.frequency.data,
            weekday=int(form.weekday.data) if form.frequency.data == "weekly" and form.weekday.data else None,
            day_of_month=form.day_of_month.data if form.frequency.data == "monthly" else None,
            start_date=form.start_date.data,
            reliability_pct=form.reliability_pct.data or 100,
            notes=form.notes.data,
        )
        db.session.add(agreement)
        db.session.commit()
        flash("Contrato de aluguel criado com sucesso.", "success")
        return redirect(url_for("cars.detail", car_id=car.id))

    return render_template("agreements/form.html", form=form, car=car)


@agreements_bp.route("/contratos/<int:agreement_id>/encerrar", methods=["POST"])
@login_required
def end_agreement(agreement_id):
    agreement = RentalAgreement.query.get_or_404(agreement_id)
    agreement.end_date = date.today()
    agreement.active = False
    db.session.commit()
    flash("Contrato encerrado.", "info")
    return redirect(url_for("cars.detail", car_id=agreement.car_id))
