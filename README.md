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

## Fase seguinte

- cron para tarefas recorrentes
- refinamento do fluxo de jobs mais complexos apoiados por banco local
