# BrazuClaw

PoC de chatbot Telegram que repassa mensagens ao Codex CLI.

Escopo desta primeira versao:
- onboarding terminal
- integracao Telegram via `requests`
- execucao do `codex exec --yolo`
- memoria persistida em SQLite
- suporte a imagens e arquivos como entrada e saida
- comandos `start`, `stop`, `restart` e `logs`

Fica para a fase 2:
- cron
- gerencia de logs e daemonizacao
- simplificacao adicional da codebase apos validar o fluxo end-to-end completo
