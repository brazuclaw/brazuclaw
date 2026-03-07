# BrazuClaw

Bot Telegram que repassa mensagens ao Codex CLI e devolve a resposta ao usuario.

## Estado atual

- onboarding via terminal com `brazuclaw-setup`
- integracao direta com a API HTTP do Telegram usando `requests`
- execucao do Codex CLI com `codex exec --yolo`
- daemonizacao local com `brazuclaw start`, `brazuclaw stop` e `brazuclaw restart`
- logs locais em `~/.brazuclaw/logs/brazuclaw.log`
- consulta de logs com `brazuclaw logs` e `brazuclaw logs -f`
- memoria e estado persistidos em SQLite
- suporte a texto, imagens e arquivos como entrada e saida

## Estrutura local

Todos os dados do BrazuClaw ficam em `~/.brazuclaw/`:

- `config.env`: configuracao local
- `ALMA.md`: personalidade do bot
- `logs/brazuclaw.log`: arquivo de log
- `db/mensagens.db`: historico e estado em SQLite
- `brazuclaw.pid`: PID do daemon quando o bot esta em background

## Uso

Depois de instalar o pacote:

```bash
brazuclaw-setup
brazuclaw start
```

Comandos disponiveis:

- `brazuclaw` ou `brazuclaw start`
- `brazuclaw setup`
- `brazuclaw stop`
- `brazuclaw restart`
- `brazuclaw logs`
- `brazuclaw logs -f`
- `brazuclaw cron help`
- `brazuclaw cron list`
- `brazuclaw cron add --nome NOME --schedule "*/5 * * * *" --prompt "instrucao" [--chat 123] [--callback nunca|erro|sempre] [--timeout 120]`
- `brazuclaw cron enable ID`
- `brazuclaw cron disable ID`
- `brazuclaw cron run ID`
- `brazuclaw cron abort ID`
- `brazuclaw cron rm ID`

Exemplo:

```bash
brazuclaw cron add \
  --nome resumo-diario \
  --schedule "0 9 * * *" \
  --prompt "Leia a memoria do job e gere um resumo curto do dia." \
  --chat 123456789 \
  --callback erro
```

Notas:

- o scheduler e interno ao daemon do BrazuClaw; `brazuclaw start` sincroniza os jobs ativos do banco e pula janelas perdidas durante downtime
- cada cron usa a mesma logica do bot: `ALMA.md`, memoria no SQLite e execucao via `codex exec --yolo`
- se um cron estiver em execucao, `brazuclaw cron abort ID` solicita o encerramento do subprocesso do Codex
