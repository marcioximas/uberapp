from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from forms import MaintenanceItemForm, MaintenanceLogForm
from models import Car, MaintenanceItem, MaintenanceLog

maintenance_bp = Blueprint("maintenance", __name__, url_prefix="/manutencao")


@maintenance_bp.route("/")
@login_required
def hub():
    cars = Car.query.filter_by(active=True).order_by(Car.plate).all()
    return render_template("maintenance/hub.html", cars=cars)


@maintenance_bp.route("/<int:car_id>/checklist")
@login_required
def checklist(car_id):
    car = Car.query.get_or_404(car_id)
    itens = MaintenanceItem.query.filter_by(car_id=car.id, active=True).all()
    hoje = date.today()
    itens_com_status = [(item, item.status_alerta(car.current_km, hoje)) for item in itens]
    log_form = MaintenanceLogForm()
    return render_template(
        "maintenance/checklist.html", car=car, itens_com_status=itens_com_status, log_form=log_form
    )


@maintenance_bp.route("/<int:car_id>/checklist/novo", methods=["GET", "POST"])
@login_required
def new_item(car_id):
    car = Car.query.get_or_404(car_id)
    form = MaintenanceItemForm()
    if form.validate_on_submit():
        if not form.km_interval.data and not form.date_interval_days.data:
            flash("Informe ao menos um intervalo (KM ou dias).", "danger")
        else:
            item = MaintenanceItem(
                car_id=car.id,
                name=form.name.data,
                km_interval=form.km_interval.data,
                date_interval_days=form.date_interval_days.data,
                notes=form.notes.data,
            )
            db.session.add(item)
            db.session.commit()
            flash("Item de manutenção criado.", "success")
            return redirect(url_for("maintenance.checklist", car_id=car.id))
    return render_template("maintenance/item_form.html", form=form, car=car, item=None)


@maintenance_bp.route("/itens/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    item = MaintenanceItem.query.get_or_404(item_id)
    form = MaintenanceItemForm(obj=item)
    if form.validate_on_submit():
        if not form.km_interval.data and not form.date_interval_days.data:
            flash("Informe ao menos um intervalo (KM ou dias).", "danger")
        else:
            item.name = form.name.data
            item.km_interval = form.km_interval.data
            item.date_interval_days = form.date_interval_days.data
            item.notes = form.notes.data
            db.session.commit()
            flash("Item de manutenção atualizado.", "success")
            return redirect(url_for("maintenance.checklist", car_id=item.car_id))
    return render_template("maintenance/item_form.html", form=form, car=item.car, item=item)


@maintenance_bp.route("/itens/<int:item_id>/excluir", methods=["POST"])
@login_required
def delete_item(item_id):
    item = MaintenanceItem.query.get_or_404(item_id)
    car_id = item.car_id
    if item.logs:
        item.active = False
        flash("Item possui histórico de serviços — foi desativado em vez de excluído.", "info")
    else:
        db.session.delete(item)
        flash("Item de manutenção excluído.", "info")
    db.session.commit()
    return redirect(url_for("maintenance.checklist", car_id=car_id))


@maintenance_bp.route("/itens/<int:item_id>/registrar", methods=["POST"])
@login_required
def registrar_servico(item_id):
    item = MaintenanceItem.query.get_or_404(item_id)
    form = MaintenanceLogForm()
    if form.validate_on_submit():
        log = MaintenanceLog(
            maintenance_item_id=item.id,
            done_date=form.done_date.data,
            done_km=form.done_km.data,
            cost=form.cost.data,
            notes=form.notes.data,
            created_by_user_id=current_user.id,
        )
        db.session.add(log)
        item.last_done_date = form.done_date.data
        item.last_done_km = form.done_km.data
        db.session.commit()
        flash("Serviço registrado.", "success")
    else:
        flash("Não foi possível registrar o serviço — confira os dados.", "danger")
    return redirect(url_for("maintenance.checklist", car_id=item.car_id))


@maintenance_bp.route("/alertas")
@login_required
def alertas():
    hoje = date.today()
    linhas = []
    for car in Car.query.filter_by(active=True).all():
        for item in MaintenanceItem.query.filter_by(car_id=car.id, active=True).all():
            status = item.status_alerta(car.current_km, hoje)
            if status in ("atencao", "atrasado"):
                linhas.append((car, item, status))
    linhas.sort(key=lambda x: 0 if x[2] == "atrasado" else 1)
    return render_template("maintenance/alertas.html", linhas=linhas)
