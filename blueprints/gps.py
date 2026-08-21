import os

from flask import Blueprint, render_template, redirect, url_for, flash, current_app, request, send_from_directory
from flask_login import login_required, current_user

from extensions import db
from forms import GPSUploadForm, GPSReviewForm, GPSTextReportForm
from models import Car, GPSReading
from gps_reader import validar_e_salvar_imagem, extrair_dados, GPSReaderError
from relatorio_gps import _normalizar_placa
from backfill_historico_gps_texto import parsear_relatorios_texto, aplicar_relatorio

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


def _relatorio_bate_com_carro(dados, car):
    """Confere se o carro identificado no relatório colado (por placa ou,
    na falta dela, pelo apelido/modelo) é o mesmo carro da página onde o
    relatório está sendo aplicado."""
    placa_norm = _normalizar_placa(dados.get("placa"))
    if placa_norm and placa_norm == _normalizar_placa(car.plate):
        return True

    modelo_norm = (car.model or "").replace(" ", "").upper()
    apelido_norm = (dados.get("apelido") or "").replace(" ", "").upper()
    return bool(modelo_norm and apelido_norm and (modelo_norm in apelido_norm or apelido_norm in modelo_norm))


@gps_bp.route("/relatorio-texto/<int:car_id>", methods=["GET", "POST"])
@login_required
def relatorio_texto(car_id):
    car = Car.query.get_or_404(car_id)
    form = GPSTextReportForm()
    preview = None

    if form.validate_on_submit():
        relatorios = parsear_relatorios_texto(form.texto.data)
        if not relatorios:
            flash("Não consegui interpretar esse relatório colado. Confira o texto e tente de novo.", "danger")
        else:
            dados = relatorios[0]
            if not _relatorio_bate_com_carro(dados, car):
                flash(
                    f"Esse relatório parece ser do carro placa {dados.get('placa')}, "
                    f"não de {car.plate}. Confira antes de aplicar.",
                    "danger",
                )
            else:
                preview = {
                    "periodo_inicio": dados["periodo_inicio"],
                    "periodo_fim": dados["periodo_fim"],
                    "km_rodados": dados["km_rodados"],
                    "km_atual_novo": (car.current_km or 0) + dados["km_rodados"],
                    "leituras_deslocadas": GPSReading.query.filter(
                        GPSReading.car_id == car.id, GPSReading.confirmed_km.isnot(None)
                    ).count(),
                }

    return render_template(
        "gps/relatorio_texto.html", form=form, car=car, preview=preview, texto=form.texto.data
    )


@gps_bp.route("/relatorio-texto/<int:car_id>/aplicar", methods=["POST"])
@login_required
def relatorio_texto_aplicar(car_id):
    car = Car.query.get_or_404(car_id)
    texto = request.form.get("texto", "")

    relatorios = parsear_relatorios_texto(texto)
    if not relatorios:
        flash("Não consegui interpretar esse relatório colado.", "danger")
        return redirect(url_for("gps.relatorio_texto", car_id=car.id))

    dados = relatorios[0]
    if not _relatorio_bate_com_carro(dados, car):
        flash(
            f"Esse relatório parece ser do carro placa {dados.get('placa')}, não de {car.plate}.",
            "danger",
        )
        return redirect(url_for("gps.relatorio_texto", car_id=car.id))

    try:
        km_aplicado = aplicar_relatorio(car, dados)
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("gps.relatorio_texto", car_id=car.id))

    flash(
        f"Relatório aplicado: +{km_aplicado:.2f} km. KM atual de {car.plate} agora é {car.current_km:.2f}.",
        "success",
    )
    return redirect(url_for("cars.detail", car_id=car.id))


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
