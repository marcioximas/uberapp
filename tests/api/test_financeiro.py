import io
from datetime import date

from models import (
    Car,
    Driver,
    RentalAgreement,
    ExpectedCharge,
    Transaction,
    ImportBatch,
    RecurringItem,
    RecurringOccurrence,
    AdHocEntry,
    CashSettings,
)


def _criar_agreement(db, reliability_pct=100):
    car = Car(plate="ABC1D23", model="Onix")
    driver = Driver(name="João Motorista", phone="5511999998888")
    db.session.add_all([car, driver])
    db.session.commit()
    agreement = RentalAgreement(
        car_id=car.id, driver_id=driver.id, amount=400, frequency="weekly",
        weekday=0, start_date=date(2026, 7, 1), reliability_pct=reliability_pct,
    )
    db.session.add(agreement)
    db.session.commit()
    return car, driver, agreement


CSV_BYTES = (
    "Data;Lançamento;Valor\n"
    "08/07/2026;PIX RECEBIDO JOAO;400,00\n"
).encode("utf-8")


def test_upload_csv_imports_and_reconciles(auth_client, db):
    _criar_agreement(db)

    resp = auth_client.post(
        "/financeiro/importar",
        data={"file": (io.BytesIO(CSV_BYTES), "extrato.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    batch = ImportBatch.query.first()
    assert batch is not None
    assert batch.row_count == 1
    transacao = Transaction.query.first()
    assert transacao.status == "matched"


def test_conciliacao_lists_charges_and_status_filter(auth_client, db):
    _criar_agreement(db)
    auth_client.get("/financeiro/conciliacao")  # gera as cobranças

    resp = auth_client.get("/financeiro/conciliacao?status=late")
    assert resp.status_code == 200
    for c in ExpectedCharge.query.filter_by(status="late").all():
        assert c.due_date.strftime("%d/%m/%Y").encode() in resp.data


def test_atribuir_transacao_manual(auth_client, db):
    car, driver, agreement = _criar_agreement(db)
    auth_client.get("/financeiro/conciliacao")  # gera as cobranças

    batch = ImportBatch(filename="teste.csv", row_count=1)
    db.session.add(batch)
    db.session.flush()
    transacao = Transaction(
        import_batch_id=batch.id, transaction_date=date(2026, 7, 8),
        description="valor divergente", amount=390,
    )
    db.session.add(transacao)
    db.session.commit()

    cobranca = ExpectedCharge.query.filter_by(rental_agreement_id=agreement.id).order_by(
        ExpectedCharge.due_date
    ).first()

    resp = auth_client.post(
        f"/financeiro/transacoes/{transacao.id}/atribuir",
        data={f"t{transacao.id}-expected_charge_id": str(cobranca.id)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(transacao)
    assert transacao.status == "matched"
    assert transacao.matched_by == "manual"


def test_ignorar_transacao(auth_client, db):
    batch = ImportBatch(filename="teste.csv", row_count=1)
    db.session.add(batch)
    db.session.flush()
    transacao = Transaction(
        import_batch_id=batch.id, transaction_date=date(2026, 7, 8),
        description="tarifa", amount=-15.9,
    )
    db.session.add(transacao)
    db.session.commit()

    auth_client.post(f"/financeiro/transacoes/{transacao.id}/ignorar", follow_redirects=True)
    db.session.refresh(transacao)
    assert transacao.status == "ignored"


def test_confirmar_manual_e_desfazer(auth_client, db):
    car, driver, agreement = _criar_agreement(db)
    auth_client.get("/financeiro/conciliacao")
    cobranca = ExpectedCharge.query.filter_by(rental_agreement_id=agreement.id).first()

    auth_client.post(f"/financeiro/cobrancas/{cobranca.id}/confirmar-manual", follow_redirects=True)
    db.session.refresh(cobranca)
    assert cobranca.status == "matched"
    assert cobranca.manually_confirmed is True

    auth_client.post(f"/financeiro/cobrancas/{cobranca.id}/desfazer-confirmacao", follow_redirects=True)
    db.session.refresh(cobranca)
    assert cobranca.manually_confirmed is False
    assert cobranca.status != "matched"


def test_notificar_cobranca_sem_config_falha_graciosamente(auth_client, db):
    car, driver, agreement = _criar_agreement(db)
    auth_client.get("/financeiro/conciliacao")
    cobranca = ExpectedCharge.query.filter_by(rental_agreement_id=agreement.id).first()

    resp = auth_client.post(
        f"/financeiro/cobrancas/{cobranca.id}/notificar", follow_redirects=True
    )
    assert resp.status_code == 200
    assert "Não foi possível enviar o WhatsApp".encode() in resp.data


def test_mes_a_mes_shows_rent_and_recurring_item(auth_client, db):
    car, driver, agreement = _criar_agreement(db)
    item = RecurringItem(
        car_id=car.id, name="Prestação financiamento", amount=650, type="expense",
        frequency="monthly", day_of_month=15, start_date=date(2026, 7, 1),
    )
    db.session.add(item)
    db.session.commit()

    resp = auth_client.get("/financeiro/mes-a-mes?ano=2026&mes=7")
    assert resp.status_code == 200
    assert b"Jo\xc3\xa3o Motorista" in resp.data
    assert "Prestação financiamento".encode() in resp.data


def test_confirmar_ocorrencia_toggle(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    item = RecurringItem(
        car_id=car.id, name="Seguro", amount=200, type="expense",
        frequency="monthly", day_of_month=1, start_date=date(2026, 7, 1),
    )
    db.session.add(item)
    db.session.commit()
    ocorrencia = RecurringOccurrence(recurring_item_id=item.id, due_date=date(2026, 7, 1), amount=200)
    db.session.add(ocorrencia)
    db.session.commit()

    auth_client.post(f"/financeiro/ocorrencias/{ocorrencia.id}/confirmar", follow_redirects=True)
    db.session.refresh(ocorrencia)
    assert ocorrencia.status == "paid"

    auth_client.post(f"/financeiro/ocorrencias/{ocorrencia.id}/confirmar", follow_redirects=True)
    db.session.refresh(ocorrencia)
    assert ocorrencia.status == "pending"


def test_editar_valor_ocorrencia(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    item = RecurringItem(
        car_id=car.id, name="Seguro", amount=200, type="expense",
        frequency="monthly", day_of_month=1, start_date=date(2026, 7, 1),
    )
    db.session.add(item)
    db.session.commit()
    ocorrencia = RecurringOccurrence(recurring_item_id=item.id, due_date=date(2026, 7, 1), amount=200)
    db.session.add(ocorrencia)
    db.session.commit()

    auth_client.post(
        f"/financeiro/ocorrencias/{ocorrencia.id}/valor",
        data={"amount": "250.00"},
        follow_redirects=True,
    )
    db.session.refresh(ocorrencia)
    assert float(ocorrencia.amount) == 250.00


def test_novo_avulso(auth_client, db):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()

    auth_client.post(
        "/financeiro/avulsos/novo",
        data={
            "car_id": str(car.id), "type": "expense", "description": "Troca de pneu",
            "amount": "300.00", "entry_date": "2026-08-02",
        },
        follow_redirects=True,
    )
    avulso = AdHocEntry.query.filter_by(car_id=car.id).first()
    assert avulso is not None
    assert avulso.description == "Troca de pneu"


def test_projecao_view_renders(auth_client, db):
    _criar_agreement(db)
    resp = auth_client.get("/financeiro/projecao?meses=6")
    assert resp.status_code == 200
    assert "Projeção de fluxo de caixa".encode() in resp.data


def test_configuracoes_saves_cash_settings(auth_client, db):
    resp = auth_client.post(
        "/financeiro/configuracoes",
        data={"saldo_inicial": "1000.00", "saldo_data": "2026-07-01"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    settings = CashSettings.get()
    assert float(settings.saldo_inicial) == 1000.00
