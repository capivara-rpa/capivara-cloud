from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from . import config
from .connectors import CATALOGO, CATALOGO_POR_TIPO
from .exemplos import _no

MAX_PASSOS = 20
PADRAO_SEGREDO = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})"
)


class ErroCopilot(Exception):
    pass


def _resumo_conectores() -> list[dict[str, Any]]:
    resumo = []
    for item in CATALOGO:
        campos = []
        for campo in item.get("campos") or []:
            campos.append(
                {
                    "nome": campo.get("nome"),
                    "rotulo": campo.get("rotulo"),
                    "tipo": campo.get("tipo"),
                    "obrigatorio": bool(campo.get("obrigatorio")),
                    "opcoes": campo.get("opcoes") or [],
                    "padrao": campo.get("padrao", ""),
                }
            )
        resumo.append(
            {
                "tipo": item.get("tipo"),
                "nome": item.get("nome"),
                "categoria": item.get("categoria"),
                "descricao": item.get("descricao"),
                "entradas": item.get("entradas", 1),
                "saidas": item.get("saidas", 1),
                "campos": campos,
            }
        )
    return resumo


def _instrucoes() -> str:
    catalogo = json.dumps(_resumo_conectores(), ensure_ascii=False)
    return (
        "Você é o Copilot do Capivara Cloud. Transforme a descrição do usuário em um "
        "rascunho de fluxo executável. Responda somente um objeto JSON válido, sem texto "
        "ao redor e sem markdown, com esta forma:\n"
        '{"nome":"...","descricao":"...","passos":['
        '{"tipo":"gatilho_manual","nome":"Início","config":{},"proximo":"2"}]}\n'
        "Regras obrigatórias:\n"
        "- Use somente os tipos do catálogo abaixo.\n"
        "- O primeiro passo deve ser um gatilho.\n"
        f"- No máximo {MAX_PASSOS} passos; prefira o menor número que resolva o pedido.\n"
        "- Os IDs são implícitos: o passo 1 é o primeiro da lista, o 2 o segundo.\n"
        '- "proximo" é opcional e aponta para o número do próximo passo; se omitido, '
        "a ligação segue a ordem da lista.\n"
        '- Para "condicao", use "verdadeiro" e "falso" com os números dos passos.\n'
        "- Preencha apenas campos conhecidos do conector e respeite as opções permitidas.\n"
        "- Para credenciais, use apenas um nome simbólico, nunca um segredo real.\n"
        "- Para dados dinâmicos, use {{ entrada.campo }} ou {{ passos.N.campo }}.\n"
        "- Não invente URLs de webhook nem tokens.\n"
        "- Não inclua comentários no JSON.\n\n"
        f"CATÁLOGO: {catalogo}"
    )


def _validar_base_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    partes = urlparse(url)
    if partes.scheme not in {"http", "https"} or not partes.netloc:
        raise ErroCopilot("Base URL de IA inválida. Use https://... ou http://localhost:...")
    if partes.username or partes.password:
        raise ErroCopilot("Base URL de IA não pode conter usuário ou senha.")
    if partes.scheme == "http" and (partes.hostname or "").lower() not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ErroCopilot("HTTP só é permitido em localhost. Use HTTPS para provedores remotos.")
    return url


def _erro_amigavel(resposta: httpx.Response) -> str:
    mensagem = ""
    try:
        corpo = resposta.json()
        erro = corpo.get("error") or corpo.get("detail") or corpo.get("message")
        if isinstance(erro, dict):
            erro = erro.get("message", "")
        mensagem = str(erro or "")
    except (AttributeError, ValueError):
        mensagem = resposta.text[:240]
    return f"Provider de IA retornou {resposta.status_code}: {mensagem or 'erro desconhecido'}"


def _json_de_texto(texto: str) -> dict[str, Any]:
    limpo = (texto or "").strip()
    if limpo.startswith("```"):
        partes = limpo.split("```")
        if len(partes) >= 3:
            limpo = partes[1].strip()
    if limpo.lower().startswith("json"):
        limpo = limpo[4:].strip()
    try:
        dados = json.loads(limpo)
    except (TypeError, ValueError) as exc:
        raise ErroCopilot("O modelo não devolveu um JSON válido. Tente novamente.") from exc
    if not isinstance(dados, dict):
        raise ErroCopilot("O modelo não devolveu um objeto JSON.")
    return dados


def _chamar_modelo(
    descricao: str,
    chave: str,
    modelo: str,
    base_url: str,
) -> dict[str, Any]:
    url = f"{_validar_base_url(base_url)}/chat/completions"
    cabecalhos = {"Content-Type": "application/json"}
    if config.IA_PROVIDER.strip().lower() != "ollama":
        cabecalhos["Authorization"] = f"Bearer {chave}"
    corpo = {
        "model": modelo,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _instrucoes()},
            {"role": "user", "content": descricao},
        ],
    }
    with httpx.Client(timeout=config.IA_TEMPO) as cliente:
        resposta = cliente.post(
            url,
            headers=cabecalhos,
            json={**corpo, "response_format": {"type": "json_object"}},
        )
        if resposta.status_code == 400 and "response_format" in resposta.text.lower():
            resposta = cliente.post(url, headers=cabecalhos, json=corpo)
        if not resposta.is_success:
            raise ErroCopilot(_erro_amigavel(resposta))
    try:
        dados = resposta.json()
        conteudo = dados["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ErroCopilot("A resposta do modelo veio em um formato inesperado.") from exc
    return _json_de_texto(conteudo)


def _campo_visivel(campo: dict[str, Any], config_valores: dict[str, Any]) -> bool:
    for nome, valores in (campo.get("mostrar_se") or {}).items():
        permitidos = [str(item) for item in (valores if isinstance(valores, list) else [valores])]
        if str(config_valores.get(nome, "")) not in permitidos:
            return False
    return True


def _validar_config(
    bruto: Any,
    indice: int,
    conector: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(bruto, dict):
        raise ErroCopilot(f"Passo {indice}: 'config' precisa ser um objeto JSON.")
    campos = conector.get("campos") or []
    valores = {}
    for campo in campos:
        nome = str(campo.get("nome") or "")
        if not nome:
            continue
        valor = bruto.get(nome, campo.get("padrao", ""))
        if isinstance(valor, str):
            valor = valor.strip()
            if PADRAO_SEGREDO.search(valor):
                raise ErroCopilot(
                    f"Passo {indice}: o campo '{nome}' parece conter um segredo real."
                )
        valores[nome] = valor
    resultado = {}
    for campo in campos:
        nome = str(campo.get("nome") or "")
        if not nome or not _campo_visivel(campo, valores):
            continue
        valor = valores[nome]
        rotulo = campo.get("rotulo") or nome
        if campo.get("obrigatorio") and (valor is None or valor == ""):
            raise ErroCopilot(f"Passo {indice}: o campo '{rotulo}' é obrigatório.")
        opcoes = [str(opcao) for opcao in (campo.get("opcoes") or [])]
        if opcoes and str(valor) not in opcoes:
            raise ErroCopilot(
                f"Passo {indice}: o campo '{rotulo}' aceita apenas {', '.join(opcoes)}."
            )
        if campo.get("tipo") == "number" and valor not in (None, ""):
            try:
                texto = str(valor)
                valor = float(texto) if "." in texto else int(texto)
            except (TypeError, ValueError) as exc:
                raise ErroCopilot(
                    f"Passo {indice}: o campo '{rotulo}' precisa ser numérico."
                ) from exc
        resultado[nome] = valor
    return resultado


def _categoria(conector: dict[str, Any]) -> str:
    categoria = conector.get("categoria") or ""
    if categoria == "Gatilhos":
        return "gatilho"
    if categoria == "Lógica":
        return "logica"
    return "acao"


def _tem_ciclo(arestas: list[tuple[int, str, int]]) -> bool:
    grafo: dict[int, list[int]] = {}
    for origem, _, destino in arestas:
        grafo.setdefault(origem, []).append(destino)
    visitando: dict[int, int] = {}

    def visitar(no: int) -> bool:
        if visitando.get(no) == 1:
            return True
        if visitando.get(no) == 2:
            return False
        visitando[no] = 1
        for destino in grafo.get(no, []):
            if visitar(destino):
                return True
        visitando[no] = 2
        return False

    return any(visitar(no) for no in grafo)


def compilar_grafo(passos: Any) -> dict[str, Any]:
    if not isinstance(passos, list) or not passos:
        raise ErroCopilot("O modelo não gerou passos suficientes para o fluxo.")
    if len(passos) > MAX_PASSOS:
        raise ErroCopilot(f"O fluxo gerado passou de {MAX_PASSOS} passos.")

    validados: list[dict[str, Any]] = []
    for indice, bruto in enumerate(passos, 1):
        if not isinstance(bruto, dict):
            raise ErroCopilot(f"Passo {indice}: cada passo precisa ser um objeto JSON.")
        tipo = str(bruto.get("tipo") or "").strip()
        conector = CATALOGO_POR_TIPO.get(tipo)
        if not conector:
            raise ErroCopilot(
                f"Passo {indice}: o conector '{tipo or 'vazio'}' não existe no catálogo."
            )
        if indice == 1 and not tipo.startswith("gatilho_"):
            raise ErroCopilot("O primeiro passo precisa ser um gatilho.")
        validados.append(
            {
                "id": indice,
                "tipo": tipo,
                "nome": str(bruto.get("nome") or conector.get("nome") or tipo)[:80],
                "config": _validar_config(bruto.get("config") or {}, indice, conector),
                "conector": conector,
                "bruto": bruto,
            }
        )

    ids = {item["id"] for item in validados}
    arestas: list[tuple[int, str, int]] = []

    def adicionar(origem: int, saida: str, alvo: Any, campo: str) -> None:
        try:
            destino = int(alvo)
        except (TypeError, ValueError) as exc:
            raise ErroCopilot(
                f"Passo {origem}: '{campo}' precisa ser o número de um passo."
            ) from exc
        if destino not in ids:
            raise ErroCopilot(
                f"Passo {origem}: '{campo}' aponta para o passo {destino}, que não existe."
            )
        if destino == origem:
            raise ErroCopilot(f"Passo {origem}: '{campo}' não pode apontar para ele mesmo.")
        arestas.append((origem, saida, destino))

    for item in validados:
        indice = item["id"]
        bruto = item["bruto"]
        if item["tipo"] == "condicao":
            if "verdadeiro" in bruto:
                adicionar(indice, "output_1", bruto["verdadeiro"], "verdadeiro")
            if "falso" in bruto:
                adicionar(indice, "output_2", bruto["falso"], "falso")
        elif "proximo" in bruto or indice < len(validados):
            alvo = bruto.get("proximo", indice + 1)
            adicionar(indice, "output_1", alvo, "proximo")

    if _tem_ciclo(arestas):
        raise ErroCopilot(
            "O fluxo gerado contém um ciclo. Peça um fluxo linear ou correlacione "
            "melhor os passos."
        )

    dados: dict[str, Any] = {}
    for item in validados:
        indice = item["id"]
        conector = item["conector"]
        conexoes_entrada = [
            (origem, "input_1") for origem, _, destino in arestas if destino == indice
        ]
        conexoes_saida = [
            (destino, nome_saida) for origem, nome_saida, destino in arestas if origem == indice
        ]
        dados[str(indice)] = _no(
            indice,
            item["tipo"],
            item["nome"],
            item["config"],
            120 + (indice - 1) * 300,
            220 + ((indice - 1) % 2) * 60,
            categoria=_categoria(conector),
            icone=str(conector.get("icone") or "◇"),
            entradas=int(conector.get("entradas", 1)),
            saidas=int(conector.get("saidas", 1)),
            conexoes_entrada=conexoes_entrada,
            conexoes_saida=conexoes_saida,
        )
    return {"drawflow": {"Home": {"data": dados}}}


def gerar(
    descricao: str,
    *,
    chave: str,
    modelo: str | None = None,
    base_url: str | None = None,
    nome: str | None = None,
) -> dict[str, Any]:
    if not chave or not chave.strip():
        raise ErroCopilot("Informe sua chave de IA para gerar o rascunho.")
    resposta = _chamar_modelo(
        descricao,
        chave.strip(),
        (modelo or config.IA_MODELO).strip() or config.IA_MODELO,
        (base_url or config.IA_BASE_URL).strip() or config.IA_BASE_URL,
    )
    passos = resposta.get("passos")
    grafo = compilar_grafo(passos)
    nome_final = str(nome or resposta.get("nome") or f"Fluxo gerado: {descricao[:40]}")[:120]
    descricao_final = str(resposta.get("descricao") or descricao)[:1000]
    return {
        "nome": nome_final,
        "descricao": descricao_final,
        "grafo": grafo,
        "avisos": [
            "Rascunho gerado; revise os parâmetros antes de salvar ou rodar.",
            "Nenhuma credencial secreta foi gravada pelo Copilot.",
        ],
    }
