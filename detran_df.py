"""Consulta de multas/débitos no Detran-DF (portal.detran.df.gov.br, "Detran Digital").

O Detran-DF não tem API pública nem paga simples, e a consulta de débitos
exige login autenticado — cuja tela tem reCAPTCHA real do Google. Não dá
para automatizar o login sozinho (o captcha exige uma pessoa de verdade).

Fluxo adotado (semi-automático):
  1. Uma pessoa roda `python detran_df_login.py` de vez em quando: abre um
     Chromium visível, pré-preenche CPF/senha (DETRAN_DF_CPF/DETRAN_DF_SENHA),
     e espera a pessoa resolver o captcha e clicar "Entrar" manualmente.
     Ao confirmar (Enter no terminal), salva a sessão autenticada em disco
     (SESSION_PATH — cookies + localStorage, formato storage_state do Playwright).
  2. `detran_df_multas.py` reaproveita essa sessão salva (sem precisar logar
     de novo) para consultar placa+renavam de cada carro automaticamente,
     enquanto ela durar. Quando expirar, `consultar_multas_carro` levanta
     DetranDFSessaoExpirada e é preciso rodar o login manual de novo.

Variáveis de ambiente:
  DETRAN_DF_CPF          CPF/CNPJ da conta única da frota (só para pré-preencher o login)
  DETRAN_DF_SENHA        senha da conta (só para pré-preencher o login)
  DETRAN_DF_SESSION_PATH caminho do arquivo de sessão salvo (padrão: instance/detran_df_session.json)

ATENÇÃO — seletores provisórios: não foi possível inspecionar o HTML da tela
autenticada de consulta sem logar de verdade (o login exige captcha humano).
Os seletores de placa/renavam/botão/resultado em `consultar_multas_carro` e
`_extrair_multas_da_pagina` são a melhor tentativa e quase certamente vão
precisar de um ajuste na primeira execução real — essas funções foram
mantidas isoladas exatamente para tornar esse ajuste barato.
"""
import os

LOGIN_URL = "https://portal.detran.df.gov.br/#/login"
DEBITOS_URL = "https://portal.detran.df.gov.br/#/servicos/detran-digital/veiculos/consulta/debitos"


def _session_path():
    return os.environ.get("DETRAN_DF_SESSION_PATH", os.path.join("instance", "detran_df_session.json"))


class DetranDFError(Exception):
    pass


class DetranDFSessaoExpirada(DetranDFError):
    """A sessão salva não autentica mais — é preciso rodar detran_df_login.py de novo."""


def iniciar_login_manual():
    """Abre um Chromium visível no login do Detran Digital, pré-preenche CPF/senha
    (se configurados), e espera a pessoa resolver o captcha e clicar "Entrar"
    manualmente. Ao confirmar no terminal, salva a sessão autenticada em disco."""
    from playwright.sync_api import sync_playwright

    cpf = os.environ.get("DETRAN_DF_CPF")
    senha = os.environ.get("DETRAN_DF_SENHA")
    session_path = _session_path()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)

        if cpf and senha:
            try:
                page.get_by_placeholder("Cpf/Cnpj").fill(cpf)
                page.get_by_placeholder("Senha").fill(senha)
                print("CPF/senha pré-preenchidos. Resolva o captcha e clique em 'Entrar'.")
            except Exception as exc:
                print(f"Não consegui pré-preencher CPF/senha automaticamente ({exc}). "
                      f"Preencha manualmente.")
        else:
            print("DETRAN_DF_CPF/DETRAN_DF_SENHA não configurados — preencha login manualmente.")

        input("\nDepois de logar com sucesso (resolver o captcha e clicar 'Entrar'), "
              "volte aqui e pressione Enter para salvar a sessão...")

        os.makedirs(os.path.dirname(session_path) or ".", exist_ok=True)
        context.storage_state(path=session_path)
        browser.close()

    print(f"Sessão salva em {session_path}.")


def carregar_sessao_ou_falhar():
    """Retorna (playwright, browser, context) autenticados com a sessão salva.
    Levanta DetranDFError se o arquivo de sessão não existir."""
    from playwright.sync_api import sync_playwright

    session_path = _session_path()
    if not os.path.exists(session_path):
        raise DetranDFError(
            f"Nenhuma sessão salva em {session_path}. Rode `python detran_df_login.py` primeiro."
        )

    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(storage_state=session_path)
    return p, browser, context


def _pagina_exige_login(page):
    """True se a página redirecionou para o login ou mostrou o aviso de
    acesso restrito — sinal de que a sessão salva expirou."""
    if "#/login" in page.url:
        return True
    try:
        return page.get_by_text("Área de acesso somente para usuários logados").is_visible(timeout=1000)
    except Exception:
        return False


def _extrair_multas_da_pagina(page, car):
    """Lê a tabela de resultado da consulta e retorna list[dict] no formato
    esperado por fines.upsert_fine (numero_ait, data_infracao, local,
    descricao, valor, vencimento, pontos, orgao_status, raw_response).

    PROVISÓRIO: mapeia colunas por texto do cabeçalho da tabela, tentando ser
    resiliente a pequenas variações de nome. Ajustar depois de ver a página
    autenticada de verdade pela primeira vez.
    """
    import json
    from datetime import datetime

    def _parse_data(texto):
        texto = (texto or "").strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(texto, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_valor(texto):
        texto = (texto or "").strip().replace("R$", "").strip()
        texto = texto.replace(".", "").replace(",", ".")
        try:
            return float(texto)
        except ValueError:
            return None

    linhas_html = page.locator("table tbody tr").all()
    if not linhas_html:
        return []

    cabecalhos = [h.strip().lower() for h in page.locator("table thead th").all_inner_texts()]

    def _indice(*nomes):
        for nome in nomes:
            for i, h in enumerate(cabecalhos):
                if nome in h:
                    return i
        return None

    idx_ait = _indice("ait", "auto de infração", "número")
    idx_data = _indice("data")
    idx_local = _indice("local")
    idx_descricao = _indice("infração", "descrição")
    idx_valor = _indice("valor")
    idx_vencimento = _indice("vencimento")
    idx_pontos = _indice("pontos", "pontuação")
    idx_status = _indice("situação", "status")

    resultado = []
    for linha in linhas_html:
        celulas = linha.locator("td").all_inner_texts()
        if not celulas:
            continue

        def _col(idx):
            return celulas[idx].strip() if idx is not None and idx < len(celulas) else None

        numero_ait = _col(idx_ait) or "-".join(c.strip() for c in celulas[:2])
        resultado.append({
            "numero_ait": numero_ait,
            "data_infracao": _parse_data(_col(idx_data)),
            "local": _col(idx_local),
            "descricao": _col(idx_descricao),
            "valor": _parse_valor(_col(idx_valor)),
            "vencimento": _parse_data(_col(idx_vencimento)),
            "pontos": int(_col(idx_pontos)) if _col(idx_pontos) and _col(idx_pontos).isdigit() else None,
            "orgao_status": _col(idx_status),
            "raw_response": json.dumps({"placa": car.plate, "renavam": car.renavam, "celulas": celulas}),
        })
    return resultado


def consultar_multas_carro(page, car):
    """Consulta as multas/débitos do carro (usa car.plate e car.renavam) e
    retorna list[dict] no formato esperado por fines.upsert_fine.

    Levanta DetranDFSessaoExpirada se a sessão salva não autenticar mais, e
    ValueError se o carro não tiver renavam cadastrado.
    """
    if not car.renavam:
        raise ValueError(f"Carro {car.plate} não tem RENAVAM cadastrado — pulei a consulta.")

    page.goto(DEBITOS_URL)
    if _pagina_exige_login(page):
        raise DetranDFSessaoExpirada(
            "Sessão do Detran-DF expirou ou não autenticou. Rode `python detran_df_login.py` de novo."
        )

    page.get_by_placeholder("Placa").fill(car.plate.replace("-", ""))
    page.get_by_placeholder("Renavam").fill(car.renavam)
    page.get_by_role("button", name="Consultar").click()
    page.wait_for_load_state("networkidle")

    if _pagina_exige_login(page):
        raise DetranDFSessaoExpirada(
            "Sessão do Detran-DF expirou ou não autenticou. Rode `python detran_df_login.py` de novo."
        )

    return _extrair_multas_da_pagina(page, car)
