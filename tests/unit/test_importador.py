import io
from datetime import date
from decimal import Decimal

import pytest

from importador import (
    parse_itau_csv,
    ImportadorError,
    importar_extrato,
    gerar_cobrancas_esperadas,
    conciliar_transacoes,
)
from models import Car, Driver, RentalAgreement, ExpectedCharge, Transaction


CSV_TIPICO = (
    "Extrato de conta corrente;;\n"
    "Periodo: 01/07/2026 a 03/08/2026;;\n"
    ";;\n"
    "Data;Lançamento;Valor\n"
    "08/07/2026;PIX RECEBIDO JOAO MOTORISTA;400,00\n"
    "20/07/2026;TARIFA PACOTE DE SERVICOS;-15,90\n"
).encode("utf-8-sig")


def test_parse_itau_csv_skips_preamble_and_parses_br_number_format():
    linhas, ignoradas = parse_itau_csv(io.BytesIO(CSV_TIPICO))
    assert ignoradas == 0
    assert len(linhas) == 2
    assert linhas[0]["date"] == date(2026, 7, 8)
    assert linhas[0]["amount"] == Decimal("400.00")
    assert linhas[1]["amount"] == Decimal("-15.90")


def test_parse_itau_csv_raises_on_empty_file():
    with pytest.raises(ImportadorError):
        parse_itau_csv(io.BytesIO(b""))


def test_parse_itau_csv_raises_when_no_header_found():
    garbage = "isso;nao;e um extrato\nnem;isso;tampouco\n".encode("utf-8")
    with pytest.raises(ImportadorError):
        parse_itau_csv(io.BytesIO(garbage))


def test_parse_itau_csv_skips_invalid_rows_without_aborting():
    csv_com_linha_ruim = (
        "Data;Lançamento;Valor\n"
        "08/07/2026;PIX RECEBIDO;400,00\n"
        "data-invalida;LINHA QUEBRADA;abc\n"
    ).encode("utf-8")
    linhas, ignoradas = parse_itau_csv(io.BytesIO(csv_com_linha_ruim))
    assert len(linhas) == 1
    assert ignoradas == 1


@pytest.fixture()
def agreement_semanal(db):
    car = Car(plate="ABC1D23", model="Onix", year=2022)
    driver = Driver(name="João Motorista", phone="5511999998888")
    db.session.add_all([car, driver])
    db.session.commit()
    agreement = RentalAgreement(
        car_id=car.id,
        driver_id=driver.id,
        amount=400,
        frequency="weekly",
        weekday=0,
        start_date=date(2026, 7, 1),
    )
    db.session.add(agreement)
    db.session.commit()
    return agreement


def test_conciliar_transacoes_prefers_nearest_due_date_when_windows_overlap(db, agreement_semanal):
    """Regressão: tolerância (5 dias) > metade do intervalo semanal (7 dias) faz duas
    cobranças ficarem candidatas; o matching deve escolher a mais próxima em vez de
    deixar tudo como ambíguo."""
    gerar_cobrancas_esperadas(until_date=date(2026, 7, 31))

    from models import ImportBatch

    batch = ImportBatch(filename="teste.csv", row_count=1)
    db.session.add(batch)
    db.session.flush()
    # devido em 06/07 e 13/07; esta transação está a 2 dias do primeiro e a 5 do segundo
    transacao = Transaction(
        import_batch_id=batch.id,
        transaction_date=date(2026, 7, 8),
        description="PIX",
        amount=400,
    )
    db.session.add(transacao)
    db.session.commit()

    conciliar_transacoes(batch_id=batch.id)

    db.session.refresh(transacao)
    assert transacao.status == "matched"
    assert transacao.matched_by == "auto"
    cobranca = ExpectedCharge.query.get(transacao.matched_expected_charge_id)
    assert cobranca.due_date == date(2026, 7, 6)


def test_conciliar_transacoes_leaves_unmatched_when_no_amount_candidate(db, agreement_semanal):
    gerar_cobrancas_esperadas(until_date=date(2026, 7, 31))
    from models import ImportBatch

    batch = ImportBatch(filename="teste.csv", row_count=1)
    db.session.add(batch)
    db.session.flush()
    transacao = Transaction(
        import_batch_id=batch.id,
        transaction_date=date(2026, 7, 8),
        description="PIX de outra coisa",
        amount=250,
    )
    db.session.add(transacao)
    db.session.commit()

    conciliar_transacoes(batch_id=batch.id)

    db.session.refresh(transacao)
    assert transacao.status == "unmatched"


def test_importar_extrato_creates_batch_and_transactions(db, admin_user, agreement_semanal):
    batch = importar_extrato(io.BytesIO(CSV_TIPICO), "extrato.csv", admin_user.id)
    assert batch.row_count == 2
    assert batch.skipped_row_count == 0
    transacoes = Transaction.query.filter_by(import_batch_id=batch.id).all()
    assert len(transacoes) == 2
    # a transação positiva de 400 deve ter conciliado automaticamente com o aluguel
    positiva = next(t for t in transacoes if t.amount > 0)
    assert positiva.status == "matched"
