from __future__ import annotations

import pytest

from app.connectors import executar


def test_log_retorna_mensagem():
    saida = executar("log", {"mensagem": "Olá, Capivara!"}, {})
    assert saida["mensagem"] == "Olá, Capivara!"


def test_condicao_verdadeira_e_falsa():
    assert executar("condicao", {"campo": "a", "operador": "==", "valor": "a"}, {})[
        "resultado"
    ] is True
    assert executar("condicao", {"campo": "a", "operador": "!=", "valor": "a"}, {})[
        "resultado"
    ] is False


def test_json_faz_parse_e_extrai_caminho():
    lido = executar("json", {"acao": "parse", "texto": '{"a": 1, "b": 2}'}, {})
    assert lido["resultado"] == {"a": 1, "b": 2}

    extraido = executar(
        "json",
        {"acao": "extrair", "texto": '{"cliente": {"nome": "Arthur"}}', "caminho": "cliente.nome"},
        {},
    )
    assert extraido["resultado"] == "Arthur"


def test_http_bloqueia_localhost_por_padrao():
    with pytest.raises(ValueError, match="local|privad|permitid"):
        executar("http", {"url": "http://127.0.0.1:8787/api/health"}, {})
