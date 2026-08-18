from datetime import date
from decimal import Decimal
from collections import defaultdict

from flask import Blueprint, render_template, request
from flask_login import login_required

from models import (
    Car,
    ExpectedCharge,
    GPSReading,
    MaintenanceItem,
    RentalAgreement,
    RecurringItem,
    RecurringOccurrence,
    AdHocEntry,
)
from importador import gerar_cobrancas_esperadas, atualizar_status_cobrancas
from contas_fixas import gerar_ocorrencias

dashboard_bp = Blueprint("dashboard", __name__)


def _margem_por_carro():
    hoje = date.today()
    inicio_mes = date(hoje.year, hoje.month, 1)
    fim_mes = date(hoje.year + 1, 1, 1) if hoje.month == 12 else date(hoje.year, hoje.month + 1, 1)

    margem = defaultdict(Decimal)

    cobrancas = (
        ExpectedCharge.query.join(RentalAgreement)
        .filter(
            ExpectedCharge.status == "matched",
            ExpectedCharge.due_date >= inicio_mes,
            ExpectedCharge.due_date < fim_mes,
        )
        .all()
    )
    for c in cobrancas:
        margem[c.agreement.car_id] += Decimal(c.amount_expected)

    ocorrencias = (
        RecurringOccurrence.query.join(RecurringItem)
        .filter(
            RecurringOccurrence.status == "paid",
            RecurringOccurrence.due_date >= inicio_mes,
            RecurringOccurrence.due_date < fim_mes,
        )
        .all()
    )
    for o in ocorrencias:
        sinal = 1 if o.item.type == "income" else -1
        margem[o.item.car_id] += sinal * Decimal(o.amount)

    avulsos = AdHocEntry.query.filter(
        AdHocEntry.entry_date >= inicio_mes, AdHocEntry.entry_date < fim_mes
    ).all()
    for a in avulsos:
        sinal = 1 if a.type == "income" else -1
        margem[a.car_id] += sinal * Decimal(a.amount)

    cars_by_id = {c.id: c for c in Car.query.filter_by(active=True).all()}
    ranking = [
        (cars_by_id[car_id], valor) for car_id, valor in margem.items() if car_id in cars_by_id
    ]
    ranking.sort(key=lambda par: par[1], reverse=True)
    return ranking


_NOMES_MES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _km_deltas_por_carro_e_mes():
    """Retorna um dict {(car_id, ano, mes): km} com o KM rodado por cada carro
    em cada mês.

    Cada GPSReading.confirmed_km é uma leitura de odômetro (absoluta), não um
    delta — então o KM rodado num mês é a soma dos avanços positivos entre
    leituras consecutivas do mesmo carro cuja leitura mais recente do par caiu
    naquele mês.
    """
    deltas = defaultdict(float)
    leituras = (
        GPSReading.query.filter(
            GPSReading.confirmed_km.isnot(None), GPSReading.reading_date.isnot(None)
        )
        .order_by(GPSReading.car_id, GPSReading.reading_date, GPSReading.created_at)
        .all()
    )
    ultimo_km_por_carro = {}
    for leitura in leituras:
        anterior = ultimo_km_por_carro.get(leitura.car_id)
        if anterior is not None and leitura.confirmed_km > anterior:
            chave = (leitura.car_id, leitura.reading_date.year, leitura.reading_date.month)
            deltas[chave] += leitura.confirmed_km - anterior
        ultimo_km_por_carro[leitura.car_id] = leitura.confirmed_km
    return deltas


def _km_por_carro_no_mes(ano, mes, carros):
    deltas = _km_deltas_por_carro_e_mes()
    return [
        {"label": carro.model or carro.plate, "km": deltas.get((carro.id, ano, mes), 0)}
        for carro in carros
    ]


def _meses_disponiveis(quantidade=12):
    """Últimos `quantidade` meses (incluindo o atual), do mais recente pro
    mais antigo — usado pra popular o seletor de mês do gráfico de KM."""
    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    meses = []
    for i in range(quantidade):
        m = mes - i
        a = ano
        while m <= 0:
            m += 12
            a -= 1
        meses.append({"value": f"{a:04d}-{m:02d}", "label": f"{_NOMES_MES[m - 1]}/{str(a)[2:]}", "ano": a, "mes": m})
    return meses


def _grafico_km_svg(dados):
    """Monta a geometria (em px) de um gráfico de barras simples, pra desenhar
    em SVG no template sem depender de nenhuma lib de gráfico em JS."""
    largura, altura = 640, 220
    margem_esq, margem_dir, margem_topo, margem_baixo = 8, 8, 16, 28
    plot_w = largura - margem_esq - margem_dir
    plot_h = altura - margem_topo - margem_baixo
    baseline_y = margem_topo + plot_h

    valores = [d["km"] for d in dados]
    maximo = max(valores) if valores else 0

    passos = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000)
    for passo in passos:
        if maximo <= passo * 4:
            eixo_topo = passo * 4
            break
    else:
        eixo_topo = maximo or 1

    n = len(dados) or 1
    slot_w = plot_w / n
    bar_w = min(24, slot_w * 0.55)
    raio = 4

    barras = []
    for i, d in enumerate(dados):
        cx = margem_esq + slot_w * i + slot_w / 2
        x = cx - bar_w / 2
        h = (d["km"] / eixo_topo) * plot_h if eixo_topo else 0
        if d["km"] > 0:
            h = max(h, 2)
        y = baseline_y - h
        r = min(raio, h)

        if h <= 0:
            path = None
        elif h <= r:
            path = f"M {x:.1f},{baseline_y:.1f} L {x:.1f},{y:.1f} L {x + bar_w:.1f},{y:.1f} L {x + bar_w:.1f},{baseline_y:.1f} Z"
        else:
            path = (
                f"M {x:.1f},{y + r:.1f} "
                f"Q {x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                f"L {x + bar_w - r:.1f},{y:.1f} "
                f"Q {x + bar_w:.1f},{y:.1f} {x + bar_w:.1f},{y + r:.1f} "
                f"L {x + bar_w:.1f},{baseline_y:.1f} "
                f"L {x:.1f},{baseline_y:.1f} Z"
            )

        barras.append({
            "path": path,
            "cx": cx,
            "y": y,
            "label": d["label"],
            "km": d["km"],
        })

    grades = []
    for frac in (0, 1 / 3, 2 / 3, 1):
        grades.append({
            "y": baseline_y - plot_h * frac,
            "valor": round(eixo_topo * frac),
        })

    return {
        "largura": largura,
        "altura": altura,
        "x_esq": margem_esq,
        "x_dir": largura - margem_dir,
        "baseline_y": baseline_y,
        "barras": barras,
        "grades": grades,
    }


@dashboard_bp.route("/")
@login_required
def index():
    gerar_cobrancas_esperadas()
    gerar_ocorrencias()
    atualizar_status_cobrancas()

    resumo_cobrancas = {"pending": 0, "late": 0, "missing": 0, "matched": 0}
    for cobranca in ExpectedCharge.query.all():
        resumo_cobrancas[cobranca.status] = resumo_cobrancas.get(cobranca.status, 0) + 1

    hoje = date.today()
    alertas_manutencao = []
    for carro in Car.query.filter_by(active=True).all():
        for item in MaintenanceItem.query.filter_by(car_id=carro.id, active=True).all():
            status = item.status_alerta(carro.current_km, hoje)
            if status in ("atencao", "atrasado"):
                alertas_manutencao.append((carro, item, status))

    total_carros = Car.query.filter_by(active=True).count()
    ranking_margem = _margem_por_carro()

    carros_ativos = Car.query.filter_by(active=True).order_by(Car.plate).all()

    meses_disponiveis = _meses_disponiveis()
    km_mes = request.args.get("km_mes", default="")
    mes_selecionado = next((m for m in meses_disponiveis if m["value"] == km_mes), None)
    if mes_selecionado is None:
        mes_selecionado = meses_disponiveis[0]
        km_mes = mes_selecionado["value"]
    grafico_km_carro = _grafico_km_svg(
        _km_por_carro_no_mes(mes_selecionado["ano"], mes_selecionado["mes"], carros_ativos)
    )

    return render_template(
        "dashboard/index.html",
        resumo_cobrancas=resumo_cobrancas,
        alertas_manutencao=alertas_manutencao,
        total_carros=total_carros,
        ranking_margem=ranking_margem,
        grafico_km_carro=grafico_km_carro,
        carros_ativos=carros_ativos,
        meses_disponiveis=meses_disponiveis,
        km_mes=km_mes,
        mes_selecionado=mes_selecionado,
    )
