import requests

import detran_df


class _FakeResponse:
    status_code = 200
    text = '{"access_token": "token"}'

    def json(self):
        return {"access_token": "token"}


class _RespostaWaf:
    status_code = 200
    text = "<html><title>Request Rejected</title></html>"

    def json(self):
        raise ValueError("HTML não é JSON")


def test_obter_token_tenta_novamente_apos_timeout(monkeypatch):
    monkeypatch.setenv("DETRAN_DF_CLIENT_ID", "client")
    monkeypatch.setenv("DETRAN_DF_CLIENT_SECRET", "secret")
    respostas = [requests.Timeout("lento"), _FakeResponse()]
    chamadas = []

    def post(*args, **kwargs):
        chamadas.append((args, kwargs))
        resposta = respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr(detran_df.requests, "post", post)
    monkeypatch.setattr(detran_df.time, "sleep", lambda segundos: None)

    assert detran_df.obter_token_servico() == "token"
    assert len(chamadas) == 2


def test_obter_token_tenta_novamente_apos_resposta_html_do_waf(monkeypatch):
    monkeypatch.setenv("DETRAN_DF_CLIENT_ID", "client")
    monkeypatch.setenv("DETRAN_DF_CLIENT_SECRET", "secret")
    respostas = [_RespostaWaf(), _FakeResponse()]
    chamadas = []

    def post(*args, **kwargs):
        chamadas.append((args, kwargs))
        return respostas.pop(0)

    monkeypatch.setattr(detran_df.requests, "post", post)
    monkeypatch.setattr(detran_df.time, "sleep", lambda segundos: None)

    assert detran_df.obter_token_servico() == "token"
    assert len(chamadas) == 2