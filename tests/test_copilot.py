from __future__ import annotations

import pytest

from app import copilot

PASSOS_SIMPLES = [
    {"tipo": "gatilho_manual", "nome": "Início", "config": {}},
    {
        "tipo": "http",
        "nome": "Buscar clientes",
        "config": {"metodo": "GET", "url": "https://api.exemplo.com/clientes"},
    },
    {"tipo": "log", "nome": "Mostrar", "config": {"mensagem": "ok"}},
]


def test_compilar_grafo_cria_nos_e_conexoes():
    grafo = copilot.compilar_grafo(PASSOS_SIMPLES)
    dados = grafo["drawflow"]["Home"]["data"]

    assert list(dados) == ["1", "2", "3"]
    assert dados["1"]["name"] == "gatilho_manual"
    assert dados["1"]["outputs"]["output_1"]["connections"][0]["node"] == "2"
    assert dados["2"]["outputs"]["output_1"]["connections"][0]["node"] == "3"
    assert dados["3"]["inputs"]["input_1"]["connections"][0]["node"] == "2"
    assert dados["2"]["data"]["config"]["timeout"] == 20


def test_compilar_rejeita_tipo_desconhecido_e_segredo():
    passos = [dict(PASSOS_SIMPLES[0]), dict(PASSOS_SIMPLES[1]), dict(PASSOS_SIMPLES[2])]
    passos[1]["tipo"] = "conector_inexistente"
    with pytest.raises(copilot.ErroCopilot, match="não existe no catálogo"):
        copilot.compilar_grafo(passos)

    passos = [dict(item) for item in PASSOS_SIMPLES]
    passos[2]["config"] = {"mensagem": "sk-abcdefghijklmnopqrstuvwxyz"}
    with pytest.raises(copilot.ErroCopilot, match="segredo real"):
        copilot.compilar_grafo(passos)


def test_compilar_respeita_condicao_e_rejeita_ciclo():
    passos = [
        {"tipo": "gatilho_webhook", "nome": "Webhook", "config": {"caminho": "pedidos"}},
        {
            "tipo": "condicao",
            "nome": "Prioridade alta?",
            "config": {"campo": "{{ entrada.prioridade }}", "operador": "==", "valor": "alta"},
            "verdadeiro": "3",
            "falso": "4",
        },
        {"tipo": "log", "nome": "Alta", "config": {"mensagem": "alta"}},
        {"tipo": "log", "nome": "Normal", "config": {"mensagem": "normal"}},
    ]
    dados = copilot.compilar_grafo(passos)["drawflow"]["Home"]["data"]
    conexoes = dados["2"]["outputs"]
    assert conexoes["output_1"]["connections"][0]["node"] == "3"
    assert conexoes["output_2"]["connections"][0]["node"] == "4"

    ciclo = [
        {"tipo": "gatilho_manual", "nome": "Início", "config": {}},
        {"tipo": "log", "nome": "A", "config": {"mensagem": "a"}, "proximo": "3"},
        {"tipo": "log", "nome": "B", "config": {"mensagem": "b"}, "proximo": "2"},
    ]
    with pytest.raises(copilot.ErroCopilot, match="ciclo"):
        copilot.compilar_grafo(ciclo)


def test_valida_base_url():
    assert copilot._validar_base_url("https://api.openai.com/v1/") == "https://api.openai.com/v1"
    assert copilot._validar_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    with pytest.raises(copilot.ErroCopilot, match="HTTP só é permitido"):
        copilot._validar_base_url("http://api.interna.local/v1")


def test_rota_copilot_exige_chave_e_gera_rascunho(cliente, monkeypatch):
    status = cliente.get("/api/copilot/status")
    assert status.status_code == 200
    assert status.json()["disponivel"] is True
    assert status.json()["servidor_configurado"] is False

    sem_chave = cliente.post("/api/copilot/gerar", json={"descricao": "Consultar uma API e logar"})
    assert sem_chave.status_code == 400
    assert "chave de IA" in sem_chave.json()["detail"]

    def modelo_falso(descricao, chave, modelo, base_url):
        assert chave == "sk-chave-de-teste"
        assert modelo == "gpt-4o-mini"
        return {
            "nome": "Fluxo da API",
            "descricao": "Fluxo gerado pela IA",
            "passos": PASSOS_SIMPLES,
        }

    monkeypatch.setattr(copilot, "_chamar_modelo", modelo_falso)
    resposta = cliente.post(
        "/api/copilot/gerar",
        headers={"X-IA-Key": "sk-chave-de-teste"},
        json={"descricao": "Consultar uma API e logar"},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["nome"] == "Fluxo da API"
    assert len(corpo["grafo"]["drawflow"]["Home"]["data"]) == 3
    assert "sk-chave-de-teste" not in str(corpo)


def test_rota_copilot_devolve_erro_do_modelo(cliente, monkeypatch):
    def modelo_com_erro(descricao, chave, modelo, base_url):
        raise copilot.ErroCopilot("Chave recusada pelo provider.")

    monkeypatch.setattr(copilot, "_chamar_modelo", modelo_com_erro)
    resposta = cliente.post(
        "/api/copilot/gerar",
        headers={"X-IA-Key": "sk-invalida"},
        json={"descricao": "Consultar uma API e logar"},
    )
    assert resposta.status_code == 400
    assert resposta.json()["detail"] == "Chave recusada pelo provider."
