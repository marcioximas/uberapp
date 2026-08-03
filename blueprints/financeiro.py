from datetime import datetime, date

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import db
from forms import (
    CSVUploadForm,
    ManualAssignForm,
    RecurringItemForm,
    AdHocEntryForm,
    CashSettingsForm,
)
from models import (
    ExpectedCharge,
    Transaction,
    ImportBatch,
    Car,
    RentalAgreement,
    RecurringItem,
    RecurringOccurrence,
    AdHocEntry,
    CashSettings,
)
from importador import (
    importar_extrato,
    ImportadorError,
    gerar_cobrancas_esperadas,
    atualizar_status_cobrancas,
)
from contas_fixas import gerar_ocorrencias
from projecao import calcular_projecao, calcular_saldo_atual
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


@financeiro_bp.route("/cobrancas/<int:charge_id>/confirmar-manual", methods=["POST"])
@login_required
def confirmar_manual(charge_id):
    cobranca = ExpectedCharge.query.get_or_404(charge_id)
    cobranca.manually_confirmed = True
    cobranca.confirmed_by_user_id = current_user.id
    cobranca.confirmed_at = datetime.utcnow()
    cobranca.status = "matched"
    db.session.commit()
    flash("Cobrança confirmada manualmente como recebida.", "success")
    return redirect(request.referrer or url_for("financeiro.conciliacao"))


@financeiro_bp.route("/cobrancas/<int:charge_id>/desfazer-confirmacao", methods=["POST"])
@login_required
def desfazer_confirmacao(charge_id):
    cobranca = ExpectedCharge.query.get_or_404(charge_id)
    if not cobranca.manually_confirmed:
        flash("Esta cobrança foi conciliada pelo extrato — não é possível desfazer por aqui.", "danger")
        return redirect(request.referrer or url_for("financeiro.conciliacao"))
    cobranca.manually_confirmed = False
    cobranca.confirmed_by_user_id = None
    cobranca.confirmed_at = None
    cobranca.recompute_status()
    db.session.commit()
    flash("Confirmação manual desfeita.", "info")
    return redirect(request.referrer or url_for("financeiro.conciliacao"))


@financeiro_bp.route("/mes-a-mes")
@login_required
def mes_a_mes():
    hoje = date.today()
    ano = request.args.get("ano", type=int) or hoje.year
    mes = request.args.get("mes", type=int) or hoje.month

    if mes < 1:
        mes = 12
        ano -= 1
    elif mes > 12:
        mes = 1
        ano += 1

    inicio_mes = date(ano, mes, 1)
    fim_mes = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)

    gerar_cobrancas_esperadas(until_date=max(fim_mes, hoje))
    gerar_ocorrencias(until_date=max(fim_mes, hoje))
    atualizar_status_cobrancas()

    cars = Car.query.filter_by(active=True).order_by(Car.plate).all()
    dados_por_carro = []
    for car in cars:
        cobrancas = (
            ExpectedCharge.query.join(RentalAgreement)
            .filter(
                RentalAgreement.car_id == car.id,
                ExpectedCharge.due_date >= inicio_mes,
                ExpectedCharge.due_date < fim_mes,
            )
            .all()
        )
        ocorrencias = (
            RecurringOccurrence.query.join(RecurringItem)
            .filter(
                RecurringItem.car_id == car.id,
                RecurringOccurrence.due_date >= inicio_mes,
                RecurringOccurrence.due_date < fim_mes,
            )
            .all()
        )
        avulsos = AdHocEntry.query.filter(
            AdHocEntry.car_id == car.id,
            AdHocEntry.entry_date >= inicio_mes,
            AdHocEntry.entry_date < fim_mes,
        ).all()

        if cobrancas or ocorrencias or avulsos or car.recurring_items:
            dados_por_carro.append(
                {"car": car, "cobrancas": cobrancas, "ocorrencias": ocorrencias, "avulsos": avulsos}
            )

    avulso_form = AdHocEntryForm()
    avulso_form.car_id.choices = [(c.id, c.plate) for c in cars]

    mes_anterior = (ano, mes - 1) if mes > 1 else (ano - 1, 12)
    mes_seguinte = (ano, mes + 1) if mes < 12 else (ano + 1, 1)

    return render_template(
        "financeiro/mes_a_mes.html",
        ano=ano,
        mes=mes,
        dados_por_carro=dados_por_carro,
        avulso_form=avulso_form,
        mes_anterior=mes_anterior,
        mes_seguinte=mes_seguinte,
    )


@financeiro_bp.route("/ocorrencias/<int:occurrence_id>/confirmar", methods=["POST"])
@login_required
def confirmar_ocorrencia(occurrence_id):
    ocorrencia = RecurringOccurrence.query.get_or_404(occurrence_id)
    if ocorrencia.status == "paid":
        ocorrencia.status = "pending"
        ocorrencia.paid_date = None
        flash("Ocorrência marcada como pendente novamente.", "info")
    else:
        ocorrencia.status = "paid"
        ocorrencia.paid_date = date.today()
        flash("Ocorrência confirmada.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("financeiro.mes_a_mes"))


@financeiro_bp.route("/ocorrencias/<int:occurrence_id>/valor", methods=["POST"])
@login_required
def editar_valor_ocorrencia(occurrence_id):
    ocorrencia = RecurringOccurrence.query.get_or_404(occurrence_id)
    novo_valor = request.form.get("amount", type=float)
    if novo_valor is None or novo_valor < 0:
        flash("Valor inválido.", "danger")
    else:
        ocorrencia.amount = novo_valor
        db.session.commit()
        flash("Valor atualizado.", "success")
    return redirect(request.referrer or url_for("financeiro.mes_a_mes"))


@financeiro_bp.route("/contas-fixas/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def edit_recurring_item(item_id):
    item = RecurringItem.query.get_or_404(item_id)
    form = RecurringItemForm(obj=item)
    if form.validate_on_submit():
        item.name = form.name.data
        item.amount = form.amount.data
        item.type = form.type.data
        item.frequency = form.frequency.data
        item.weekday = (
            int(form.weekday.data) if form.frequency.data == "weekly" and form.weekday.data else None
        )
        item.day_of_month = form.day_of_month.data if form.frequency.data == "monthly" else None
        item.start_date = form.start_date.data
        item.notes = form.notes.data
        db.session.commit()
        flash("Conta fixa atualizada.", "success")
        return redirect(url_for("cars.detail", car_id=item.car_id))
    return render_template("financeiro/contas_fixas_form.html", form=form, car=item.car, item=item)


@financeiro_bp.route("/contas-fixas/<int:item_id>/excluir", methods=["POST"])
@login_required
def delete_recurring_item(item_id):
    item = RecurringItem.query.get_or_404(item_id)
    car_id = item.car_id
    if item.occurrences:
        item.active = False
        flash("Conta fixa possui histórico de ocorrências — foi desativada em vez de excluída.", "info")
    else:
        db.session.delete(item)
        flash("Conta fixa excluída.", "info")
    db.session.commit()
    return redirect(url_for("cars.detail", car_id=car_id))


@financeiro_bp.route("/avulsos/novo", methods=["GET", "POST"])
@login_required
def novo_avulso():
    form = AdHocEntryForm()
    form.car_id.choices = [
        (c.id, c.plate) for c in Car.query.filter_by(active=True).order_by(Car.plate).all()
    ]
    if form.validate_on_submit():
        entry = AdHocEntry(
            car_id=form.car_id.data,
            type=form.type.data,
            description=form.description.data,
            amount=form.amount.data,
            entry_date=form.entry_date.data,
            created_by_user_id=current_user.id,
        )
        db.session.add(entry)
        db.session.commit()
        flash("Lançamento avulso registrado.", "success")
        return redirect(url_for("financeiro.mes_a_mes", ano=entry.entry_date.year, mes=entry.entry_date.month))
    return render_template("financeiro/avulso_form.html", form=form)


@financeiro_bp.route("/projecao")
@login_required
def projecao():
    meses = request.args.get("meses", type=int) or 6
    if meses not in (6, 12, 24):
        meses = 6
    saldo_atual, linhas = calcular_projecao(meses=meses)
    return render_template("financeiro/projecao.html", saldo_atual=saldo_atual, linhas=linhas, meses=meses)


@financeiro_bp.route("/configuracoes", methods=["GET", "POST"])
@login_required
def configuracoes():
    settings = CashSettings.get()
    form = CashSettingsForm(obj=settings)
    if form.validate_on_submit():
        settings.saldo_inicial = form.saldo_inicial.data
        settings.saldo_data = form.saldo_data.data
        db.session.commit()
        flash("Configurações salvas.", "success")
        return redirect(url_for("dashboard.index"))
    return render_template("financeiro/configuracoes.html", form=form)


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
