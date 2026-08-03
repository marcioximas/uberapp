import os

from flask import Blueprint, render_template, redirect, url_for, flash, current_app, send_from_directory
from flask_login import login_required, current_user

from extensions import db
from forms import GPSUploadForm, GPSReviewForm
from models import Car, GPSReading
from gps_reader import validar_e_salvar_imagem, extrair_dados, GPSReaderError

gps_bp = Blueprint("gps", __name__, url_prefix="/manutencao/gps")


@gps_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    form = GPSUploadForm()
    form.car_id.choices = [
        (c.id, c.plate) for c in Car.query.filter_by(active=True).order_by(Car.plate).all()
    ]

    if form.validate_on_submit():
        try:
            nome_arquivo = validar_e_salvar_imagem(form.image.data, current_app.config["UPLOAD_FOLDER"])
        except GPSReaderError as e:
            flash(str(e), "danger")
            return render_template("gps/upload.html", form=form)

        caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], "gps", nome_arquivo)
        dados = extrair_dados(caminho)

        leitura = GPSReading(
            car_id=form.car_id.data,
            image_filename=nome_arquivo,
            extracted_km=dados["extracted_km"],
            extracted_max_speed=dados["extracted_max_speed"],
            extracted_moving_time_minutes=dados["extracted_moving_time_minutes"],
            raw_ai_response=dados["raw_ai_response"],
            confidence_note=dados["confidence_note"],
        )
        db.session.add(leitura)
        db.session.commit()
        return redirect(url_for("gps.revisar", reading_id=leitura.id))

    return render_template("gps/upload.html", form=form)


@gps_bp.route("/<int:reading_id>/revisar", methods=["GET", "POST"])
@login_required
def revisar(reading_id):
    leitura = GPSReading.query.get_or_404(reading_id)
    if leitura.status != "pending_review":
        flash("Esta leitura já foi revisada.", "info")
        return redirect(url_for("gps.historico"))

    form = GPSReviewForm(
        confirmed_km=leitura.extracted_km,
        confirmed_max_speed=leitura.extracted_max_speed,
        confirmed_moving_time_minutes=leitura.extracted_moving_time_minutes,
    )

    if form.validate_on_submit():
        leitura.confirmed_km = form.confirmed_km.data
        leitura.confirmed_max_speed = form.confirmed_max_speed.data
        leitura.confirmed_moving_time_minutes = form.confirmed_moving_time_minutes.data
        leitura.reading_date = form.reading_date.data
        leitura.status = "confirmed"
        leitura.reviewed_by_user_id = current_user.id

        if form.confirmed_km.data > leitura.car.current_km:
            leitura.car.current_km = form.confirmed_km.data
            flash("Leitura confirmada e KM do carro atualizado.", "success")
        else:
            flash(
                f"Leitura confirmada, mas o KM informado ({form.confirmed_km.data}) não é maior "
                f"que o KM atual do carro ({leitura.car.current_km}) — o KM do carro NÃO foi alterado.",
                "warning",
            )

        db.session.commit()
        return redirect(url_for("gps.historico"))

    return render_template("gps/revisar.html", leitura=leitura, form=form)


@gps_bp.route("/<int:reading_id>/rejeitar", methods=["POST"])
@login_required
def rejeitar(reading_id):
    leitura = GPSReading.query.get_or_404(reading_id)
    leitura.status = "rejected"
    leitura.reviewed_by_user_id = current_user.id
    db.session.commit()
    flash("Leitura descartada.", "info")
    return redirect(url_for("gps.historico"))


@gps_bp.route("/historico")
@login_required
def historico():
    leituras = GPSReading.query.order_by(GPSReading.created_at.desc()).limit(50).all()
    return render_template("gps/historico.html", leituras=leituras)


@gps_bp.route("/imagem/<path:filename>")
@login_required
def imagem(filename):
    pasta = os.path.join(current_app.config["UPLOAD_FOLDER"], "gps")
    return send_from_directory(pasta, filename)
