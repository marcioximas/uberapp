"""Geração de datas de vencimento para itens recorrentes (aluguel fixo, contas fixas)."""

from datetime import date, timedelta


def gerar_datas_vencimento(start_date, frequency, weekday, day_of_month, until_date):
    """Gera as datas de vencimento (weekly/monthly) entre start_date e until_date, inclusive."""
    if start_date > until_date:
        return

    if frequency == "weekly":
        dia_semana = weekday if weekday is not None else start_date.weekday()
        dias_ate_weekday = (dia_semana - start_date.weekday()) % 7
        atual = start_date + timedelta(days=dias_ate_weekday)
        while atual <= until_date:
            yield atual
            atual += timedelta(days=7)
    elif frequency == "monthly":
        dia = day_of_month or start_date.day
        ano, mes = start_date.year, start_date.month
        while True:
            try:
                atual = date(ano, mes, dia)
            except ValueError:
                atual = None
            if atual and atual >= start_date:
                if atual > until_date:
                    break
                yield atual
            mes += 1
            if mes > 12:
                mes = 1
                ano += 1
            if date(ano, mes, 1) > until_date:
                break
