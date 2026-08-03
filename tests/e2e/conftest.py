import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import pytest

VENV_PYTHON = sys.executable
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _porta_livre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _aguardar_servidor(url, timeout=20):
    import urllib.request
    import urllib.error

    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.3)
    return False


@pytest.fixture(scope="session")
def live_server():
    """Sobe o app Flask real (subprocess) contra um SQLite temporário, para os
    testes Playwright dirigirem um navegador de verdade contra ele."""
    porta = _porta_livre()
    db_dir = tempfile.mkdtemp()
    db_path = os.path.join(db_dir, "e2e.db").replace("\\", "/")

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["SECRET_KEY"] = "e2e-test-secret"
    env["FLASK_APP"] = "app.py"
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("WHATSAPP_TOKEN", None)

    subprocess.run(
        [VENV_PYTHON, "-m", "flask", "db", "upgrade"],
        cwd=REPO_ROOT, env=env, check=True, capture_output=True,
    )
    subprocess.run(
        [VENV_PYTHON, "-m", "flask", "create-admin", "--username", "admin", "--password", "teste1234"],
        cwd=REPO_ROOT, env=env, check=True, capture_output=True,
    )

    processo = subprocess.Popen(
        [VENV_PYTHON, "-m", "flask", "run", "--no-reload", "--no-debugger", "--port", str(porta)],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    # Drena o stdout continuamente numa thread — se ninguém ler o pipe, o buffer do SO
    # enche (os logs de requisição do Werkzeug acumulam ao longo da sessão de testes) e o
    # processo do Flask trava esperando escrever, travando a próxima requisição HTTP.
    linhas_log = []

    def _drenar_stdout():
        for linha in processo.stdout:
            linhas_log.append(linha.decode(errors="replace"))

    thread_log = threading.Thread(target=_drenar_stdout, daemon=True)
    thread_log.start()

    base_url = f"http://127.0.0.1:{porta}"
    if not _aguardar_servidor(base_url + "/login"):
        processo.terminate()
        raise RuntimeError(
            "Servidor de teste não subiu a tempo.\n" + "".join(linhas_log[-50:])
        )

    yield base_url

    processo.terminate()
    try:
        processo.wait(timeout=5)
    except subprocess.TimeoutExpired:
        processo.kill()


@pytest.fixture()
def logged_in_page(page, live_server):
    """Página do Playwright já autenticada como o admin de teste."""
    page.goto(f"{live_server}/login")
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "teste1234")
    page.click("input[type='submit']")
    page.wait_for_url(f"{live_server}/")
    return page
