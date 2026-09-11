from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required

from extensions import db
from forms import CarForm, RecurringItemForm
from models import Car, Fine, Transaction, RecurringItem

cars_bp = Blueprint("cars", __name__, url_prefix="/carros")


@cars_bp.route("/")
@login_required
def list_cars():
    cars = Car.query.order_by(Car.plate).all()

    hoje = date.today()
    multas_pendentes_por_carro = {}
    for fine in Fine.query.all():
        if fine.status_display(hoje) not in ("paga", "recorrida", "rejected"):
            multas_pendentes_por_carro[fine.car_id] = multas_pendentes_por_carro.get(fine.car_id, 0) + 1

    return render_template(
        "cars/list.html", cars=cars, multas_pendentes_por_carro=multas_pendentes_por_carro
    )


@cars_bp.route("/novo", methods=["GET", "POST"])
@login_required
def new_car():
    form = CarForm()
    if form.validate_on_submit():
        if Car.query.filter_by(plate=form.plate.data.upper()).first():
            flash("Já existe um carro com essa placa.", "danger")
        else:
            car = Car(
                plate=form.plate.data.upper(),
                model=form.model.data,
                year=form.year.data,
                renavam=form.renavam.data,
                chassi=form.chassi.data,
            )
            db.session.add(car)
            db.session.commit()
            flash("Carro cadastrado com sucesso.", "success")
            return redirect(url_for("cars.list_cars"))
    return render_template("cars/form.html", form=form, car=None)


@cars_bp.route("/<int:car_id>/editar", methods=["GET", "POST"])
@login_required
def edit_car(car_id):
    car = Car.query.get_or_404(car_id)
    form = CarForm(obj=car)
    if form.validate_on_submit():
        car.plate = form.plate.data.upper()
        car.model = form.model.data
        car.year = form.year.data
        car.renavam = form.renavam.data
        car.chassi = form.chassi.data
        db.session.commit()
        flash("Carro atualizado com sucesso.", "success")
        return redirect(url_for("cars.list_cars"))
    return render_template("cars/form.html", form=form, car=car)


@cars_bp.route("/<int:car_id>/desativar", methods=["POST"])
@login_required
def deactivate_car(car_id):
    car = Car.query.get_or_404(car_id)
    car.active = False
    db.session.commit()
    flash(f"Carro {car.plate} desativado.", "info")
    return redirect(url_for("cars.list_cars"))


@cars_bp.route("/<int:car_id>")
@login_required
def detail(car_id):
    car = Car.query.get_or_404(car_id)
    transacoes_recentes = (
        Transaction.query.filter_by(matched_car_id=car.id)
        .order_by(Transaction.transaction_date.desc())
        .limit(10)
        .all()
    )
    return render_template("cars/detail.html", car=car, transacoes_recentes=transacoes_recentes)


@cars_bp.route("/<int:car_id>/contas-fixas/novo", methods=["GET", "POST"])
@login_required
def new_recurring_item(car_id):
    car = Car.query.get_or_404(car_id)
    form = RecurringItemForm()
    if form.validate_on_submit():
        item = RecurringItem(
            car_id=car.id,
            name=form.name.data,
            amount=form.amount.data,
            type=form.type.data,
            frequency=form.frequency.data,
            weekday=int(form.weekday.data) if form.frequency.data == "weekly" and form.weekday.data else None,
            day_of_month=form.day_of_month.data if form.frequency.data == "monthly" else None,
            start_date=form.start_date.data,
            notes=form.notes.data,
        )
        db.session.add(item)
        db.session.commit()
        flash("Conta fixa cadastrada com sucesso.", "success")
        return redirect(url_for("cars.detail", car_id=car.id))
    return render_template("financeiro/contas_fixas_form.html", form=form, car=car, item=None)
