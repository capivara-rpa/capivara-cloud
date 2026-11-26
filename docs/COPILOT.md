# Copilot de fluxos (BYOK)

O Copilot transforma uma descrição em português em um **rascunho de fluxo
Drawflow**. Ele não escreve código livre e não executa o fluxo automaticamente:
gera uma lista de passos, valida cada conector/campo contra o catálogo e cria um
novo workflow para você revisar antes de salvar ou rodar.

## Gerar uma chave de IA

1. Acesse <https://platform.openai.com/api-keys>.
2. Entre na sua conta e clique em **Create new secret key**.
3. Dê um nome curto (ex.: `capivara-cloud-local`), copie o valor `sk-...` e
   guarde em um cofre. A chave aparece uma única vez no provedor.
4. No Capivara Cloud, abra **Fluxos → Gerar com IA** e cole a chave no campo
   **Chave de IA (BYOK)**.

Não coloque a chave no código, no `.env` versionado, em prints ou no chat. Se
ela vazar, revogue imediatamente no provedor e gere outra.

## Usar na interface

1. Abra `http://127.0.0.1:8787/#fluxos`.
2. Clique em **Gerar com IA**.
3. Descreva o processo, por exemplo:

   > Receber um webhook com `prioridade`, consultar uma API e enviar o resultado
   > para um canal do Slack.

4. Informe a chave e, se quiser, um modelo diferente do padrão.
5. Clique em **Gerar rascunho**.
6. O Cloud cria um novo fluxo, abre o canvas e marca o status como
   **alterações não salvas**. Revise os nós e clique em **Salvar** quando
   aprovar.

A chave marcada como **Guardar nesta sessão** fica apenas no
`sessionStorage` do navegador e é removida ao fechar a janela. Sem essa opção,
o campo é limpo ao fechar o diálogo.

## Segurança e privacidade

- A chave vai no cabeçalho `X-IA-Key` da chamada `POST /api/copilot/gerar`.
  Ela não entra no corpo da requisição, não é gravada no SQLite e não aparece
  no trace.
- O selo no topo do editor mostra a origem: **IA: sua chave** ou **IA: servidor**.
- O prompt inclui o catálogo de conectores e a sua descrição. Não inclui
  credenciais cifradas nem valores do banco.
- O modelo é obrigado a devolver JSON com `nome`, `descricao` e `passos`.
- O compilador rejeita conector inexistente, campo obrigatório vazio, opção
  inválida, segredo literal, ponteiro de passo inexistente e ciclos.
- Referências dinâmicas devem usar `{{ entrada.campo }}` ou
  `{{ passos.N.campo }}`. Para credenciais, o modelo usa apenas um nome
  simbólico (ex.: `slack_principal`), que você configura depois em
  **Credenciais**.
- O fluxo gerado **não é executado** pelo Copilot.

## Chave no servidor (opcional)

Se quiser que todos os usuários da instância usem a mesma chave, configure no
`.env`:

```env
CAPIVARA_AI_KEY=sk-...
```

Nesse caso o campo da UI pode ficar vazio e a chave do servidor é usada. Isso
centraliza o custo e o risco de abuso em quem administra o servidor; por isso o
padrão recomendado é BYOK.

## Outros provedores compatíveis

O adapter usa a API de chat no formato OpenAI. Ajuste no `.env`:

```env
CAPIVARA_IA_PROVIDER=openai
CAPIVARA_IA_BASE_URL=https://api.openai.com/v1
CAPIVARA_IA_MODELO=gpt-4o-mini
CAPIVARA_IA_TIMEOUT=60
```

Para Ollama local, por exemplo:

```env
CAPIVARA_IA_PROVIDER=ollama
CAPIVARA_IA_BASE_URL=http://localhost:11434/v1
CAPIVARA_IA_MODELO=llama3.1
```

Com `provider=ollama`, o cabeçalho `Authorization` não é enviado; você pode
colocar `local` no campo da UI apenas para habilitar o botão. URLs `http` só
são aceitas em `localhost`/`127.0.0.1`; provedores remotos precisam de `https`.

## API

```bash
curl -X POST http://127.0.0.1:8787/api/copilot/gerar \
  -H "Content-Type: application/json" \
  -H "X-IA-Key: $OPENAI_API_KEY" \
  -d '{"descricao":"Receber webhook, consultar API e logar o resultado"}'
```

`GET /api/copilot/status` mostra o provedor, o modelo e se existe chave no
servidor, sem devolver nenhum segredo.

## Limitações da versão 1

- Gera um fluxo novo; ainda não reformula o fluxo aberto por chat.
- Não consulta a documentação dos conectores como RAG; usa o catálogo curto.
- Não faz simulação/dry-run automático além da validação estrutural.
- Limite de 20 passos por rascunho.
- A qualidade depende do modelo escolhido; sempre revise antes de rodar.

## Problemas comuns

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| `Informe sua chave de IA...` | Campo vazio e sem `CAPIVARA_AI_KEY` | Gerar/colar a chave ou configurar a variável |
| `Chave recusada pelo provider` | Chave inválida, revogada ou sem crédito | Conferir a chave no provedor |
| `O modelo não devolveu um JSON válido` | Modelo pequeno ou resposta com markdown | Tente outro modelo ou reformule a descrição |
| `o conector ... não existe no catálogo` | Modelo inventou um tipo | Repetir com descrição mais concreta |
| `o campo ... é obrigatório` | Modelo omitiu parâmetro necessário | Preencher no inspetor após gerar ou tentar outro modelo |
| `O fluxo gerado contém um ciclo` | Ligação circular entre passos | Pedir fluxo linear ou corrigir os ponteiros |
| `HTTP só é permitido em localhost` | Base URL remota com `http://` | Usar `https://` ou apontar para Ollama local |
