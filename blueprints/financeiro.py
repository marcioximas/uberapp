from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import db
from forms import CSVUploadForm, ManualAssignForm
from models import ExpectedCharge, Transaction, ImportBatch
from importador import (
    importar_extrato,
    ImportadorError,
    gerar_cobrancas_esperadas,
    atualizar_status_cobrancas,
)
from whatsapp import enviar_cobranca, WhatsAppError

financeiro_bp = Blueprint("financeiro", __name__, url_prefix="/financeiro")


@financeiro_bp.route("/importar", methods=["GET", "POST"])
@login_required
def importar():
    form = CSVUploadForm()
    if form.validate_on_submit():
        try:
            batch = importar_extrato(form.file.data.stream, form.file.data.filename, current_user.id)
        except ImportadorError as e:
            flash(str(e), "danger")
            return render_template("financeiro/upload.html", form=form)

        msg = f"Importação concluída: {batch.row_count} linhas importadas."
        if batch.skipped_row_count:
            msg += f" {batch.skipped_row_count} linha(s) ignorada(s) por formato inválido."
        flash(msg, "success")
        return redirect(url_for("financeiro.conciliacao"))

    return render_template("financeiro/upload.html", form=form)


@financeiro_bp.route("/conciliacao")
@login_required
def conciliacao():
    gerar_cobrancas_esperadas()
    atualizar_status_cobrancas()

    status_filter = request.args.get("status")
    query = ExpectedCharge.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    cobrancas = query.order_by(ExpectedCharge.due_date.desc()).limit(200).all()

    transacoes_pendentes = (
        Transaction.query.filter_by(status="unmatched")
        .order_by(Transaction.transaction_date.desc())
        .all()
    )

    forms_atribuicao = {}
    for transacao in transacoes_pendentes:
        form = ManualAssignForm(prefix=f"t{transacao.id}")
        candidatas = (
            ExpectedCharge.query.filter(ExpectedCharge.status.in_(["pending", "late", "missing"]))
            .order_by(ExpectedCharge.due_date)
            .all()
        )
        form.expected_charge_id.choices = [
            (
                c.id,
                f"{c.agreement.car.plate} - {c.agreement.driver.name} - "
                f"R$ {c.amount_expected:.2f} - vence {c.due_date.strftime('%d/%m/%Y')}",
            )
            for c in candidatas
        ]
        forms_atribuicao[transacao.id] = form

    return render_template(
        "financeiro/conciliacao.html",
        cobrancas=cobrancas,
        transacoes_pendentes=transacoes_pendentes,
        forms_atribuicao=forms_atribuicao,
        status_filter=status_filter,
    )


@financeiro_bp.route("/transacoes/<int:transaction_id>/atribuir", methods=["POST"])
@login_required
def atribuir_transacao(transaction_id):
    transacao = Transaction.query.get_or_404(transaction_id)
    form = ManualAssignForm(prefix=f"t{transacao.id}")
    candidatas = ExpectedCharge.query.filter(
        ExpectedCharge.status.in_(["pending", "late", "missing"])
    ).all()
    form.expected_charge_id.choices = [(c.id, "") for c in candidatas]

    if form.validate_on_submit():
        cobranca = ExpectedCharge.query.get_or_404(form.expected_charge_id.data)
        transacao.status = "matched"
        transacao.matched_expected_charge_id = cobranca.id
        transacao.matched_car_id = cobranca.agreement.car_id
        transacao.matched_by = "manual"
        cobranca.status = "matched"
        db.session.commit()
        flash("Transação vinculada com sucesso.", "success")
    else:
        flash("Selecione uma cobrança válida.", "danger")

    return redirect(url_for("financeiro.conciliacao"))


@financeiro_bp.route("/transacoes/<int:transaction_id>/ignorar", methods=["POST"])
@login_required
def ignorar_transacao(transaction_id):
    transacao = Transaction.query.get_or_404(transaction_id)
    transacao.status = "ignored"
    db.session.commit()
    flash("Transação marcada como ignorada.", "info")
    return redirect(url_for("financeiro.conciliacao"))


@financeiro_bp.route("/cobrancas/<int:charge_id>/notificar", methods=["POST"])
@login_required
def notificar_cobranca(charge_id):
    cobranca = ExpectedCharge.query.get_or_404(charge_id)
    try:
        enviar_cobranca(cobranca)
    except WhatsAppError as e:
        flash(f"Não foi possível enviar o WhatsApp: {e}", "danger")
    else:
        cobranca.notified_at = datetime.utcnow()
        cobranca.notified_count = (cobranca.notified_count or 0) + 1
        db.session.commit()
        flash(f"Cobrança enviada via WhatsApp para {cobranca.agreement.driver.name}.", "success")
    return redirect(url_for("financeiro.conciliacao"))


@financeiro_bp.route("/importacoes")
@login_required
def importacoes():
    batches = ImportBatch.query.order_by(ImportBatch.imported_at.desc()).all()
    return render_template("financeiro/importacoes.html", batches=batches)


@financeiro_bp.route("/importacoes/<int:batch_id>")
@login_required
def importacao_detalhe(batch_id):
    batch = ImportBatch.query.get_or_404(batch_id)
    transacoes = (
        Transaction.query.filter_by(import_batch_id=batch.id)
        .order_by(Transaction.transaction_date.desc())
        .all()
    )
    return render_template("financeiro/importacao_detalhe.html", batch=batch, transacoes=transacoes)
