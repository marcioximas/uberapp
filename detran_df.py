"""Consulta de débitos/multas de um veículo no Detran-DF via HTTP direto
(sem browser, sem login pessoal, sem captcha).

Descoberto inspecionando as chamadas de rede reais do portal.detran.df.gov.br
(https://portal.detran.df.gov.br/#/servicos/detran-digital/veiculos/consulta/debitos):
o SPA usa uma credencial "client_credentials" fixa, embutida no próprio JS do
site (não é o login pessoal do cidadão), pra pegar um token de serviço no
Keycloak deles, e então consulta o débito/multa de um veículo pelo CHASSI
(não placa/renavam) num endpoint público.

Fluxo:
  1. obter_token_servico() — client_credentials no Keycloak do Detran-DF,
     usando DETRAN_DF_CLIENT_ID/DETRAN_DF_CLIENT_SECRET (a mesma credencial
     que o navegador de qualquer visitante do site usa).
  2. consultar_debitos_por_chassi(chassi) — GET no endpoint de débitos,
     retorna o JSON bruto (inclui infracoesVeiculo, débitos de IPVA, etc).
  3. consultar_multas_carro(car) — helper que já extrai só as multas
     (infracoesVeiculo) no formato esperado por fines.upsert_fine.

Variáveis de ambiente: DETRAN_DF_CLIENT_ID, DETRAN_DF_CLIENT_SECRET
(ver .env.example).
"""
import os
from datetime import datetime

import requests

TOKEN_URL = "https://acesso.detran.df.gov.br/auth/realms/detran-portal/protocol/openid-connect/token"
DEBITOS_URL = "https://route5-api.detran.df.gov.br/fuse-service-prod/api/veiculo/codbarras/SEM_BOLETO/{chassi}/{ano}/debitos"

# O WAF na frente da API do Detran-DF rejeita requisições sem cara de navegador
# (ex.: User-Agent padrão do requests). Estes são os mesmos headers que o
# próprio portal.detran.df.gov.br manda nessas chamadas.
_HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
    "Origin": "https://portal.detran.df.gov.br",
    "Referer": "https://portal.detran.df.gov.br/",
}


class DetranDFError(Exception):
    pass


class DetranDFNotConfigured(DetranDFError):
    pass


def obter_token_servico():
    client_id = os.environ.get("DETRAN_DF_CLIENT_ID")
    client_secret = os.environ.get("DETRAN_DF_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise DetranDFNotConfigured(
            "DETRAN_DF_CLIENT_ID / DETRAN_DF_CLIENT_SECRET não configurados no ambiente."
        )

    try:
        resp = requests.post(
            TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials", "scope": "profile phone email"},
            headers={**_HEADERS_NAVEGADOR, "Accept": "application/json, image/*"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise DetranDFError(f"Falha de conexão ao autenticar no Detran-DF: {exc}") from exc

    if resp.status_code >= 400:
        raise DetranDFError(f"Falha ao autenticar no Detran-DF: HTTP {resp.status_code} {resp.text}")

    try:
        return resp.json()["access_token"]
    except (KeyError, ValueError):
        raise DetranDFError(f"Resposta inesperada ao autenticar no Detran-DF: {resp.text}")


def consultar_debitos_por_chassi(chassi, token, ano="ANOS_ANTERIORES"):
    """Retorna o JSON bruto de débitos/multas do veículo (chassi), sem tratamento."""
    url = DEBITOS_URL.format(chassi=chassi, ano=ano)
    try:
        resp = requests.get(
            url,
            headers={
                **_HEADERS_NAVEGADOR,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, image/*",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise DetranDFError(f"Falha de conexão ao consultar débitos ({chassi}): {exc}") from exc

    if resp.status_code >= 400:
        raise DetranDFError(f"Falha ao consultar débitos ({chassi}): HTTP {resp.status_code} {resp.text}")

    return resp.json()


def _parse_data_br(texto):
    if not texto:
        return None
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _parse_valor(texto):
    if texto in (None, ""):
        return None
    try:
        return float(texto)
    except (TypeError, ValueError):
        return None


def extrair_multas(resposta_json):
    """Converte o campo infracoesVeiculo da resposta bruta em list[dict] no
    formato esperado por fines.upsert_fine."""
    import json as _json

    multas = []
    for infracao in resposta_json.get("infracoesVeiculo") or []:
        multas.append({
            "numero_ait": infracao.get("numeroAuto"),
            "data_infracao": _parse_data_br(infracao.get("dataInfracao")),
            "local": infracao.get("localMulta"),
            "descricao": infracao.get("descricaoInfracao"),
            "valor": _parse_valor(infracao.get("valor")),
            "vencimento": _parse_data_br(infracao.get("dataVencimento")),
            "pontos": infracao.get("pontosInfracao"),
            "orgao_status": infracao.get("descSituacao"),
            "raw_response": _json.dumps(infracao, ensure_ascii=False),
        })
    return multas


def consultar_multas_carro(car, token=None):
    """Consulta as multas do carro (usa car.chassi) e retorna list[dict] no
    formato esperado por fines.upsert_fine.

    Levanta ValueError se o carro não tiver chassi cadastrado.
    Se `token` não for passado, obtém um novo (client_credentials).
    """
    if not car.chassi:
        raise ValueError(f"Carro {car.plate} não tem chassi cadastrado — pulei a consulta.")

    if token is None:
        token = obter_token_servico()

    dados = consultar_debitos_por_chassi(car.chassi, token)
    return extrair_multas(dados)
