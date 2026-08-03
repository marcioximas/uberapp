"""Envio de cobrança de parcela atrasada via WhatsApp (Meta Cloud API oficial).

A Cloud API não envia para grupos nem permite mencionar usuários — apenas mensagens
1-para-1 para um número de telefone, e fora da janela de 24h de atendimento é
obrigatório usar um Message Template pré-aprovado no Meta Business Manager.

Configuração necessária (ver .env.example):
  WHATSAPP_TOKEN            token de acesso permanente do app da Meta
  WHATSAPP_PHONE_NUMBER_ID  ID do número de telefone comercial (Cloud API)
  WHATSAPP_TEMPLATE_NAME    nome do template aprovado (padrão: "cobranca_atraso")
  WHATSAPP_TEMPLATE_LANG    idioma do template (padrão: "pt_BR")

O template precisa ser criado e aprovado previamente no Meta Business Manager com
4 variáveis de corpo, na ordem: nome do motorista, placa do carro, valor (R$),
data de vencimento. Exemplo de corpo de template a cadastrar:

  "Olá {{1}}, o aluguel do carro {{2}} no valor de R$ {{3}}, vencido em {{4}},
   ainda não foi identificado em nosso sistema. Por favor, regularize o pagamento."
"""

import os

import requests


class WhatsAppError(Exception):
    pass


class WhatsAppNotConfiguredError(WhatsAppError):
    pass


def _config():
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        raise WhatsAppNotConfiguredError(
            "WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID não configurados no ambiente."
        )
    return {
        "token": token,
        "phone_number_id": phone_number_id,
        "template_name": os.environ.get("WHATSAPP_TEMPLATE_NAME", "cobranca_atraso"),
        "template_lang": os.environ.get("WHATSAPP_TEMPLATE_LANG", "pt_BR"),
        "api_version": os.environ.get("WHATSAPP_API_VERSION", "v20.0"),
    }


def normalizar_numero(phone):
    """Normaliza um telefone BR para o formato E.164 sem '+' exigido pela Cloud API."""
    digitos = "".join(c for c in phone if c.isdigit())
    if not digitos:
        return None
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos
    if len(digitos) in (10, 11):  # DDD + número, sem código do país
        return "55" + digitos
    return digitos


def enviar_cobranca(expected_charge):
    """Envia o template de cobrança para o motorista do agreement vinculado a expected_charge.

    Retorna o message id em caso de sucesso. Levanta WhatsAppError em caso de falha
    (config ausente, telefone ausente/inválido, ou erro retornado pela API da Meta).
    """
    config = _config()

    driver = expected_charge.agreement.driver
    if not driver.phone:
        raise WhatsAppError(f"Motorista {driver.name} não tem telefone cadastrado.")

    numero = normalizar_numero(driver.phone)
    if not numero:
        raise WhatsAppError(f"Telefone de {driver.name} inválido: {driver.phone!r}.")

    car = expected_charge.agreement.car
    url = (
        f"https://graph.facebook.com/{config['api_version']}"
        f"/{config['phone_number_id']}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "template",
        "template": {
            "name": config["template_name"],
            "language": {"code": config["template_lang"]},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": driver.name},
                        {"type": "text", "text": car.plate},
                        {"type": "text", "text": f"{expected_charge.amount_expected:.2f}"},
                        {"type": "text", "text": expected_charge.due_date.strftime("%d/%m/%Y")},
                    ],
                }
            ],
        },
    }
    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Content-Type": "application/json",
    }

    try:
        resposta = requests.post(url, json=payload, headers=headers, timeout=15)
    except requests.RequestException as exc:
        raise WhatsAppError(f"Falha de conexão com a API do WhatsApp: {exc}") from exc

    if resposta.status_code >= 400:
        raise WhatsAppError(f"API do WhatsApp retornou erro: {resposta.status_code} {resposta.text}")

    dados = resposta.json()
    try:
        return dados["messages"][0]["id"]
    except (KeyError, IndexError):
        raise WhatsAppError(f"Resposta inesperada da API do WhatsApp: {dados}")
