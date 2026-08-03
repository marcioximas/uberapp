from datetime import date

from recorrencia import gerar_datas_vencimento


def test_weekly_generates_correct_weekdays():
    # 2026-07-01 é uma quarta-feira; weekday=0 pede segunda-feira
    datas = list(
        gerar_datas_vencimento(
            start_date=date(2026, 7, 1),
            frequency="weekly",
            weekday=0,
            day_of_month=None,
            until_date=date(2026, 7, 31),
        )
    )
    assert datas == [date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20), date(2026, 7, 27)]
    assert all(d.weekday() == 0 for d in datas)


def test_monthly_generates_correct_day():
    datas = list(
        gerar_datas_vencimento(
            start_date=date(2026, 1, 15),
            frequency="monthly",
            weekday=None,
            day_of_month=15,
            until_date=date(2026, 4, 30),
        )
    )
    assert datas == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15), date(2026, 4, 15)]


def test_monthly_skips_months_without_that_day():
    # Dia 31 não existe em fevereiro/abril — deve pular esses meses sem quebrar
    datas = list(
        gerar_datas_vencimento(
            start_date=date(2026, 1, 31),
            frequency="monthly",
            weekday=None,
            day_of_month=31,
            until_date=date(2026, 4, 30),
        )
    )
    assert datas == [date(2026, 1, 31), date(2026, 3, 31)]


def test_no_dates_when_start_after_until():
    datas = list(
        gerar_datas_vencimento(
            start_date=date(2026, 8, 1),
            frequency="weekly",
            weekday=0,
            day_of_month=None,
            until_date=date(2026, 7, 1),
        )
    )
    assert datas == []


def test_weekly_defaults_to_start_date_weekday_when_none_given():
    # 2026-07-01 é quarta-feira (weekday 2); sem weekday explícito, usa o da start_date
    datas = list(
        gerar_datas_vencimento(
            start_date=date(2026, 7, 1),
            frequency="weekly",
            weekday=None,
            day_of_month=None,
            until_date=date(2026, 7, 8),
        )
    )
    assert datas == [date(2026, 7, 1), date(2026, 7, 8)]
