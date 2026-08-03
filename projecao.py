"""Saldo de caixa atual e projeção de fluxo de caixa (mensal, N meses à frente).

A projeção soma só os valores fixos (aluguel esperado + contas fixas por carro,
ambos já materializados como ExpectedCharge/RecurringOccurrence) — lançamentos
avulsos (AdHocEntry) não entram, pois não são previsíveis mês a mês.
"""

from datetime import date, timedelta
from decimal import Decimal

from models import (
    CashSettings,
    ExpectedCharge,
    RecurringOccurrence,
    AdHocEntry,
    RentalAgreement,
    RecurringItem,
)
from importador import gerar_cobrancas_esperadas, atualizar_status_cobrancas
from contas_fixas import gerar_ocorrencias


def _month_bounds(year, month):
    first = date(year, month, 1)
    if month == 12:
        proximo = date(year + 1, 1, 1)
    else:
        proximo = date(year, month + 1, 1)
    return first, proximo - timedelta(days=1)


def _add_months(year, month, n):
    total = (year * 12 + (month - 1)) + n
    return total // 12, total % 12 + 1


def calcular_saldo_atual():
    """Saldo inicial + tudo confirmado (matched/paid/avulso) entre saldo_data e hoje."""
    settings = CashSettings.get()
    hoje = date.today()
    saldo = Decimal(settings.saldo_inicial)

    cobrancas = (
        ExpectedCharge.query.join(RentalAgreement)
        .filter(
            ExpectedCharge.status == "matched",
            ExpectedCharge.due_date >= settings.saldo_data,
            ExpectedCharge.due_date <= hoje,
        )
        .all()
    )
    for c in cobrancas:
        saldo += Decimal(c.amount_expected)

    ocorrencias = (
        RecurringOccurrence.query.join(RecurringItem)
        .filter(
            RecurringOccurrence.status == "paid",
            RecurringOccurrence.due_date >= settings.saldo_data,
            RecurringOccurrence.due_date <= hoje,
        )
        .all()
    )
    for o in ocorrencias:
        sinal = 1 if o.item.type == "income" else -1
        saldo += sinal * Decimal(o.amount)

    avulsos = AdHocEntry.query.filter(
        AdHocEntry.entry_date >= settings.saldo_data,
        AdHocEntry.entry_date <= hoje,
    ).all()
    for a in avulsos:
        sinal = 1 if a.type == "income" else -1
        saldo += sinal * Decimal(a.amount)

    return saldo


def calcular_projecao(meses=6):
    """Retorna (saldo_atual, [{ano, mes, receita, despesa, saldo_final, alerta}, ...])."""
    hoje = date.today()
    ano_final, mes_final = _add_months(hoje.year, hoje.month, meses - 1)
    _, horizonte_fim = _month_bounds(ano_final, mes_final)

    gerar_cobrancas_esperadas(until_date=horizonte_fim)
    gerar_ocorrencias(until_date=horizonte_fim)
    atualizar_status_cobrancas()

    saldo_atual = calcular_saldo_atual()
    saldo_corrente = saldo_atual
    linhas = []

    for i in range(meses):
        ano, mes = _add_months(hoje.year, hoje.month, i)
        inicio_mes, fim_mes = _month_bounds(ano, mes)

        # Só o que ainda NÃO foi confirmado entra na projeção (o que já foi confirmado
        # já está em saldo_atual) — não filtramos por "due_date > hoje" para não perder
        # cobranças com vencimento hoje/já vencidas dentro do mês que ainda seguem pendentes.
        cobrancas = (
            ExpectedCharge.query.join(RentalAgreement)
            .filter(
                ExpectedCharge.status != "matched",
                ExpectedCharge.due_date >= inicio_mes,
                ExpectedCharge.due_date <= fim_mes,
            )
            .all()
        )
        receita = sum(
            (Decimal(c.amount_expected) * c.agreement.reliability_pct / 100 for c in cobrancas),
            Decimal("0"),
        )

        ocorrencias = (
            RecurringOccurrence.query.join(RecurringItem)
            .filter(
                RecurringOccurrence.status != "paid",
                RecurringOccurrence.due_date >= inicio_mes,
                RecurringOccurrence.due_date <= fim_mes,
            )
            .all()
        )
        receita_fixa = sum(
            (Decimal(o.amount) for o in ocorrencias if o.item.type == "income"), Decimal("0")
        )
        despesa_fixa = sum(
            (Decimal(o.amount) for o in ocorrencias if o.item.type == "expense"), Decimal("0")
        )

        receita_total = receita + receita_fixa
        net = receita_total - despesa_fixa
        saldo_corrente = saldo_corrente + net

        linhas.append(
            {
                "ano": ano,
                "mes": mes,
                "receita": receita_total,
                "despesa": despesa_fixa,
                "net": net,
                "saldo_final": saldo_corrente,
                "alerta": saldo_corrente < 0,
            }
        )

    return saldo_atual, linhas
