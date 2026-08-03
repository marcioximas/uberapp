from datetime import date

import pytest

import projecao as projecao_module
from projecao import calcular_saldo_atual, calcular_projecao
from models import (
    CashSettings,
    Car,
    Driver,
    RentalAgreement,
    ExpectedCharge,
    RecurringItem,
    RecurringOccurrence,
    AdHocEntry,
)


@pytest.fixture()
def frozen_today(monkeypatch):
    """Congela `date.today()` dentro do módulo projecao para tornar os testes determinísticos."""
    fixo = date(2026, 8, 3)

    class _DataFixa(date):
        @classmethod
        def today(cls):
            return fixo

    monkeypatch.setattr(projecao_module, "date", _DataFixa)
    return fixo


def test_calcular_saldo_atual_soma_confirmados_no_periodo(db, frozen_today):
    car = Car(plate="ABC1D23", model="Onix")
    driver = Driver(name="João")
    db.session.add_all([car, driver])
    db.session.commit()

    agreement = RentalAgreement(
        car_id=car.id, driver_id=driver.id, amount=400, frequency="weekly",
        weekday=0, start_date=date(2026, 7, 1),
    )
    db.session.add(agreement)
    db.session.commit()

    cobranca_confirmada = ExpectedCharge(
        rental_agreement_id=agreement.id, due_date=date(2026, 7, 6),
        amount_expected=400, status="matched",
    )
    item = RecurringItem(
        car_id=car.id, name="Prestação", amount=650, type="expense",
        frequency="monthly", day_of_month=15, start_date=date(2026, 7, 1),
    )
    db.session.add_all([cobranca_confirmada, item])
    db.session.commit()

    ocorrencia_paga = RecurringOccurrence(
        recurring_item_id=item.id, due_date=date(2026, 7, 15), amount=650,
        status="paid", paid_date=date(2026, 7, 15),
    )
    avulso = AdHocEntry(
        car_id=car.id, type="expense", description="Troca de pneu",
        amount=300, entry_date=date(2026, 8, 2),
    )
    db.session.add_all([ocorrencia_paga, avulso])
    db.session.add(CashSettings(id=1, saldo_inicial=1000, saldo_data=date(2026, 7, 1)))
    db.session.commit()

    saldo = calcular_saldo_atual()
    assert saldo == 1000 + 400 - 650 - 300


def test_projecao_inclui_cobranca_vencida_hoje_ainda_nao_confirmada(db, frozen_today):
    """Regressão: uma cobrança com vencimento exatamente hoje e ainda pendente não pode
    desaparecer da projeção (não está em saldo_atual porque não foi confirmada, e não
    deve ficar de fora do mês corrente por causa de um filtro due_date > hoje)."""
    car = Car(plate="ABC1D23", model="Onix")
    driver = Driver(name="João")
    db.session.add_all([car, driver])
    db.session.commit()

    agreement = RentalAgreement(
        car_id=car.id, driver_id=driver.id, amount=400, frequency="weekly",
        weekday=0, start_date=date(2026, 7, 1), reliability_pct=100,
    )
    db.session.add(agreement)
    db.session.add(CashSettings(id=1, saldo_inicial=0, saldo_data=date(2026, 7, 1)))
    db.session.commit()

    saldo_atual, linhas = calcular_projecao(meses=1)

    mes_atual = linhas[0]
    assert mes_atual["ano"] == 2026 and mes_atual["mes"] == 8
    cobranca_hoje = ExpectedCharge.query.filter_by(due_date=date(2026, 8, 3)).first()
    assert cobranca_hoje is not None
    assert mes_atual["receita"] >= 400


def test_projecao_pondera_receita_pela_confiabilidade(db, frozen_today):
    car = Car(plate="ABC1D23", model="Onix")
    driver = Driver(name="João")
    db.session.add_all([car, driver])
    db.session.commit()
    agreement = RentalAgreement(
        car_id=car.id, driver_id=driver.id, amount=1000, frequency="monthly",
        day_of_month=20, start_date=date(2026, 8, 1), reliability_pct=50,
    )
    db.session.add(agreement)
    db.session.add(CashSettings(id=1, saldo_inicial=0, saldo_data=date(2026, 8, 1)))
    db.session.commit()

    _, linhas = calcular_projecao(meses=1)

    assert linhas[0]["receita"] == 500  # 1000 * 50%


def test_projecao_alerta_quando_saldo_fica_negativo(db, frozen_today):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.commit()
    item = RecurringItem(
        car_id=car.id, name="Prestação alta", amount=5000, type="expense",
        frequency="monthly", day_of_month=10, start_date=date(2026, 8, 1),
    )
    db.session.add(item)
    db.session.add(CashSettings(id=1, saldo_inicial=100, saldo_data=date(2026, 8, 1)))
    db.session.commit()

    _, linhas = calcular_projecao(meses=2)

    assert linhas[0]["alerta"] is True
    assert linhas[0]["saldo_final"] < 0


def test_avulsos_nao_entram_na_projecao(db, frozen_today):
    car = Car(plate="ABC1D23", model="Onix")
    db.session.add(car)
    db.session.add(CashSettings(id=1, saldo_inicial=1000, saldo_data=date(2026, 8, 1)))
    db.session.commit()
    avulso = AdHocEntry(
        car_id=car.id, type="expense", description="Multa", amount=999999,
        entry_date=date(2026, 8, 20),
    )
    db.session.add(avulso)
    db.session.commit()

    _, linhas = calcular_projecao(meses=1)

    # Um avulso gigante não deve derrubar o saldo projetado
    assert linhas[0]["saldo_final"] == 1000
