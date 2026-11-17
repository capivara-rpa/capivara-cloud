# Conectores do Capivara Cloud

O catálogo vivo está em `GET /api/conectores` e no Swagger. Cada conector tem
`tipo`, `categoria`, `campos`, `credencial_tipo` (quando existe) e `docs`.

## Gatilhos

| Tipo | Nome | Como dispara |
| --- | --- | --- |
| `gatilho_manual` | Início manual | Botão **Rodar** no editor |
| `gatilho_webhook` | Webhook | `POST /api/webhooks/{id}` com JSON |

## Ações

| Tipo | Nome | Credencial | Observações |
| --- | --- | --- | --- |
| `http` | HTTP Request | `http` (opcional) | GET/POST/PUT/PATCH/DELETE, headers, corpo, Bearer/Basic/API key |
| `email` | E-mail | `smtp` | SMTP com TLS/SSL, HTML e anexos |
| `excel` | Excel | — | Cria/lê `.xlsx` em `data/output` |
| `slack` | Slack | `slack` (opcional) | Webhook ou Bot token + canal |
| `teams` | Microsoft Teams | — | Webhook do Teams |
| `google_sheets` | Google Sheets | `google_sheets` | OAuth refresh token |
| `telegram` | Telegram | `telegram` | Bot token + chat_id |
| `discord` | Discord | — | Webhook do Discord |
| `notion` | Notion | `notion` | Cria página em database |
| `airtable` | Airtable | `airtable` | Cria registro |
| `github` | GitHub | `github` | Cria issue |
| `stripe` | Stripe | `stripe` | Cria PaymentIntent |
| `openai` | OpenAI | `openai` | Chat Completions |
| `whatsapp` | WhatsApp Cloud | `whatsapp` | Mensagem de texto |

## Lógica

| Tipo | Nome | O que faz |
| --- | --- | --- |
| `condicao` | Condição | Compara dois valores e escolhe `output_1`/`output_2` |
| `json` | JSON | Lê, monta ou transforma JSON |
| `espera` | Espera | Aguarda N segundos |
| `log` | Log | Registra uma mensagem no trace |
| `fim` | Fim | Encerra o fluxo |

## Modelos de credencial

Os modelos prontos aparecem em `GET /api/credenciais/modelos` e no formulário de
credenciais. Exemplos:

### HTTP

```json
{
  "tipo": "bearer",
  "token": "seu-token"
}
```

Tipos aceitos: `bearer`, `basic` (`usuario`/`senha`) e `api_key`
(`nome`/`valor`).

### SMTP

```json
{
  "host": "smtp.exemplo.com",
  "porta": 587,
  "usuario": "conta@exemplo.com",
  "senha": "sua-senha",
  "remetente": "Capivara Cloud <conta@exemplo.com>",
  "tls": true
}
```

### Google Sheets

```json
{
  "client_id": "....apps.googleusercontent.com",
  "client_secret": "....",
  "refresh_token": "...."
}
```

### Slack

```json
{
  "webhook_url": "https://hooks.slack.com/services/...",
  "bot_token": "",
  "canal": "#geral"
}
```

### Telegram

```json
{
  "bot_token": "123:ABC",
  "chat_id": "123456"
}
```

### Notion

```json
{
  "token": "secret_...",
  "database_id": "...."
}
```

### Airtable

```json
{
  "token": "pat...",
  "base_id": "app...",
  "tabela": "Clientes"
}
```

### GitHub

```json
{
  "token": "ghp_...",
  "repo": "capivara-rpa/capivara-cloud"
}
```

### Stripe

```json
{
  "secret_key": "sk_test_..."
}
```

### OpenAI

```json
{
  "api_key": "sk-...",
  "modelo": "gpt-4o-mini"
}
```

### WhatsApp Cloud

```json
{
  "token": "EAAG...",
  "phone_number_id": "123456789"
}
```

## Adicionar um conector

1. Adicione uma entrada em `CATALOGO` (`app/connectors.py`) com `tipo`,
   `categoria`, `campos` e, se precisar, `credencial_tipo`/`modelo_credencial`.
2. Implemente `_seu_conector(config)` retornando um `dict` com a saída do passo.
3. Registre o handler em `HANDLERS`.
4. Adicione um teste em `tests/test_connectors.py`.
5. Atualize esta página e, se fizer sentido, proponha no repositório da
   comunidade.

## Convenções

- Use `_credencial(config.get("credencial"))` para buscar segredos.
- Use `resolver_template` no `config` antes de chamar o handler.
- Use `validar_url` em qualquer URL configurável.
- Levante `ValueError` com mensagem em português para erro de negócio.
- Devolva dados serializáveis em JSON.
- Nunca grave segredo no retorno do passo.
