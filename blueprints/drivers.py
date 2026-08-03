from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required

from extensions import db
from forms import DriverForm
from models import Driver

drivers_bp = Blueprint("drivers", __name__, url_prefix="/motoristas")


@drivers_bp.route("/")
@login_required
def list_drivers():
    drivers = Driver.query.order_by(Driver.name).all()
    return render_template("drivers/list.html", drivers=drivers)


@drivers_bp.route("/novo", methods=["GET", "POST"])
@login_required
def new_driver():
    form = DriverForm()
    if form.validate_on_submit():
        driver = Driver(name=form.name.data, phone=form.phone.data, document=form.document.data)
        db.session.add(driver)
        db.session.commit()
        flash("Motorista cadastrado com sucesso.", "success")
        return redirect(url_for("drivers.list_drivers"))
    return render_template("drivers/form.html", form=form, driver=None)


@drivers_bp.route("/<int:driver_id>/editar", methods=["GET", "POST"])
@login_required
def edit_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    form = DriverForm(obj=driver)
    if form.validate_on_submit():
        driver.name = form.name.data
        driver.phone = form.phone.data
        driver.document = form.document.data
        db.session.commit()
        flash("Motorista atualizado com sucesso.", "success")
        return redirect(url_for("drivers.list_drivers"))
    return render_template("drivers/form.html", form=form, driver=driver)


@drivers_bp.route("/<int:driver_id>/desativar", methods=["POST"])
@login_required
def deactivate_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    driver.active = False
    db.session.commit()
    flash(f"Motorista {driver.name} desativado.", "info")
    return redirect(url_for("drivers.list_drivers"))


@drivers_bp.route("/<int:driver_id>")
@login_required
def detail(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    return render_template("drivers/detail.html", driver=driver)
