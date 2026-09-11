from datetime import date, timedelta, timezone
from decimal import Decimal
from collections import defaultdict

from flask import Blueprint, render_template, request
from flask_login import login_required

from models import (
    Car,
    ExpectedCharge,
    Fine,
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


def _km_deltas_por_carro(chave_periodo):
    """Retorna um dict {(car_id, *chave_periodo(reading_date)): km} com o KM
    rodado por cada carro em cada período (a chave é definida por quem chama:
    (ano, mes), (ano_iso, semana_iso), (ano, mes, dia), etc).

    Cada GPSReading.confirmed_km é uma leitura de odômetro (absoluta), não um
    delta — então o KM rodado num período é a soma dos avanços positivos entre
    leituras consecutivas do mesmo carro cuja leitura mais recente do par caiu
    naquele período.
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
            chave = (leitura.car_id,) + chave_periodo(leitura.reading_date)
            deltas[chave] += leitura.confirmed_km - anterior
        ultimo_km_por_carro[leitura.car_id] = leitura.confirmed_km
    return deltas


def _km_deltas_por_carro_e_mes():
    return _km_deltas_por_carro(lambda d: (d.year, d.month))


def _km_deltas_por_carro_e_semana():
    return _km_deltas_por_carro(lambda d: d.isocalendar()[:2])


def _km_deltas_por_carro_e_dia():
    return _km_deltas_por_carro(lambda d: (d.year, d.month, d.day))


def _km_por_carro_no_mes(ano, mes, carros):
    deltas = _km_deltas_por_carro_e_mes()
    return [
        {"label": carro.model or carro.plate, "km": deltas.get((carro.id, ano, mes), 0)}
        for carro in carros
    ]


def _km_por_carro_na_semana(ano_iso, semana_iso, carros):
    deltas = _km_deltas_por_carro_e_semana()
    return [
        {"label": carro.model or carro.plate, "km": deltas.get((carro.id, ano_iso, semana_iso), 0)}
        for carro in carros
    ]


def _km_por_carro_no_dia(ano, mes, dia, carros):
    deltas = _km_deltas_por_carro_e_dia()
    return [
        {"label": carro.model or carro.plate, "km": deltas.get((carro.id, ano, mes, dia), 0)}
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


def _semanas_disponiveis(quantidade=12):
    """Últimas `quantidade` semanas (segunda a domingo, incluindo a atual),
    da mais recente pra mais antiga — usado pra popular o seletor de semana
    do gráfico de KM."""
    hoje = date.today()
    inicio_semana_atual = hoje - timedelta(days=hoje.weekday())
    semanas = []
    for i in range(quantidade):
        inicio = inicio_semana_atual - timedelta(weeks=i)
        fim = inicio + timedelta(days=6)
        ano_iso, semana_iso, _ = inicio.isocalendar()
        semanas.append({
            "value": f"{ano_iso:04d}-W{semana_iso:02d}",
            "label": f"{inicio.strftime('%d/%m')} a {fim.strftime('%d/%m')}",
            "ano_iso": ano_iso,
            "semana_iso": semana_iso,
        })
    return semanas


def _dias_disponiveis(quantidade=14):
    """Últimos `quantidade` dias (incluindo hoje), do mais recente pro mais
    antigo — usado pra popular o seletor de dia do gráfico de KM."""
    hoje = date.today()
    dias = []
    for i in range(quantidade):
        d = hoje - timedelta(days=i)
        dias.append({
            "value": d.isoformat(),
            "label": d.strftime("%d/%m"),
            "ano": d.year,
            "mes": d.month,
            "dia": d.day,
        })
    return dias


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


def _ultima_atualizacao_km():
    """Data/hora (horário de Brasília) da última leitura de GPS gravada
    automaticamente pelo GitHub Actions (relatorio_gps.py) — quando o KM
    dos carros foi atualizado pela última vez."""
    ultima = (
        GPSReading.query.filter(GPSReading.image_filename.like("relatorio-gps-automatico:%"))
        .order_by(GPSReading.created_at.desc())
        .first()
    )
    if ultima is None or ultima.created_at is None:
        return None

    utc = ultima.created_at.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return utc.astimezone(ZoneInfo("America/Sao_Paulo"))
    except Exception:
        # Fallback sem tzdata instalado: Brasília é UTC-3 o ano todo (sem horário de verão).
        return utc - timedelta(hours=3)


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

    alertas_multas = []
    for carro in Car.query.filter_by(active=True).all():
        for fine in Fine.query.filter_by(car_id=carro.id).all():
            status = fine.status_display(hoje)
            if status not in ("paga", "recorrida", "rejected"):
                alertas_multas.append((carro, fine, status))
    alertas_multas.sort(key=lambda x: 0 if x[2] == "vencida" else 1)
    total_multas_pendentes = len(alertas_multas)

    total_carros = Car.query.filter_by(active=True).count()
    ranking_margem = _margem_por_carro()

    carros_ativos = Car.query.filter_by(active=True).order_by(Car.plate).all()

    periodo_tipo = request.args.get("periodo_tipo", default="mes")
    if periodo_tipo not in ("dia", "semana", "mes"):
        periodo_tipo = "mes"

    meses_disponiveis = _meses_disponiveis()
    km_mes = request.args.get("km_mes", default="")
    mes_selecionado = next((m for m in meses_disponiveis if m["value"] == km_mes), None)
    if mes_selecionado is None:
        mes_selecionado = meses_disponiveis[0]
        km_mes = mes_selecionado["value"]

    semanas_disponiveis = _semanas_disponiveis()
    km_semana = request.args.get("km_semana", default="")
    semana_selecionada = next((s for s in semanas_disponiveis if s["value"] == km_semana), None)
    if semana_selecionada is None:
        semana_selecionada = semanas_disponiveis[0]
        km_semana = semana_selecionada["value"]

    dias_disponiveis = _dias_disponiveis()
    km_dia = request.args.get("km_dia", default="")
    dia_selecionado = next((d for d in dias_disponiveis if d["value"] == km_dia), None)
    if dia_selecionado is None:
        dia_selecionado = dias_disponiveis[0]
        km_dia = dia_selecionado["value"]

    if periodo_tipo == "semana":
        periodo_label = semana_selecionada["label"]
        grafico_km_carro = _grafico_km_svg(
            _km_por_carro_na_semana(semana_selecionada["ano_iso"], semana_selecionada["semana_iso"], carros_ativos)
        )
    elif periodo_tipo == "dia":
        periodo_label = dia_selecionado["label"]
        grafico_km_carro = _grafico_km_svg(
            _km_por_carro_no_dia(dia_selecionado["ano"], dia_selecionado["mes"], dia_selecionado["dia"], carros_ativos)
        )
    else:
        periodo_label = mes_selecionado["label"]
        grafico_km_carro = _grafico_km_svg(
            _km_por_carro_no_mes(mes_selecionado["ano"], mes_selecionado["mes"], carros_ativos)
        )

    ultima_atualizacao_km = _ultima_atualizacao_km()

    return render_template(
        "dashboard/index.html",
        resumo_cobrancas=resumo_cobrancas,
        alertas_manutencao=alertas_manutencao,
        alertas_multas=alertas_multas,
        total_multas_pendentes=total_multas_pendentes,
        total_carros=total_carros,
        ranking_margem=ranking_margem,
        grafico_km_carro=grafico_km_carro,
        carros_ativos=carros_ativos,
        periodo_tipo=periodo_tipo,
        periodo_label=periodo_label,
        meses_disponiveis=meses_disponiveis,
        km_mes=km_mes,
        mes_selecionado=mes_selecionado,
        semanas_disponiveis=semanas_disponiveis,
        km_semana=km_semana,
        semana_selecionada=semana_selecionada,
        dias_disponiveis=dias_disponiveis,
        km_dia=km_dia,
        dia_selecionado=dia_selecionado,
        ultima_atualizacao_km=ultima_atualizacao_km,
    )
