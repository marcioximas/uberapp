"""Login manual no Detran Digital (portal.detran.df.gov.br) para salvar uma
sessão autenticada em disco, reaproveitada depois por detran_df_multas.py.

Roda local, na sua máquina — não em GitHub Actions (o login tem reCAPTCHA
real, exige uma pessoa resolvendo o captcha na hora).

Uso:
    python detran_df_login.py

Variáveis de ambiente (ver .env.example): DETRAN_DF_CPF, DETRAN_DF_SENHA
(opcionais — só pré-preenchem o formulário; login e captcha ainda são manuais).
"""
import detran_df

if __name__ == "__main__":
    detran_df.iniciar_login_manual()
