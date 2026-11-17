from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

NOME = "Capivara Cloud"
VERSAO = "0.1.0"
DESCRICAO = (
    "Automação de APIs em português, com workflows visuais, conectores, "
    "credenciais cifradas e execução observável."
)

PASTA_DADOS = Path(os.getenv("CAPIVARA_CLOUD_DATA", RAIZ / "data")).resolve()
PASTA_DADOS.mkdir(parents=True, exist_ok=True)
PASTA_SAIDAS = PASTA_DADOS / "output"
PASTA_SAIDAS.mkdir(parents=True, exist_ok=True)

BANCO = Path(os.getenv("CAPIVARA_CLOUD_BANCO", PASTA_DADOS / "cloud.db"))
CHAVE_ARQUIVO = Path(os.getenv("CAPIVARA_CLOUD_CHAVE", PASTA_DADOS / "cloud.key"))
PASTA_ESTATICOS = RAIZ / "app" / "static"

HOST = os.getenv("CAPIVARA_CLOUD_HOST", "127.0.0.1")
PORTA = int(os.getenv("CAPIVARA_CLOUD_PORTA", "8787"))
PERMITIR_REDE_LOCAL = os.getenv(
    "CAPIVARA_CLOUD_PERMITIR_REDE_LOCAL", "false"
).strip().lower() in {"1", "true", "sim", "yes"}
