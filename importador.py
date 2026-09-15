"""Importação do extrato CSV do Itaú e conciliação com os aluguéis fixos esperados."""

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from extensions import db
from models import (
    ImportBatch,
    Transaction,
    RentalAgreement,
    ExpectedCharge,
    TOLERANCIA_DIAS,
)
from recorrencia import gerar_datas_vencimento

# Aliases de nomes de coluna (case/acento-insensível) usados para localizar o cabeçalho real
COLUNA_ALIASES = {
    "data": ["data", "dt.", "data lancamento", "data lanc"],
    "descricao": ["lancamento", "historico", "descricao", "detalhes"],
    "valor": ["valor", "valor (r$)", "vlr", "valor(r$)"],
}


class ImportadorError(Exception):
    pass


def _normalizar(texto):
    import unicodedata

    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return texto.strip().lower()


def _detectar_delimitador(linhas):
    amostra = "\n".join(linhas[:5])
    try:
        dialect = csv.Sniffer().sniff(amostra, delimiters=";,")
        return dialect.delimiter
    except csv.Error:
        return ";" if amostra.count(";") >= amostra.count(",") else ","


def _encontrar_indices_cabecalho(linhas, delimitador):
    for i, linha in enumerate(linhas[:15]):
        celulas = [_normalizar(c) for c in linha.split(delimitador)]
        indices = {}
        for campo, aliases in COLUNA_ALIASES.items():
            for idx, celula in enumerate(celulas):
                if celula in aliases:
                    indices[campo] = idx
                    break
        if len(indices) == len(COLUNA_ALIASES):
            return i, indices
    return None, None


def _parse_valor(valor_str):
    valor_str = valor_str.strip().replace("R$", "").strip()
    if not valor_str:
        raise InvalidOperation("valor vazio")
    negativo = valor_str.startswith("-") or (valor_str.startswith("(") and valor_str.endswith(")"))
    valor_str = valor_str.strip("()").lstrip("-").strip()
    if "," in valor_str and "." in valor_str:
        # formato BR: 1.234,56
        valor_str = valor_str.replace(".", "").replace(",", ".")
    elif "," in valor_str:
        valor_str = valor_str.replace(",", ".")
    valor = Decimal(valor_str)
    return -valor if negativo else valor


def _parse_data(data_str):
    data_str = data_str.strip()
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            from datetime import datetime

            return datetime.strptime(data_str, formato).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {data_str}")


def parse_itau_csv(file_stream):
    """Lê o CSV do extrato Itaú e retorna (linhas_validas, linhas_ignoradas).

    linhas_validas: list[dict] com keys date, description, amount, raw_row
    linhas_ignoradas: contagem de linhas que não puderam ser interpretadas
    """
    raw_bytes = file_stream.read()
    try:
        texto = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = raw_bytes.decode("latin-1")

    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        raise ImportadorError("Arquivo CSV vazio.")

    delimitador = _detectar_delimitador(linhas)
    idx_cabecalho, indices = _encontrar_indices_cabecalho(linhas, delimitador)
    if idx_cabecalho is None:
        raise ImportadorError(
            "Não foi possível localizar as colunas de data/descrição/valor no CSV."
        )

    linhas_validas = []
    linhas_ignoradas = 0
    for linha in linhas[idx_cabecalho + 1 :]:
        celulas = linha.split(delimitador)
        max_idx = max(indices.values())
        if len(celulas) <= max_idx:
            linhas_ignoradas += 1
            continue
        try:
            data_transacao = _parse_data(celulas[indices["data"]])
            valor = _parse_valor(celulas[indices["valor"]])
        except (ValueError, InvalidOperation):
            linhas_ignoradas += 1
            continue
        descricao = celulas[indices["descricao"]].strip()
        linhas_validas.append(
            {
                "date": data_transacao,
                "description": descricao,
                "amount": valor,
                "raw_row": linha,
            }
        )

    if not linhas_validas:
        raise ImportadorError("Nenhuma linha válida encontrada no CSV.")

    return linhas_validas, linhas_ignoradas


def importar_extrato(file_stream, filename, user_id):
    """Faz o parse do CSV, cria o ImportBatch + Transactions e roda a conciliação automática."""
    linhas, ignoradas = parse_itau_csv(file_stream)

    batch = ImportBatch(
        filename=filename,
        imported_by_user_id=user_id,
        row_count=len(linhas),
        skipped_row_count=ignoradas,
    )
    db.session.add(batch)
    db.session.flush()

    for linha in linhas:
        transacao = Transaction(
            import_batch_id=batch.id,
            transaction_date=linha["date"],
            description=linha["description"],
            amount=linha["amount"],
            raw_row=linha["raw_row"],
        )
        db.session.add(transacao)

    db.session.commit()

    gerar_cobrancas_esperadas()
    conciliar_transacoes(batch_id=batch.id)
    atualizar_status_cobrancas()
    db.session.commit()

    return batch


def gerar_cobrancas_esperadas(until_date=None):
    """Gera ExpectedCharge para todo agreement ativo, do start_date até until_date (padrão: hoje)."""
    until_date = until_date or date.today()

    for agreement in RentalAgreement.query.filter_by(active=True).all():
        fim = agreement.end_date or until_date
        fim = min(fim, until_date)
        datas = gerar_datas_vencimento(
            agreement.start_date, agreement.frequency, agreement.weekday, agreement.day_of_month, fim
        )
        for due_date in datas:
            existe = ExpectedCharge.query.filter_by(
                rental_agreement_id=agreement.id, due_date=due_date
            ).first()
            if not existe:
                db.session.add(
                    ExpectedCharge(
                        rental_agreement_id=agreement.id,
                        due_date=due_date,
                        amount_expected=agreement.amount,
                    )
                )
    db.session.commit()


def conciliar_transacoes(batch_id=None):
    """Faz o matching automático de transações não conciliadas contra cobranças esperadas."""
    query = Transaction.query.filter_by(status="unmatched").filter(Transaction.amount > 0)
    if batch_id is not None:
        query = query.filter_by(import_batch_id=batch_id)

    for transacao in query.all():
        candidatos = (
            ExpectedCharge.query.join(RentalAgreement)
            .filter(
                ExpectedCharge.status.in_(["pending", "late"]),
                db.or_(
                    ExpectedCharge.amount_expected == transacao.amount,
                    RentalAgreement.discounted_amount == transacao.amount,
                ),
            )
            .all()
        )
        candidatos = [
            c
            for c in candidatos
            if abs((transacao.transaction_date - c.due_date).days) <= TOLERANCIA_DIAS
            and c.transaction is None
        ]

        cobranca = None
        if len(candidatos) == 1:
            cobranca = candidatos[0]
        elif len(candidatos) > 1:
            # Cadências semanais (7 dias) com tolerância de alguns dias fazem janelas
            # vizinhas se sobreporem — nesse caso, casa com a data de vencimento mais
            # próxima, desde que ela seja unicamente a mais próxima (sem empate).
            candidatos.sort(key=lambda c: abs((transacao.transaction_date - c.due_date).days))
            menor_distancia = abs((transacao.transaction_date - candidatos[0].due_date).days)
            proxima_distancia = abs((transacao.transaction_date - candidatos[1].due_date).days)
            if menor_distancia < proxima_distancia:
                cobranca = candidatos[0]

        if cobranca is not None:
            transacao.status = "matched"
            transacao.matched_expected_charge_id = cobranca.id
            transacao.matched_car_id = cobranca.agreement.car_id
            transacao.matched_by = "auto"
            cobranca.status = "matched"

    db.session.commit()


def atualizar_status_cobrancas():
    """Recomputa o status (pending/late/missing) de todas as cobranças ainda não conciliadas."""
    hoje = date.today()
    for cobranca in ExpectedCharge.query.filter(ExpectedCharge.status != "matched").all():
        cobranca.recompute_status(hoje)
    db.session.commit()
