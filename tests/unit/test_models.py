from datetime import date, timedelta

from models import ExpectedCharge, MaintenanceItem, Transaction


def _charge(due_date, transaction=None, manually_confirmed=False):
    c = ExpectedCharge(due_date=due_date, amount_expected=400, manually_confirmed=manually_confirmed)
    c.transaction = transaction
    return c


def test_recompute_status_pending_within_tolerance():
    hoje = date(2026, 8, 3)
    c = _charge(due_date=hoje - timedelta(days=2))
    c.recompute_status(today=hoje)
    assert c.status == "pending"


def test_recompute_status_late_after_tolerance():
    hoje = date(2026, 8, 3)
    c = _charge(due_date=hoje - timedelta(days=10))
    c.recompute_status(today=hoje)
    assert c.status == "late"


def test_recompute_status_missing_after_grace_period():
    hoje = date(2026, 8, 3)
    c = _charge(due_date=hoje - timedelta(days=40))
    c.recompute_status(today=hoje)
    assert c.status == "missing"


def test_recompute_status_matched_when_transaction_linked():
    hoje = date(2026, 8, 3)
    c = _charge(due_date=hoje - timedelta(days=40), transaction=Transaction())
    c.recompute_status(today=hoje)
    assert c.status == "matched"


def test_recompute_status_matched_when_manually_confirmed_even_if_overdue():
    # Regressão: confirmação manual (sem transação bancária) deve continuar "matched"
    # mesmo que a data de vencimento já esteja muito atrasada.
    hoje = date(2026, 8, 3)
    c = _charge(due_date=hoje - timedelta(days=40), manually_confirmed=True)
    c.recompute_status(today=hoje)
    assert c.status == "matched"


class _FakeCreatedAt:
    def date(self):
        return date(2026, 1, 1)


def _item(km_interval=None, date_interval_days=None, last_done_km=None, last_done_date=None):
    item = MaintenanceItem(
        name="Troca de óleo",
        km_interval=km_interval,
        date_interval_days=date_interval_days,
        last_done_km=last_done_km,
        last_done_date=last_done_date,
    )
    item.created_at = _FakeCreatedAt()
    return item


def test_status_alerta_ok_when_far_from_interval():
    item = _item(km_interval=10000, last_done_km=0)
    assert item.status_alerta(current_km=1000) == "ok"


def test_status_alerta_atencao_near_threshold():
    item = _item(km_interval=10000, last_done_km=0)
    assert item.status_alerta(current_km=9500) == "atencao"


def test_status_alerta_atrasado_past_interval():
    item = _item(km_interval=10000, last_done_km=0)
    assert item.status_alerta(current_km=15000) == "atrasado"


def test_status_alerta_worst_of_km_and_date():
    hoje = date(2026, 8, 3)
    # KM ainda ok, mas data já vencida há muito tempo -> pior caso vence (atrasado)
    item = _item(km_interval=10000, date_interval_days=30, last_done_km=0, last_done_date=date(2026, 1, 1))
    assert item.status_alerta(current_km=100, today=hoje) == "atrasado"


def test_status_alerta_ok_when_no_interval_configured():
    item = _item()
    assert item.status_alerta(current_km=999999) == "ok"
