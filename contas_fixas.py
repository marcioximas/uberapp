"""Geração de ocorrências de contas fixas por carro (RecurringItem -> RecurringOccurrence)."""

from datetime import date

from extensions import db
from models import RecurringItem, RecurringOccurrence
from recorrencia import gerar_datas_vencimento


def gerar_ocorrencias(until_date=None):
    """Gera RecurringOccurrence para todo RecurringItem ativo, até until_date (padrão: hoje)."""
    until_date = until_date or date.today()

    for item in RecurringItem.query.filter_by(active=True).all():
        fim = item.end_date or until_date
        fim = min(fim, until_date)
        datas = gerar_datas_vencimento(item.start_date, item.frequency, item.weekday, item.day_of_month, fim)
        for due_date in datas:
            existe = RecurringOccurrence.query.filter_by(
                recurring_item_id=item.id, due_date=due_date
            ).first()
            if not existe:
                db.session.add(
                    RecurringOccurrence(
                        recurring_item_id=item.id,
                        due_date=due_date,
                        amount=item.amount,
                    )
                )
    db.session.commit()
