"""Leitura de prints de rastreador GPS via API de visão da Anthropic."""

import base64
import json
import os
import uuid

from PIL import Image, UnidentifiedImageError
import anthropic

MAX_DIMENSAO = 1568  # recomendação da Anthropic p/ uso eficiente de tokens de visão

PROMPT = """\
Esta imagem é um print de tela de um aplicativo rastreador de GPS de veículo, \
mostrando um resumo semanal de uma viagem/período.

Extraia os seguintes dados e responda APENAS com um objeto JSON, sem markdown, \
sem texto antes ou depois, com exatamente estas chaves:

{
  "km_rodado": <inteiro, quilômetros rodados no período>,
  "velocidade_maxima": <inteiro, velocidade máxima em km/h>,
  "tempo_em_movimento_minutos": <inteiro, tempo total em movimento, já convertido para minutos>,
  "confianca": "alta" | "media" | "baixa",
  "observacoes": "<qualquer ressalva sobre valores ilegíveis ou ambíguos, ou string vazia>"
}

Se algum valor não estiver visível ou legível na imagem, use null para aquele campo \
e explique em "observacoes".
"""


class GPSReaderError(Exception):
    pass


def validar_e_salvar_imagem(file_storage, upload_folder):
    """Valida que o upload é uma imagem de fato, redimensiona se necessário, salva em disco.

    Retorna o nome do arquivo salvo (relativo a upload_folder/gps).
    """
    try:
        imagem = Image.open(file_storage.stream)
        imagem.verify()
    except UnidentifiedImageError as exc:
        raise GPSReaderError("O arquivo enviado não é uma imagem válida.") from exc

    file_storage.stream.seek(0)
    imagem = Image.open(file_storage.stream)
    imagem = imagem.convert("RGB")

    if max(imagem.size) > MAX_DIMENSAO:
        imagem.thumbnail((MAX_DIMENSAO, MAX_DIMENSAO))

    nome_arquivo = f"{uuid.uuid4().hex}.jpg"
    destino = os.path.join(upload_folder, "gps", nome_arquivo)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    imagem.save(destino, format="JPEG", quality=85)

    return nome_arquivo


def _strip_markdown_fence(texto):
    texto = texto.strip()
    if texto.startswith("```"):
        linhas = texto.splitlines()
        linhas = linhas[1:]
        if linhas and linhas[-1].strip().startswith("```"):
            linhas = linhas[:-1]
        texto = "\n".join(linhas)
    return texto.strip()


def extrair_dados(caminho_imagem):
    """Chama a API da Anthropic para extrair os dados do print de GPS.

    Retorna sempre um dict com as chaves extracted_km, extracted_max_speed,
    extracted_moving_time_minutes, confidence_note, raw_ai_response — mesmo em
    caso de falha (campos numéricos ficam None e confidence_note explica o motivo),
    permitindo preenchimento manual na tela de revisão.
    """
    resultado = {
        "extracted_km": None,
        "extracted_max_speed": None,
        "extracted_moving_time_minutes": None,
        "confidence_note": None,
        "raw_ai_response": None,
    }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        resultado["confidence_note"] = (
            "ANTHROPIC_API_KEY não configurada — preencha os dados manualmente."
        )
        return resultado

    with open(caminho_imagem, "rb") as f:
        imagem_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resposta = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": imagem_b64,
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        )
        texto_resposta = resposta.content[0].text
    except Exception as exc:  # erro de rede/API/autenticação
        resultado["confidence_note"] = (
            f"Não foi possível conectar à IA agora ({exc}) — preencha os dados manualmente."
        )
        return resultado

    resultado["raw_ai_response"] = texto_resposta

    try:
        dados = json.loads(_strip_markdown_fence(texto_resposta))
    except json.JSONDecodeError:
        resultado["confidence_note"] = (
            "Falha ao interpretar resposta da IA — preencha os dados manualmente."
        )
        return resultado

    resultado["extracted_km"] = dados.get("km_rodado")
    resultado["extracted_max_speed"] = dados.get("velocidade_maxima")
    resultado["extracted_moving_time_minutes"] = dados.get("tempo_em_movimento_minutos")

    observacoes = dados.get("observacoes") or ""
    confianca = dados.get("confianca")
    if confianca:
        observacoes = f"Confiança: {confianca}. {observacoes}".strip()
    resultado["confidence_note"] = observacoes or None

    return resultado
