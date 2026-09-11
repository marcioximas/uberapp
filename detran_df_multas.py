"""
Consulta as multas/débitos de cada carro ativo (com RENAVAM cadastrado) no
Detran-DF, reaproveitando a sessão autenticada salva por detran_df_login.py.

Não faz login sozinho — se a sessão salva expirou, para e avisa pra rodar
`python detran_df_login.py` de novo (o login exige captcha humano).

Uso:
  python detran_df_multas.py            # simulação, só mostra o que encontrou
  python detran_df_multas.py --apply    # grava de fato (upsert_fine + commit)

Variáveis de ambiente: DETRAN_DF_SESSION_PATH (ver detran_df.py).
"""
import sys

from extensions import db
from models import Car
from fines import upsert_fine
import detran_df


def processar(app, apply=False):
    with app.app_context():
        try:
            p, browser, context = detran_df.carregar_sessao_ou_falhar()
        except detran_df.DetranDFError as exc:
            print(str(exc))
            sys.exit(1)

        page = context.new_page()
        carros = Car.query.filter_by(active=True).order_by(Car.plate).all()

        try:
            for carro in carros:
                if not carro.renavam:
                    print(f"{carro.plate}: sem RENAVAM cadastrado — pulei.")
                    continue

                try:
                    multas = detran_df.consultar_multas_carro(page, carro)
                except detran_df.DetranDFSessaoExpirada as exc:
                    print(f"\n{exc}")
                    sys.exit(1)
                except Exception as exc:
                    # Um carro falhar (rede, seletor mudou, etc.) não deve impedir os demais.
                    print(f"{carro.plate}: falha ao consultar — {exc}")
                    continue

                if not multas:
                    print(f"{carro.plate}: nenhuma multa encontrada.")
                    continue

                for dados in multas:
                    valor_str = f"R$ {dados['valor']:.2f}" if dados.get("valor") is not None else "valor ?"
                    print(f"{carro.plate}: AIT {dados['numero_ait']} — "
                          f"{dados.get('descricao') or '?'} — {valor_str}")
                    if apply:
                        upsert_fine(carro, dados)

                if apply:
                    db.session.commit()
                    print(f"{carro.plate}: {len(multas)} multa(s) gravada(s).")
                else:
                    print(f"{carro.plate}: {len(multas)} multa(s) encontrada(s) (simulação, sem --apply).")
        finally:
            browser.close()
            p.stop()


if __name__ == "__main__":
    aplicar = "--apply" in sys.argv
    from app import app as flask_app
    processar(flask_app, apply=aplicar)
