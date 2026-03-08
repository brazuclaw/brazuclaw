# BrazuClaw

Bot Telegram que repassa mensagens a provedores de IA configuraveis (Codex, Claude, Gemini) e devolve a resposta ao usuario. Extensivel via sistema de skills agnosticas de provedor.

## Estado atual

- onboarding via terminal com `brazuclaw-setup`
- integracao direta com a API HTTP do Telegram usando `requests`
- execucao de provedores de IA configuraveis (Codex, Claude, Gemini)
- selecao de provedor e modelo independente para chat e task/cron
- daemonizacao local com `brazuclaw start`, `brazuclaw stop` e `brazuclaw restart`
- logs locais em `~/.brazuclaw/logs/brazuclaw.log`
- consulta de logs com `brazuclaw logs` e `brazuclaw logs -f`
- memoria e estado persistidos em SQLite
- suporte a texto, imagens e arquivos como entrada e saida
- scheduler de crons interno com callbacks ao Telegram
- sistema de skills agnosticas de provedor em `~/.brazuclaw/skills/`

## Estrutura local

Todos os dados do BrazuClaw ficam em `~/.brazuclaw/`:

- `config.env`: configuracao local
- `ALMA.md`: personalidade do bot (editavel)
- `skills/`: skills disponiveis para o agente (extensiveis)
- `logs/brazuclaw.log`: arquivo de log
- `db/mensagens.db`: historico e estado em SQLite
- `brazuclaw.pid`: PID do daemon quando o bot esta em background
- `chrome-profile/`: perfil persistente do Chrome (skill chrome-cdp-playwright)

## Instalacao

```bash
pip install git+https://github.com/seu-usuario/brazuclaw.git
brazuclaw-setup
brazuclaw start
```

## Uso

Comandos disponiveis:

```
brazuclaw               # inicia o daemon (alias de start)
brazuclaw start         # inicia o daemon
brazuclaw setup         # executa o wizard de configuracao
brazuclaw stop          # encerra o daemon
brazuclaw restart       # reinicia o daemon
brazuclaw logs          # mostra as ultimas 50 linhas de log
brazuclaw logs -f       # segue o log em tempo real
brazuclaw logs 100      # mostra as ultimas 100 linhas

brazuclaw provider bot [codex|claude|gemini]   # le ou define provedor do chat
brazuclaw provider task [codex|claude|gemini]  # le ou define provedor dos crons
brazuclaw model bot [nome]                     # le ou define modelo do chat
brazuclaw model task [nome]                    # le ou define modelo dos crons

brazuclaw cron list
brazuclaw cron add --nome NOME --schedule "*/5 * * * *" --prompt "instrucao" \
                   [--chat CHAT_ID] [--callback nunca|erro|sempre] [--timeout 120]
brazuclaw cron enable ID
brazuclaw cron disable ID
brazuclaw cron run ID       # executa cron em foreground imediatamente
brazuclaw cron abort ID     # solicita aborto do subprocesso em execucao
brazuclaw cron rm ID
```

Exemplo de cron:

```bash
brazuclaw cron add \
  --nome resumo-diario \
  --schedule "0 9 * * *" \
  --prompt "Gere um resumo das noticias do dia." \
  --chat 123456789 \
  --callback sempre
```

## Skills

Skills sao documentacoes que ensinam o agente a executar tarefas especificas, sem depender de um provedor em particular. Ficam em `~/.brazuclaw/skills/`.

Skills incluidas no pacote:

| Skill | Descricao |
|---|---|
| `how-to-make-new-skills` | Guia para criar novas skills |
| `chrome-cdp-playwright` | Automacao de browser via Playwright e CDP, headless por padrao, perfil persistente |

Para criar uma nova skill:

1. Crie `~/.brazuclaw/skills/nome-da-skill/skill.md` com objetivo, contexto e instrucoes
2. Adicione uma entrada em `~/.brazuclaw/skills/skill-list.md`
3. O agente passara a consultar e usar a skill automaticamente

## Anexos

- **Entrada**: envie uma imagem ou arquivo pelo Telegram; o bot salva no SQLite e informa o agente da referencia
- **Saida**: o agente devolve o arquivo em base64 dentro de `[anexo nome="..." mimetype="..."] BASE64 [/anexo]`; o bot decodifica e envia como foto ou documento no Telegram

## Notas

- o scheduler e interno ao daemon; `brazuclaw start` recalcula os horarios dos jobs ativos e pula janelas perdidas durante downtime
- cada cron usa a mesma logica do bot: `ALMA.md`, memoria no SQLite e execucao via provedor de IA configurado para task
- o bot aguarda indefinidamente a resposta do provedor (sem timeout fixo); o indicador de digitacao e mantido a cada 4 segundos
- instancias orfas do processo sao encerradas automaticamente ao iniciar
