from __future__ import annotations

import json
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from openpyxl import Workbook, load_workbook

from .config import PASTA_SAIDAS
from .db import obter_credencial
from .template import json_ou_texto, resolver_template, validar_url


def _campo(
    nome: str,
    rotulo: str,
    tipo: str = "text",
    *,
    placeholder: str = "",
    ajuda: str = "",
    opcoes: list[str] | None = None,
    padrao: Any = "",
    obrigatorio: bool = False,
) -> dict[str, Any]:
    return {
        "nome": nome,
        "rotulo": rotulo,
        "tipo": tipo,
        "placeholder": placeholder,
        "ajuda": ajuda,
        "opcoes": opcoes or [],
        "padrao": padrao,
        "obrigatorio": obrigatorio,
    }


CATALOGO: list[dict[str, Any]] = [
    {
        "tipo": "gatilho_manual",
        "nome": "Início manual",
        "categoria": "Gatilhos",
        "icone": "▶",
        "cor": "#1FA463",
        "descricao": "Executa o fluxo quando você clicar em Rodar.",
        "docs": "",
        "entradas": 0,
        "saidas": 1,
        "campos": [],
    },
    {
        "tipo": "gatilho_webhook",
        "nome": "Webhook",
        "categoria": "Gatilhos",
        "icone": "⇥",
        "cor": "#1FA463",
        "descricao": "Recebe um POST em /api/webhooks/{id} com o corpo JSON.",
        "docs": "https://swagger.io/docs/specification/",
        "entradas": 0,
        "saidas": 1,
        "campos": [
            _campo(
                "caminho",
                "Apelido do webhook",
                placeholder="prioridade",
                ajuda="Usado apenas como documentação no MVP.",
            )
        ],
    },
    {
        "tipo": "http",
        "nome": "HTTP Request",
        "categoria": "Ações",
        "icone": "↗",
        "cor": "#1F5FD1",
        "descricao": "Chama qualquer API REST. O canivete suíço da Capivara Cloud.",
        "docs": "https://developer.mozilla.org/pt-BR/docs/Web/HTTP",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "http",
        "modelo_credencial": {
            "tipo": "bearer",
            "token": "seu-token",
        },
        "campos": [
            _campo(
                "metodo",
                "Método",
                "select",
                opcoes=["GET", "POST", "PUT", "PATCH", "DELETE"],
                padrao="GET",
            ),
            _campo(
                "url",
                "URL",
                placeholder="https://api.exemplo.com/v1/clientes",
                obrigatorio=True,
            ),
            _campo(
                "headers",
                "Headers (JSON)",
                "textarea",
                placeholder='{"Accept": "application/json"}',
            ),
            _campo(
                "corpo",
                "Corpo (JSON ou texto)",
                "textarea",
                placeholder='{"nome": "{{ entrada.nome }}"}',
            ),
            _campo(
                "credencial",
                "Credencial",
                "credencial",
                ajuda="Opcional: Bearer, Basic ou API key.",
            ),
            _campo("timeout", "Timeout (s)", "number", padrao=20),
        ],
    },
    {
        "tipo": "email",
        "nome": "E-mail",
        "categoria": "Ações",
        "icone": "✉",
        "cor": "#9B6B43",
        "descricao": "Envia e-mail por SMTP com anexos e HTML.",
        "docs": "https://datatracker.ietf.org/doc/html/rfc5321",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "smtp",
        "modelo_credencial": {
            "host": "smtp.exemplo.com",
            "porta": 587,
            "usuario": "conta@exemplo.com",
            "senha": "sua-senha",
            "remetente": "Capivara Cloud <conta@exemplo.com>",
            "tls": True,
        },
        "campos": [
            _campo("credencial", "Credencial SMTP", "credencial", obrigatorio=True),
            _campo("para", "Para", placeholder="cliente@exemplo.com", obrigatorio=True),
            _campo("assunto", "Assunto", placeholder="Relatório diário", obrigatorio=True),
            _campo(
                "corpo",
                "Corpo",
                "textarea",
                placeholder="Olá, {{ entrada.nome }}!",
                obrigatorio=True,
            ),
            _campo("html", "Enviar como HTML", "select", opcoes=["não", "sim"], padrao="não"),
        ],
    },
    {
        "tipo": "excel",
        "nome": "Excel",
        "categoria": "Ações",
        "icone": "▦",
        "cor": "#168A52",
        "descricao": "Cria ou lê planilhas .xlsx no armazenamento local.",
        "docs": "https://openpyxl.readthedocs.io/",
        "entradas": 1,
        "saidas": 1,
        "campos": [
            _campo(
                "acao",
                "Ação",
                "select",
                opcoes=["criar", "ler"],
                padrao="criar",
            ),
            _campo(
                "caminho",
                "Arquivo",
                placeholder="relatorios/clientes.xlsx",
                obrigatorio=True,
            ),
            _campo("aba", "Aba", placeholder="Planilha1"),
            _campo(
                "dados",
                "Dados (JSON)",
                "textarea",
                placeholder='[{"nome": "Ana", "cidade": "São Paulo"}]',
                ajuda="Para criar: lista de objetos. Para ler: deixe vazio.",
            ),
        ],
    },
    {
        "tipo": "slack",
        "nome": "Slack",
        "categoria": "Ações",
        "icone": "#",
        "cor": "#4A154B",
        "descricao": "Mensagem via Incoming Webhook ou chat.postMessage.",
        "docs": "https://api.slack.com/specs",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "slack",
        "modelo_credencial": {
            "webhook_url": "https://hooks.slack.com/services/...",
        },
        "campos": [
            _campo("credencial", "Credencial Slack", "credencial"),
            _campo("webhook_url", "Webhook URL", placeholder="https://hooks.slack.com/..."),
            _campo("canal", "Canal", placeholder="#automacoes"),
            _campo("texto", "Texto", "textarea", placeholder="Deu bom: {{ entrada.nome }}"),
        ],
    },
    {
        "tipo": "teams",
        "nome": "Microsoft Teams",
        "categoria": "Ações",
        "icone": "T",
        "cor": "#5B5FC7",
        "descricao": "Envia mensagem para um canal via Incoming Webhook.",
        "docs": "https://learn.microsoft.com/graph/api/channel-post-messages",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "teams",
        "modelo_credencial": {
            "webhook_url": "https://...webhook.office.com/webhookb2/...",
        },
        "campos": [
            _campo("credencial", "Credencial Teams", "credencial"),
            _campo("webhook_url", "Webhook URL"),
            _campo("titulo", "Título", placeholder="Capivara Cloud"),
            _campo("texto", "Texto", "textarea", placeholder="Novo pedido: {{ entrada.id }}"),
        ],
    },
    {
        "tipo": "google_sheets",
        "nome": "Google Sheets",
        "categoria": "Ações",
        "icone": "G",
        "cor": "#0F9D58",
        "descricao": "Lê ou adiciona linhas em uma planilha via API v4.",
        "docs": "https://developers.google.com/sheets/api/reference/rest",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "google",
        "modelo_credencial": {
            "service_account_json": (
                '{"type":"service_account","project_id":"...",'
                '"client_email":"...","private_key":"..."}'
            ),
        },
        "campos": [
            _campo("credencial", "Conta de serviço", "credencial", obrigatorio=True),
            _campo("spreadsheet_id", "Spreadsheet ID", obrigatorio=True),
            _campo("range", "Range", placeholder="Página1!A1", obrigatorio=True),
            _campo("acao", "Ação", "select", opcoes=["append", "read"], padrao="append"),
            _campo(
                "valores",
                "Valores (JSON)",
                "textarea",
                placeholder='[["Ana", "SP"]] ou [{"nome":"Ana","uf":"SP"}]',
            ),
        ],
    },
    {
        "tipo": "telegram",
        "nome": "Telegram",
        "categoria": "Ações",
        "icone": "➤",
        "cor": "#229ED9",
        "descricao": "Envia mensagem via Bot API.",
        "docs": "https://core.telegram.org/bots/api",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "telegram",
        "modelo_credencial": {"bot_token": "123456:ABC..."},
        "campos": [
            _campo("credencial", "Credencial Telegram", "credencial", obrigatorio=True),
            _campo("chat_id", "Chat ID", obrigatorio=True),
            _campo("texto", "Texto", "textarea", obrigatorio=True),
        ],
    },
    {
        "tipo": "discord",
        "nome": "Discord",
        "categoria": "Ações",
        "icone": "◉",
        "cor": "#5865F2",
        "descricao": "Mensagem via webhook de canal.",
        "docs": "https://discord.com/developers/docs/resources/webhook",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "discord",
        "modelo_credencial": {"webhook_url": "https://discord.com/api/webhooks/..."},
        "campos": [
            _campo("credencial", "Credencial Discord", "credencial"),
            _campo("webhook_url", "Webhook URL"),
            _campo("conteudo", "Conteúdo", "textarea", obrigatorio=True),
        ],
    },
    {
        "tipo": "notion",
        "nome": "Notion",
        "categoria": "Ações",
        "icone": "N",
        "cor": "#111111",
        "descricao": "Cria uma página em um database do Notion.",
        "docs": "https://developers.notion.com/reference",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "notion",
        "modelo_credencial": {"token": "secret_..."},
        "campos": [
            _campo("credencial", "Credencial Notion", "credencial", obrigatorio=True),
            _campo("database_id", "Database ID", obrigatorio=True),
            _campo(
                "propriedades",
                "Propriedades (JSON)",
                "textarea",
                placeholder='{"Nome": {"title": [{"text": {"content": "{{ entrada.nome }}"}}]}}',
            ),
        ],
    },
    {
        "tipo": "airtable",
        "nome": "Airtable",
        "categoria": "Ações",
        "icone": "A",
        "cor": "#FCB400",
        "descricao": "Cria um registro em uma tabela.",
        "docs": "https://airtable.com/developers/web/api/introduction",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "airtable",
        "modelo_credencial": {"token": "pat..."},
        "campos": [
            _campo("credencial", "Credencial Airtable", "credencial", obrigatorio=True),
            _campo("base_id", "Base ID", obrigatorio=True),
            _campo("tabela", "Tabela", obrigatorio=True),
            _campo("campos", "Campos (JSON)", "textarea", obrigatorio=True),
        ],
    },
    {
        "tipo": "github",
        "nome": "GitHub",
        "categoria": "Ações",
        "icone": "⌂",
        "cor": "#24292F",
        "descricao": "Abre uma issue em um repositório.",
        "docs": "https://docs.github.com/en/rest",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "github",
        "modelo_credencial": {"token": "ghp_..."},
        "campos": [
            _campo("credencial", "Credencial GitHub", "credencial", obrigatorio=True),
            _campo("repo", "Repositório", placeholder="capivara-rpa/capivara", obrigatorio=True),
            _campo("titulo", "Título", obrigatorio=True),
            _campo("corpo", "Corpo", "textarea"),
            _campo("labels", "Labels (JSON)", "textarea", placeholder='["automacao"]'),
        ],
    },
    {
        "tipo": "stripe",
        "nome": "Stripe",
        "categoria": "Ações",
        "icone": "S",
        "cor": "#635BFF",
        "descricao": "Cria um PaymentIntent.",
        "docs": "https://stripe.com/docs/api",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "stripe",
        "modelo_credencial": {"secret_key": "sk_test_..."},
        "campos": [
            _campo("credencial", "Credencial Stripe", "credencial", obrigatorio=True),
            _campo("valor", "Valor em centavos", "number", padrao=1000, obrigatorio=True),
            _campo("moeda", "Moeda", placeholder="brl", padrao="brl"),
            _campo("descricao", "Descrição"),
            _campo("email", "E-mail do cliente"),
        ],
    },
    {
        "tipo": "openai",
        "nome": "OpenAI",
        "categoria": "Ações",
        "icone": "✳",
        "cor": "#10A37F",
        "descricao": "Gera texto com Chat Completions.",
        "docs": "https://platform.openai.com/docs/api-reference",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "openai",
        "modelo_credencial": {"api_key": "sk-..."},
        "campos": [
            _campo("credencial", "Credencial OpenAI", "credencial", obrigatorio=True),
            _campo("modelo", "Modelo", placeholder="gpt-4o-mini", padrao="gpt-4o-mini"),
            _campo("system", "System prompt", "textarea"),
            _campo("prompt", "Prompt", "textarea", obrigatorio=True),
        ],
    },
    {
        "tipo": "whatsapp",
        "nome": "WhatsApp Cloud",
        "categoria": "Ações",
        "icone": "W",
        "cor": "#25D366",
        "descricao": "Envia texto pela WhatsApp Cloud API (Meta).",
        "docs": "https://developers.facebook.com/docs/whatsapp/cloud-api/reference",
        "entradas": 1,
        "saidas": 1,
        "credencial_tipo": "whatsapp",
        "modelo_credencial": {"token": "EAAG...", "phone_number_id": "1234567890"},
        "campos": [
            _campo("credencial", "Credencial WhatsApp", "credencial", obrigatorio=True),
            _campo("phone_number_id", "Phone Number ID"),
            _campo("para", "Para", placeholder="5511999999999", obrigatorio=True),
            _campo("texto", "Texto", "textarea", obrigatorio=True),
        ],
    },
    {
        "tipo": "condicao",
        "nome": "Condição",
        "categoria": "Lógica",
        "icone": "◇",
        "cor": "#FFD84D",
        "descricao": "Dois caminhos: verdadeiro (saída 1) ou falso (saída 2).",
        "docs": "",
        "entradas": 1,
        "saidas": 2,
        "campos": [
            _campo("campo", "Campo", placeholder="{{ entrada.prioridade }}", obrigatorio=True),
            _campo(
                "operador",
                "Operador",
                "select",
                opcoes=["==", "!=", ">", "<", ">=", "<=", "contem", "vazio", "nao_vazio"],
                padrao="==",
            ),
            _campo("valor", "Valor", placeholder="alta"),
        ],
    },
    {
        "tipo": "json",
        "nome": "JSON",
        "categoria": "Lógica",
        "icone": "{ }",
        "cor": "#1F5FD1",
        "descricao": "Extrai um caminho, faz parse ou stringify.",
        "docs": "https://www.json.org/json-pt.html",
        "entradas": 1,
        "saidas": 1,
        "campos": [
            _campo(
                "acao",
                "Ação",
                "select",
                opcoes=["extrair", "parse", "stringify"],
                padrao="extrair",
            ),
            _campo("texto", "Entrada", "textarea", placeholder="{{ passos.2.json }}"),
            _campo("caminho", "Caminho", placeholder="data.clientes.0.nome"),
        ],
    },
    {
        "tipo": "espera",
        "nome": "Espera",
        "categoria": "Lógica",
        "icone": "◷",
        "cor": "#9B6B43",
        "descricao": "Pausa o fluxo por alguns segundos (máximo 30 no MVP).",
        "docs": "",
        "entradas": 1,
        "saidas": 1,
        "campos": [_campo("segundos", "Segundos", "number", padrao=2)],
    },
    {
        "tipo": "log",
        "nome": "Log",
        "categoria": "Lógica",
        "icone": "≡",
        "cor": "#6B6357",
        "descricao": "Registra uma mensagem no trace da execução.",
        "docs": "",
        "entradas": 1,
        "saidas": 1,
        "campos": [
            _campo(
                "mensagem",
                "Mensagem",
                "textarea",
                placeholder="Processado: {{ entrada.nome }}",
                obrigatorio=True,
            )
        ],
    },
    {
        "tipo": "fim",
        "nome": "Fim",
        "categoria": "Lógica",
        "icone": "■",
        "cor": "#6B6357",
        "descricao": "Encerra o fluxo com sucesso.",
        "docs": "",
        "entradas": 1,
        "saidas": 0,
        "campos": [],
    },
]

CATALOGO_POR_TIPO = {item["tipo"]: item for item in CATALOGO}


def _credencial(nome: str | None) -> dict[str, Any]:
    if not nome:
        return {}
    registro = obter_credencial(nome, mascarar_dados=False)
    if not registro:
        raise ValueError(f"Credencial '{nome}' não encontrada.")
    return registro.get("dados", {})


def _timeout(config: dict[str, Any]) -> float:
    try:
        return max(1.0, min(float(config.get("timeout") or 20), 60.0))
    except (TypeError, ValueError):
        return 20.0


def _http(config: dict[str, Any]) -> dict[str, Any]:
    url = str(config.get("url") or "").strip()
    if not url:
        raise ValueError("Informe a URL da requisição.")
    validar_url(url)
    metodo = str(config.get("metodo") or "GET").upper()
    headers = json_ou_texto(config.get("headers"), {}) or {}
    if not isinstance(headers, dict):
        raise ValueError("Headers precisam ser um objeto JSON.")
    corpo = json_ou_texto(config.get("corpo"), None)
    cred = _credencial(config.get("credencial"))
    auth = None
    if cred:
        tipo = str(cred.get("tipo") or "bearer").lower()
        if tipo == "basic":
            auth = (str(cred.get("usuario", "")), str(cred.get("senha", "")))
        elif tipo == "api_key":
            headers[str(cred.get("nome") or "X-API-Key")] = str(cred.get("valor", ""))
        elif cred.get("token"):
            headers.setdefault("Authorization", f"Bearer {cred['token']}")
    kwargs: dict[str, Any] = {
        "method": metodo,
        "url": url,
        "headers": headers,
        "timeout": _timeout(config),
        "follow_redirects": True,
    }
    if auth:
        kwargs["auth"] = auth
    if corpo not in (None, "") and metodo not in {"GET", "HEAD"}:
        if isinstance(corpo, (dict, list)):
            kwargs["json"] = corpo
        else:
            kwargs["content"] = str(corpo)
    with httpx.Client() as cliente:
        resposta = cliente.request(**kwargs)
    texto = resposta.text[:20000]
    try:
        dados = resposta.json()
    except ValueError:
        dados = None
    if resposta.status_code >= 400:
        raise ValueError(f"HTTP {resposta.status_code}: {texto[:800]}")
    return {
        "status": resposta.status_code,
        "content_type": resposta.headers.get("content-type", ""),
        "json": dados,
        "texto": texto,
    }


def _email(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    if not cred:
        raise ValueError("Selecione uma credencial SMTP.")
    host = str(cred.get("host") or "")
    porta = int(cred.get("porta") or 587)
    usuario = str(cred.get("usuario") or "")
    senha = str(cred.get("senha") or "")
    remetente = str(cred.get("remetente") or usuario)
    if not host or not usuario:
        raise ValueError("Credencial SMTP precisa de host e usuário.")
    mensagem = EmailMessage()
    mensagem["From"] = remetente
    mensagem["To"] = str(config.get("para") or "")
    mensagem["Subject"] = str(config.get("assunto") or "")
    corpo = str(config.get("corpo") or "")
    if str(config.get("html") or "não").lower() in {"sim", "true", "1"}:
        mensagem.set_content("Seu cliente de e-mail não suporta HTML.")
        mensagem.add_alternative(corpo, subtype="html")
    else:
        mensagem.set_content(corpo)
    contexto = ssl.create_default_context()
    if porta == 465 or cred.get("ssl"):
        with smtplib.SMTP_SSL(host, porta, context=contexto, timeout=20) as smtp:
            smtp.login(usuario, senha)
            smtp.send_message(mensagem)
    else:
        with smtplib.SMTP(host, porta, timeout=20) as smtp:
            if cred.get("tls", True):
                smtp.starttls(context=contexto)
            smtp.login(usuario, senha)
            smtp.send_message(mensagem)
    return {"enviado": True, "para": mensagem["To"], "assunto": mensagem["Subject"]}


def _caminho_seguro(caminho: str) -> Path:
    relativo = Path(str(caminho or "").strip())
    if not relativo.name:
        raise ValueError("Informe o arquivo Excel.")
    destino = (PASTA_SAIDAS / relativo).resolve()
    if PASTA_SAIDAS.resolve() not in destino.parents and destino != PASTA_SAIDAS.resolve():
        raise ValueError("O arquivo precisa ficar dentro de data/output.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    return destino


def _excel(config: dict[str, Any]) -> dict[str, Any]:
    acao = str(config.get("acao") or "criar").lower()
    destino = _caminho_seguro(str(config.get("caminho") or "planilha.xlsx"))
    if acao == "ler":
        if not destino.exists():
            raise ValueError(f"Arquivo não encontrado: {destino.name}")
        livro = load_workbook(destino, data_only=True)
        aba = str(config.get("aba") or "").strip()
        planilha = livro[aba] if aba and aba in livro.sheetnames else livro.active
        linhas = list(planilha.iter_rows(values_only=True))
        if not linhas:
            return {"arquivo": destino.name, "linhas": []}
        cabecalho = [str(valor or "") for valor in linhas[0]]
        dados = [
            {cabecalho[i]: linha[i] for i in range(len(cabecalho))}
            for linha in linhas[1:]
        ]
        return {"arquivo": destino.name, "aba": planilha.title, "linhas": dados}
    dados = json_ou_texto(config.get("dados"), [])
    if not isinstance(dados, list):
        raise ValueError("Os dados do Excel precisam ser uma lista de objetos.")
    livro = Workbook()
    planilha = livro.active
    if str(config.get("aba") or "").strip():
        planilha.title = str(config["aba"]).strip()[:31]
    if dados and isinstance(dados[0], dict):
        cabecalho = list(dados[0].keys())
        planilha.append(cabecalho)
        for item in dados:
            planilha.append([item.get(coluna) for coluna in cabecalho])
    else:
        for linha in dados:
            planilha.append(linha if isinstance(linha, list) else [linha])
    livro.save(destino)
    return {"arquivo": destino.name, "aba": planilha.title, "linhas": len(dados)}


def _slack(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    webhook = str(config.get("webhook_url") or cred.get("webhook_url") or "").strip()
    texto = str(config.get("texto") or "")
    if webhook:
        validar_url(webhook)
        resposta = httpx.post(webhook, json={"text": texto}, timeout=20)
        resposta.raise_for_status()
        return {"enviado": True, "via": "webhook", "status": resposta.status_code}
    token = str(cred.get("bot_token") or cred.get("token") or "")
    if not token:
        raise ValueError("Informe webhook_url ou uma credencial com bot_token.")
    resposta = httpx.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": str(config.get("canal") or ""), "text": texto},
        timeout=20,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    if not dados.get("ok"):
        raise ValueError(f"Slack recusou: {dados.get('error', 'erro desconhecido')}")
    return {"enviado": True, "via": "api", "ts": dados.get("ts")}


def _teams(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    webhook = str(config.get("webhook_url") or cred.get("webhook_url") or "").strip()
    if not webhook:
        raise ValueError("Informe o webhook do Teams.")
    validar_url(webhook)
    titulo = str(config.get("titulo") or "Capivara Cloud")
    texto = str(config.get("texto") or "")
    resposta = httpx.post(
        webhook,
        json={"text": f"**{titulo}**\n\n{texto}"},
        timeout=20,
    )
    resposta.raise_for_status()
    return {"enviado": True, "status": resposta.status_code}


def _google_sheets(config: dict[str, Any]) -> dict[str, Any]:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    cred = _credencial(config.get("credencial"))
    bruto = cred.get("service_account_json") or cred.get("json") or cred
    info = json.loads(bruto) if isinstance(bruto, str) else bruto
    if not isinstance(info, dict) or not info.get("client_email"):
        raise ValueError("Credencial Google precisa do JSON da conta de serviço.")
    credenciais = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    credenciais.refresh(Request())
    headers = {"Authorization": f"Bearer {credenciais.token}"}
    spreadsheet = str(config.get("spreadsheet_id") or "")
    range_ = str(config.get("range") or "")
    if not spreadsheet or not range_:
        raise ValueError("Informe spreadsheet_id e range.")
    valores = quote(range_, safe="")
    base = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{spreadsheet}/values/{valores}"
    )
    acao = str(config.get("acao") or "append").lower()
    if acao == "read":
        resposta = httpx.get(base, headers=headers, timeout=30)
        resposta.raise_for_status()
        return {"valores": resposta.json().get("values", [])}
    valores = json_ou_texto(config.get("valores"), [])
    if isinstance(valores, list) and valores and isinstance(valores[0], dict):
        cabecalho = list(valores[0].keys())
        valores = [cabecalho] + [[item.get(coluna) for coluna in cabecalho] for item in valores]
    resposta = httpx.post(
        f"{base}:append",
        headers=headers,
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": valores},
        timeout=30,
    )
    resposta.raise_for_status()
    return resposta.json()


def _telegram(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    token = str(cred.get("bot_token") or cred.get("token") or "")
    if not token:
        raise ValueError("Credencial Telegram sem bot_token.")
    resposta = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": str(config.get("chat_id") or ""), "text": str(config.get("texto") or "")},
        timeout=20,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    if not dados.get("ok"):
        raise ValueError("Telegram recusou a mensagem.")
    return {"enviado": True, "message_id": dados.get("result", {}).get("message_id")}


def _discord(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    webhook = str(config.get("webhook_url") or cred.get("webhook_url") or "").strip()
    if not webhook:
        raise ValueError("Informe o webhook do Discord.")
    validar_url(webhook)
    resposta = httpx.post(
        webhook,
        json={"content": str(config.get("conteudo") or "")},
        timeout=20,
    )
    resposta.raise_for_status()
    return {"enviado": True, "status": resposta.status_code}


def _notion(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    token = str(cred.get("token") or cred.get("api_key") or "")
    if not token:
        raise ValueError("Credencial Notion sem token.")
    propriedades = json_ou_texto(config.get("propriedades"), {})
    resposta = httpx.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json={
            "parent": {"database_id": str(config.get("database_id") or "")},
            "properties": propriedades,
        },
        timeout=30,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    return {"id": dados.get("id"), "url": dados.get("url")}


def _airtable(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    token = str(cred.get("token") or cred.get("api_key") or "")
    base_id = str(config.get("base_id") or "")
    tabela = str(config.get("tabela") or "")
    if not token or not base_id or not tabela:
        raise ValueError("Informe credencial, base_id e tabela do Airtable.")
    resposta = httpx.post(
        f"https://api.airtable.com/v0/{base_id}/{quote(tabela, safe='')}",
        headers={"Authorization": f"Bearer {token}"},
        json={"fields": json_ou_texto(config.get("campos"), {})},
        timeout=30,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    return {"id": dados.get("id"), "createdTime": dados.get("createdTime")}


def _github(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    token = str(cred.get("token") or cred.get("api_key") or "")
    repo = str(config.get("repo") or "")
    if not token or not repo:
        raise ValueError("Informe credencial e repositório do GitHub.")
    resposta = httpx.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "title": str(config.get("titulo") or ""),
            "body": str(config.get("corpo") or ""),
            "labels": json_ou_texto(config.get("labels"), []),
        },
        timeout=30,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    return {"numero": dados.get("number"), "url": dados.get("html_url")}


def _stripe(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    chave = str(cred.get("secret_key") or cred.get("token") or "")
    if not chave:
        raise ValueError("Credencial Stripe sem secret_key.")
    dados = {
        "amount": int(config.get("valor") or 0),
        "currency": str(config.get("moeda") or "brl"),
        "automatic_payment_methods[enabled]": "true",
    }
    if config.get("descricao"):
        dados["description"] = str(config["descricao"])
    if config.get("email"):
        dados["receipt_email"] = str(config["email"])
    resposta = httpx.post(
        "https://api.stripe.com/v1/payment_intents",
        auth=(chave, ""),
        data=dados,
        timeout=30,
    )
    resposta.raise_for_status()
    retorno = resposta.json()
    return {
        "id": retorno.get("id"),
        "status": retorno.get("status"),
        "valor": retorno.get("amount"),
    }


def _openai(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    chave = str(cred.get("api_key") or cred.get("token") or "")
    if not chave:
        raise ValueError("Credencial OpenAI sem api_key.")
    mensagens = []
    if config.get("system"):
        mensagens.append({"role": "system", "content": str(config["system"])})
    mensagens.append({"role": "user", "content": str(config.get("prompt") or "")})
    resposta = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {chave}"},
        json={"model": str(config.get("modelo") or "gpt-4o-mini"), "messages": mensagens},
        timeout=60,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    return {
        "texto": dados["choices"][0]["message"]["content"],
        "modelo": dados.get("model"),
        "tokens": dados.get("usage", {}).get("total_tokens"),
    }


def _whatsapp(config: dict[str, Any]) -> dict[str, Any]:
    cred = _credencial(config.get("credencial"))
    token = str(cred.get("token") or cred.get("access_token") or "")
    phone_id = str(config.get("phone_number_id") or cred.get("phone_number_id") or "")
    if not token or not phone_id:
        raise ValueError("Informe token e phone_number_id do WhatsApp.")
    resposta = httpx.post(
        f"https://graph.facebook.com/v20.0/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messaging_product": "whatsapp",
            "to": str(config.get("para") or ""),
            "type": "text",
            "text": {"body": str(config.get("texto") or "")},
        },
        timeout=30,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    mensagens = dados.get("messages", [])
    return {"enviado": True, "id": mensagens[0].get("id") if mensagens else None}


def _condicao(config: dict[str, Any]) -> dict[str, Any]:
    campo = config.get("campo")
    valor = config.get("valor")
    operador = str(config.get("operador") or "==").lower()
    if operador == "vazio":
        resultado = campo in (None, "", [], {})
    elif operador == "nao_vazio":
        resultado = campo not in (None, "", [], {})
    elif operador == "contem":
        resultado = str(valor).lower() in str(campo).lower()
    else:
        try:
            esquerda = float(campo)  # type: ignore[arg-type]
            direita = float(valor)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            esquerda, direita = str(campo), str(valor)
        resultado = {
            "==": esquerda == direita,
            "!=": esquerda != direita,
            ">": esquerda > direita,
            "<": esquerda < direita,
            ">=": esquerda >= direita,
            "<=": esquerda <= direita,
        }.get(operador, False)
    return {"resultado": bool(resultado), "campo": campo, "valor": valor, "operador": operador}


def _json(config: dict[str, Any]) -> dict[str, Any]:
    acao = str(config.get("acao") or "extrair").lower()
    texto = config.get("texto")
    if acao == "parse":
        return {"resultado": json_ou_texto(texto, texto)}
    if acao == "stringify":
        return {"resultado": json.dumps(texto, ensure_ascii=False)}
    caminho = str(config.get("caminho") or "")
    atual = json_ou_texto(texto, texto)
    for parte in caminho.split("."):
        if not parte:
            continue
        if isinstance(atual, dict):
            atual = atual.get(parte)
        elif isinstance(atual, list) and parte.isdigit():
            atual = atual[int(parte)] if int(parte) < len(atual) else None
        else:
            atual = None
    return {"resultado": atual}


def executar(tipo: str, config: dict[str, Any], contexto: dict[str, Any]) -> dict[str, Any]:
    config = resolver_template(config, contexto)
    if tipo in {"gatilho_manual", "gatilho_webhook"}:
        return {"gatilho": tipo, "entrada": contexto.get("entrada", {})}
    if tipo == "http":
        return _http(config)
    if tipo == "email":
        return _email(config)
    if tipo == "excel":
        return _excel(config)
    if tipo == "slack":
        return _slack(config)
    if tipo == "teams":
        return _teams(config)
    if tipo == "google_sheets":
        return _google_sheets(config)
    if tipo == "telegram":
        return _telegram(config)
    if tipo == "discord":
        return _discord(config)
    if tipo == "notion":
        return _notion(config)
    if tipo == "airtable":
        return _airtable(config)
    if tipo == "github":
        return _github(config)
    if tipo == "stripe":
        return _stripe(config)
    if tipo == "openai":
        return _openai(config)
    if tipo == "whatsapp":
        return _whatsapp(config)
    if tipo == "condicao":
        return _condicao(config)
    if tipo == "json":
        return _json(config)
    if tipo == "espera":
        segundos = max(0, min(float(config.get("segundos") or 0), 30))
        time.sleep(segundos)
        return {"segundos": segundos}
    if tipo == "log":
        return {"mensagem": str(config.get("mensagem") or "")}
    if tipo == "fim":
        return {"fim": True}
    raise ValueError(f"Tipo de nó desconhecido: {tipo}")
