"""
Consulta as multas de cada carro ativo (com chassi cadastrado) no Detran-DF
via HTTP direto (ver detran_df.py) e grava em Fine (fines.upsert_fine).

Não precisa de login, captcha nem sessão — usa uma credencial de serviço
(client_credentials) pública do próprio site do Detran-DF.

Uso:
  python detran_df_multas.py            # simulação, só mostra o que encontrou
  python detran_df_multas.py --apply    # grava de fato (upsert_fine + commit)

Variáveis de ambiente: DETRAN_DF_CLIENT_ID, DETRAN_DF_CLIENT_SECRET (ver detran_df.py).
"""
import sys

from extensions import db
from models import Car
from fines import upsert_fine
import detran_df


def processar(app, apply=False):
    with app.app_context():
        try:
            token = detran_df.obter_token_servico()
        except detran_df.DetranDFError as exc:
            print(str(exc))
            sys.exit(1)

        carros = Car.query.filter_by(active=True).order_by(Car.plate).all()

        for carro in carros:
            if not carro.chassi:
                print(f"{carro.plate}: sem chassi cadastrado — pulei.")
                continue

            try:
                multas = detran_df.consultar_multas_carro(carro, token=token)
            except Exception as exc:
                # Um carro falhar (rede, chassi errado, etc.) não deve impedir os demais.
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


if __name__ == "__main__":
    aplicar = "--apply" in sys.argv
    from app import app as flask_app
    processar(flask_app, apply=aplicar)
