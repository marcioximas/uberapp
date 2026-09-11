from datetime import date

from models import Fine


def _fine(status="pending_review", extracted_valor=100, confirmed_valor=None,
          extracted_vencimento=None, confirmed_vencimento=None):
    return Fine(
        numero_ait="123",
        status=status,
        extracted_valor=extracted_valor,
        confirmed_valor=confirmed_valor,
        extracted_vencimento=extracted_vencimento,
        confirmed_vencimento=confirmed_vencimento,
    )


def test_status_display_vencida_when_overdue_and_unresolved():
    f = _fine(extracted_vencimento=date(2026, 1, 1))
    assert f.status_display(today=date(2026, 2, 1)) == "vencida"


def test_status_display_pending_review_when_not_overdue():
    f = _fine(extracted_vencimento=date(2026, 3, 1))
    assert f.status_display(today=date(2026, 2, 1)) == "pending_review"


def test_status_display_never_vencida_when_paga():
    f = _fine(status="paga", extracted_vencimento=date(2026, 1, 1))
    assert f.status_display(today=date(2026, 2, 1)) == "paga"


def test_status_display_never_vencida_when_recorrida():
    f = _fine(status="recorrida", extracted_vencimento=date(2026, 1, 1))
    assert f.status_display(today=date(2026, 2, 1)) == "recorrida"


def test_valor_prefers_confirmed_over_extracted():
    f = _fine(extracted_valor=100, confirmed_valor=80)
    assert f.valor == 80


def test_valor_falls_back_to_extracted():
    f = _fine(extracted_valor=100)
    assert f.valor == 100


def test_vencimento_prefers_confirmed_over_extracted():
    f = _fine(extracted_vencimento=date(2026, 1, 1), confirmed_vencimento=date(2026, 2, 1))
    assert f.vencimento == date(2026, 2, 1)
