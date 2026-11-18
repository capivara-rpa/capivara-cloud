from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import DESCRICAO, HOST, NOME, PASTA_ESTATICOS, PORTA, VERSAO
from .connectors import CATALOGO, CONJUNTOS_ORDEM
from .engine import ErroWorkflow, executar_workflow
from .exemplos import grafo_novo
from .schemas import (
    CredencialEntrada,
    ExecucaoEntrada,
    WorkflowAtualizacao,
    WorkflowEntrada,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.iniciar_banco()
    yield


app = FastAPI(
    title=f"{NOME} API",
    version=VERSAO,
    description=DESCRICAO,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Sistema", "description": "Saúde, configuração e metadados."},
        {"name": "Conectores", "description": "Catálogo de gatilhos e ações."},
        {"name": "Workflows", "description": "CRUD e execução dos fluxos."},
        {"name": "Execuções", "description": "Histórico e trace por passo."},
        {"name": "Credenciais", "description": "Segredos cifrados em repouso."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=PASTA_ESTATICOS), name="static")


@app.get("/", include_in_schema=False)
def raiz() -> FileResponse:
    return FileResponse(PASTA_ESTATICOS / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    return RedirectResponse("/static/img/logo-capivara.svg")


@app.get("/api/health", tags=["Sistema"], summary="Saúde da aplicação")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "nome": NOME,
        "versao": VERSAO,
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@app.get("/api/config", tags=["Sistema"], summary="Configuração pública")
def configuracao() -> dict[str, Any]:
    return {
        "nome": NOME,
        "versao": VERSAO,
        "descricao": DESCRICAO,
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
        "conectores": len(CATALOGO),
    }


@app.get("/api/conectores", tags=["Conectores"], summary="Catálogo de conectores")
def conectores() -> dict[str, Any]:
    return {
        "total": len(CATALOGO),
        "conjuntos": CONJUNTOS_ORDEM,
        "conectores": CATALOGO,
    }


@app.get(
    "/api/credenciais/modelos",
    tags=["Credenciais"],
    summary="Modelos de credencial por conector",
)
def modelos_credenciais() -> list[dict[str, Any]]:
    vistos: set[str] = set()
    modelos: list[dict[str, Any]] = []
    for conector in CATALOGO:
        tipo = conector.get("credencial_tipo")
        if not tipo or tipo in vistos:
            continue
        vistos.add(tipo)
        modelos.append(
            {
                "tipo": tipo,
                "conector": conector["nome"],
                "modelo": conector.get("modelo_credencial", {}),
                "docs": conector.get("docs", ""),
            }
        )
    return modelos


@app.get("/api/estatisticas", tags=["Sistema"], summary="Resumo do painel")
def estatisticas() -> dict[str, Any]:
    return db.estatisticas()


@app.get("/api/workflows", tags=["Workflows"], summary="Lista fluxos")
def listar_workflows() -> list[dict[str, Any]]:
    return db.listar_workflows()


@app.post("/api/workflows", tags=["Workflows"], summary="Cria fluxo", status_code=201)
def criar_workflow(entrada: WorkflowEntrada) -> dict[str, Any]:
    grafo = entrada.grafo or grafo_novo()
    return db.criar_workflow(entrada.nome, entrada.descricao, grafo, entrada.ativo)


@app.get("/api/workflows/{id_workflow}", tags=["Workflows"], summary="Detalha fluxo")
def obter_workflow(id_workflow: str) -> dict[str, Any]:
    workflow = db.obter_workflow(id_workflow)
    if not workflow:
        raise HTTPException(status_code=404, detail="Fluxo não encontrado.")
    return workflow


@app.put("/api/workflows/{id_workflow}", tags=["Workflows"], summary="Atualiza fluxo")
def atualizar_workflow(id_workflow: str, entrada: WorkflowAtualizacao) -> dict[str, Any]:
    workflow = db.atualizar_workflow(
        id_workflow,
        nome=entrada.nome,
        descricao=entrada.descricao,
        grafo=entrada.grafo,
        ativo=entrada.ativo,
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Fluxo não encontrado.")
    return workflow


@app.delete("/api/workflows/{id_workflow}", tags=["Workflows"], summary="Remove fluxo")
def apagar_workflow(id_workflow: str) -> dict[str, Any]:
    if not db.apagar_workflow(id_workflow):
        raise HTTPException(status_code=404, detail="Fluxo não encontrado.")
    return {"removido": True, "id": id_workflow}


@app.post(
    "/api/workflows/{id_workflow}/executar",
    tags=["Workflows"],
    summary="Executa fluxo manualmente",
)
def executar(id_workflow: str, corpo: ExecucaoEntrada | None = None) -> dict[str, Any]:
    workflow = db.obter_workflow(id_workflow)
    if not workflow:
        raise HTTPException(status_code=404, detail="Fluxo não encontrado.")
    entrada = corpo.entrada if corpo else {}
    try:
        return executar_workflow(workflow, entrada=entrada, gatilho="manual")
    except ErroWorkflow as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/webhooks/{id_workflow}",
    tags=["Workflows"],
    summary="Dispara fluxo por webhook",
)
def webhook(
    id_workflow: str,
    corpo: Annotated[dict[str, Any] | None, Body()] = None,
) -> dict[str, Any]:
    workflow = db.obter_workflow(id_workflow)
    if not workflow:
        raise HTTPException(status_code=404, detail="Fluxo não encontrado.")
    try:
        return executar_workflow(workflow, entrada=corpo or {}, gatilho="webhook")
    except ErroWorkflow as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/execucoes", tags=["Execuções"], summary="Lista execuções")
def listar_execucoes(
    limite: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    return db.listar_execucoes(limite)


@app.get("/api/execucoes/{id_execucao}", tags=["Execuções"], summary="Detalha execução")
def obter_execucao(id_execucao: str) -> dict[str, Any]:
    execucao = db.obter_execucao(id_execucao)
    if not execucao:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return execucao


@app.get("/api/credenciais", tags=["Credenciais"], summary="Lista credenciais mascaradas")
def listar_credenciais() -> list[dict[str, Any]]:
    return db.listar_credenciais()


@app.post(
    "/api/credenciais",
    tags=["Credenciais"],
    summary="Cria credencial cifrada",
    status_code=201,
)
def criar_credencial(entrada: CredencialEntrada) -> dict[str, Any]:
    try:
        return db.criar_credencial(entrada.nome, entrada.tipo, entrada.dados)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Já existe uma credencial com esse nome."
        ) from exc


@app.delete(
    "/api/credenciais/{id_credencial}",
    tags=["Credenciais"],
    summary="Remove credencial",
)
def apagar_credencial(id_credencial: str) -> dict[str, Any]:
    if not db.apagar_credencial(id_credencial):
        raise HTTPException(status_code=404, detail="Credencial não encontrada.")
    return {"removido": True, "id": id_credencial}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORTA)


if __name__ == "__main__":
    main()
