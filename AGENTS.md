# AGENTS.md — BrazuClaw

## Geral
- O projeto BrazuClaw é um chatbot Telegram que repassa mensagens do usuário a provedores de IA (Codex, Claude, Gemini) e devolve a resposta
- Linguagem: Python 3.11+, código-fonte 100% em português (variáveis, comentários, docstrings)
- Hardware alvo: Raspberry Pi 3 (1GB RAM, ARM quad-core 1.2GHz) ou laptop x86 equivalente (ex: Core 2 Duo, 2GB RAM, HDD)
- O sistema deve funcionar bem com apenas 512MB de RAM livre e CPU lenta
- Limite rígido: máximo 1000 linhas de código somando todos os arquivos `.py` do projeto (incluindo wizard)
- Dependências permitidas: apenas `requests`
- Nenhuma outra lib externa pode ser adicionada sem aprovação explícita
- Todo arquivo gerado, configuração e dado do BrazuClaw fica em `~/.brazuclaw/`; nenhum arquivo é criado fora desse diretório
- MUITO IMPORTANTE - o bot deve sempre rodar o provedor de IA em linha de comando (ex: `codex exec --yolo "<prompt>"`, `claude -p "<prompt>"`, `gemini -p "<prompt>"`) para toda e qualquer tarefa

## Empacotamento e Instalação
- O projeto deve ser instalável via `pip install git+...` (ou `pip install .` do repo)
- Usar `pyproject.toml` como único arquivo de configuração do pacote (sem setup.py, sem setup.cfg)
- O `pyproject.toml` deve declarar `requires-python = ">=3.11"` para que pip recuse instalação em versões anteriores
- O pip deve falhar com erro claro se o usuário tentar instalar em Python < 3.11; isso é responsabilidade do campo `requires-python`
- O pacote deve registrar os comandos CLI já implementados: entry points `brazuclaw` e `brazuclaw-setup`, com subcomandos `brazuclaw setup`, `brazuclaw start`, `brazuclaw stop`, `brazuclaw restart` e `brazuclaw logs`
- Após `pip install`, o usuário roda `brazuclaw-setup` e o wizard guia tudo; depois roda `brazuclaw` para iniciar o bot
- O pacote deve incluir `ALMA.md` e o diretório `skills/` via `package_data` (`brazuclaw = ["ALMA.md", "skills/**/*"]`)

## Diretório `~/.brazuclaw/`
- Criado automaticamente pelo wizard ou pelo bot na primeira execução, se não existir
- `~/.brazuclaw/config.env` — armazena configuração local em formato `CHAVE=valor`
- `~/.brazuclaw/ALMA.md` — arquivo de personalidade do bot; copiado do padrão do pacote se não existir
- `~/.brazuclaw/skills/` — skills disponíveis para o agente; copiadas do pacote na primeira execução sem sobrescrever customizações do usuário
- `~/.brazuclaw/logs/brazuclaw.log` — arquivo de log do daemon
- `~/.brazuclaw/db/mensagens.db` — SQLite com histórico, anexos e estado do bot
- `~/.brazuclaw/chrome-profile/` — perfil dedicado do Chrome para navegação via CDP (separado do Chrome pessoal do usuário)
- `~/.brazuclaw/brazuclaw.pid` — PID do processo em background quando o daemon está ativo
- O bot e o wizard leem variáveis primeiro de `~/.brazuclaw/config.env`, depois do ambiente do sistema; ambiente do sistema tem prioridade
- Nenhum outro diretório ou arquivo fora de `~/.brazuclaw/` deve ser criado ou modificado pelo BrazuClaw
- logs ficam em `~/.brazuclaw/logs/`

## Wizard de Onboarding (`brazuclaw-setup`)
- O wizard roda 100% no terminal, interativo, com prompts simples em português do Brasil
- Toda saída do wizard usa apenas ASCII ou caracteres latinos básicos (sem emoji, compatível com qualquer terminal)
- O wizard cria `~/.brazuclaw/` e seus arquivos conforme necessário
- O wizard executa as etapas abaixo em ordem, uma por uma, e só avança se a etapa atual passar

### Etapa 1 — Verificar sistema operacional
- Detectar se está rodando em Linux, macOS ou WSL
- Se for Windows nativo (sem WSL), exibir mensagem clara de que precisa de WSL e linkar instruções, depois sair
- Exibir o SO detectado e pedir confirmação para continuar

### Etapa 2 — Verificar Python
- Confirmar que Python >= 3.11 está disponível
- Se a versão for menor, exibir instruções de atualização e sair

### Etapa 3 — Selecionar provedores
- Perguntar o provedor para chat (bot) e para task/cron; podem ser diferentes
- Perguntar o modelo para cada provedor (Enter para usar o padrão)
- Para Gemini, apresentar menu de modelos disponíveis
- Salvar em `config.env`: `BRAZUCLAW_PROVIDER_BOT`, `BRAZUCLAW_PROVIDER_TASK`, `BRAZUCLAW_MODEL_BOT`, `BRAZUCLAW_MODEL_TASK`

### Etapa 4 — Verificar e instalar Node.js (somente se Codex selecionado)
- Codex CLI precisa de Node.js >= 18; checar com `node --version`
- Se não instalado ou versão menor, perguntar se quer instalar via gerenciador de pacotes do SO
- Oferecer o comando exato para o SO detectado (apt, brew, etc.) e pedir confirmação antes de executar

### Etapa 5 — Verificar e instalar CLIs de provedores selecionados
- **Codex**: checar `codex` no PATH; instalar com `npm install -g @openai/codex` se ausente; autenticar com `codex login --device-auth`
- **Claude**: checar `claude` no PATH; instalar com `npm install -g @anthropic-ai/claude-code` se ausente; validar execução
- **Gemini**: checar `gemini` no PATH; se ausente, exibir link de instalação e sair

### Etapa 6 — Configurar token do Telegram (BotFather)
- Exibir instruções passo a passo de como criar um bot no `@BotFather` no Telegram
- Pedir ao usuário para colar o token recebido do BotFather
- Validar formato do token (padrão `123456:ABC-xyz`)
- Testar o token com uma chamada a `getMe` da API do Telegram
- Se válido, salvar em `~/.brazuclaw/config.env` como `BRAZUCLAW_TOKEN=...`
- Se inválido, exibir erro e permitir reinserir
- Se `BRAZUCLAW_TOKEN` já estiver no ambiente, validar e usar sem pedir novamente

### Etapa 7 — Criar personalidade padrão
- Verificar se já existe `~/.brazuclaw/ALMA.md`
- Se não existir, copiar o arquivo padrão do pacote para `~/.brazuclaw/ALMA.md`
- Informar ao usuário que pode editar o arquivo a qualquer momento

### Etapa 8 — Teste de ponta a ponta
- Executar `provedor_ok()` para cada provedor selecionado
- Se falhar, exibir erro e sair
- Orientar o usuário a iniciar o bot e fazer o teste manual no Telegram
- Informar o comando de consulta de logs caso algo falhe

### Etapa 9 — Resumo final
- Exibir um resumo de tudo que foi configurado: SO, provedor bot, modelo bot, provedor task, modelo task, token Telegram, personalidade e caminhos locais
- Exibir o comando para iniciar o bot: `brazuclaw`

## Bot Telegram
- O token é lido de `~/.brazuclaw/config.env` ou da variável de ambiente `BRAZUCLAW_TOKEN`
- A comunicação com o Telegram usa a API HTTP direta via `requests`, sem wrappers
- Long polling com `getUpdates` e `timeout=30` para reduzir chamadas HTTP e CPU idle
- O parâmetro `offset` deve ser atualizado corretamente para nunca reprocessar mensagens; offset também é persistido em SQLite (`estado["telegram_offset"]`) para sobreviver a reinicializações
- Cada mensagem é repassada ao provedor de IA configurado via subprocess
- O subprocess roda com `nice -n 10` em Linux; em SO sem `nice`, ignorar sem erro
- **Sem timeout no subprocess**: o bot aguarda indefinidamente a resposta do provedor com aborto cooperativo via `deve_abortar()`
- O bot processa apenas uma mensagem por vez (sem threading, sem multiprocessing, sem async)
- Ignorar chats que não sejam privados
- Responder apenas em chats privados; ignorar grupos por padrão
- Mensagens com mais de 1000 caracteres: rejeitar com aviso ao usuário
- Suportar texto, imagem e arquivo simples como entrada; stickers, áudio e outros tipos continuam fora do escopo
- Permitir que o provedor devolva anexos em base64 dentro de blocos `[anexo]...[/anexo]` para reenvio ao Telegram
- O modo padrão de execução do CLI deve iniciar o daemon em background
- Deve existir suporte a `stop`, `restart` e `logs`
- Ao iniciar, matar instâncias órfãs do BrazuClaw que não correspondam ao PID file

## Anexos (entrada e saída)
- **Entrada**: foto ou documento recebido pelo Telegram é baixado, validado (máx 256 KB), convertido em base64 e salvo na tabela `mensagens` do SQLite junto com `mimetype` e `nome_arquivo`
- O prompt informa ao agente que existe um anexo com referência a `chat_id`, `update_id`, `nome_arquivo`, `mimetype` e o caminho do banco; o agente deve consultar o SQLite para ler o conteúdo
- **Saída**: o agente inclui no texto de resposta blocos no formato `[anexo nome="arquivo.ext" mimetype="tipo/subtipo"] BASE64 [/anexo]`; o bot extrai, decodifica e envia ao Telegram via `sendPhoto` (imagens) ou `sendDocument` (demais)
- O parser de anexos (`PADRAO_ANEXO`) aceita atributos em qualquer ordem dentro da tag de abertura
- Erros de envio de anexo são capturados, logados e notificados ao usuário via mensagem de texto; nunca silenciosos

## Memória
- Últimas 10 interações respondidas por chat devem ser usadas como contexto
- Persistência local em SQLite, sem depender de serviço externo
- Cada resposta armazenada truncada em 500 caracteres para economizar RAM
- Memória injetada no prompt antes da mensagem atual; FIFO ao atingir 10
- O offset do Telegram também deve ser persistido localmente para evitar reprocessamento após reinício

## Cron
- Scheduler interno ao daemon; jobs verificados antes de cada ciclo de long polling
- Jobs persistidos em SQLite na tabela `crons`; o bot recalcula `proximo_em` de todos os jobs ativos ao iniciar, evitando execuções perdidas durante downtime
- Cada execução usa o provedor e modelo configurados para `task` (independentes do bot)
- Três modos de callback: `nunca` (sem notificação), `erro` (só em caso de falha), `sempre` (sempre notifica)
- Suporte a `timeout_segundos` por cron (armazenado, abortável via flag no banco)
- Execuções concorrentes não ocorrem: um cron por vez, verificado pelo campo `pid_atual`
- CLI para gerenciar crons: `list`, `add`, `enable`, `disable`, `run`, `abort`, `rm`

## Skills
- Skills são extensões agnósticas de provedor que ensinam o agente a executar tarefas específicas
- Cada skill tem seu próprio diretório em `~/.brazuclaw/skills/{nome-da-skill}/` com um arquivo `skill.md`
- O catálogo em `~/.brazuclaw/skills/skill-list.md` lista todas as skills disponíveis
- Skills padrão são empacotadas no pacote Python (`brazuclaw/skills/`) e copiadas para `~/.brazuclaw/skills/` na primeira execução, sem sobrescrever customizações do usuário
- O agente é instruído via `ALMA.md` a consultar o catálogo e a documentação de cada skill antes de responder
- Para criar uma nova skill, seguir o guia em `~/.brazuclaw/skills/how-to-make-new-skills/skill.md` e atualizar `skill-list.md`
- Skills incluídas no pacote:
  - `how-to-make-new-skills` — guia para criar novas skills
  - `chrome-desktop` — controle do Chrome real do desktop via CDP, usando logins e sessoes reais do usuario

## Personalidade
- Arquivo `~/.brazuclaw/ALMA.md`; lido sob demanda e criado a partir do padrão do pacote quando ausente
- Se não existir, bot funciona sem personalidade customizada
- A `ALMA.md` instrui o agente sobre: identidade, uso de memória do SQLite, consulta de skills, tarefas recorrentes via cron e prioridade de contexto

## Estrutura de Arquivos
- `pyproject.toml` — configuração do pacote, dependências, `requires-python = ">=3.11"` e entry points
- `brazuclaw/main.py` — toda a lógica do bot, CLI, wizard, polling, cron
- `brazuclaw/wizard.py` — re-export de `cli_setup` de `main.py`
- `brazuclaw/__init__.py` — marcador de pacote
- `brazuclaw/ALMA.md` — personalidade padrão incluída no pacote
- `brazuclaw/skills/skill-list.md` — catálogo de skills padrão
- `brazuclaw/skills/how-to-make-new-skills/skill.md` — guia para criar skills
- `brazuclaw/skills/chrome-desktop/skill.md` — skill de controle do Chrome real via CDP
- `CLAUDE.md` — fonte de verdade do projeto

## Código
- Total de todos os `.py` somados: máximo 1000 linhas
- Todas as funções com docstrings em português
- Sem classes; apenas funções puras e dicionários
- Log via `print()`: timestamp, chat_id ofuscado (últimos 4 dígitos), status; saída redirecionada para arquivo quando em daemon; `flush=True` para garantir escrita imediata
- Nenhum dado sensível nos logs (sem texto de mensagens, tokens, API keys)
- Sem arquivos temporários em disco
- Encoding UTF-8; compatível com terminais sem suporte a emoji
- O AGENTS.md é a fonte de verdade para qualquer agente de código neste projeto

## Provedores de IA
- Três provedores suportados: `codex`, `claude`, `gemini`
- Provedor e modelo são configuráveis independentemente para bot (chat) e task (cron)
- Config keys em `~/.brazuclaw/config.env`:
  - `BRAZUCLAW_PROVIDER_BOT=codex` — provedor para chat (codex | claude | gemini)
  - `BRAZUCLAW_PROVIDER_TASK=codex` — provedor para cron/jobs (codex | claude | gemini)
  - `BRAZUCLAW_MODEL_BOT=` — modelo opcional para chat
  - `BRAZUCLAW_MODEL_TASK=` — modelo opcional para task
- Registry de provedores com binário, args base, flag de modelo e posição do modelo (antes ou depois dos args):
  - `codex`: `codex exec --yolo <prompt>` (flag `-m`, modelo depois)
  - `claude`: `claude --model MODEL -p <prompt>` (flag `--model`, modelo antes)
  - `gemini`: `gemini --model MODEL --yolo -p <prompt>` (flag `--model`, modelo antes)
- Comandos CLI: `brazuclaw provider bot [provedor]` e `brazuclaw provider task [provedor]`
- Comandos CLI: `brazuclaw model bot [modelo]` e `brazuclaw model task [modelo]`
- Wizard permite escolher provedor+modelo para bot e task; etapas de Node.js/Codex são condicionais
- Para gemini: filtrar linhas de stderr/stdout com "Loaded cached credentials." e "YOLO mode is enabled." após execução
- Default: codex (compatível com configs existentes sem chaves PROVIDER)
- Se provedor retornar código de saída não-zero sem stdout, lança RuntimeError com o stderr; se houver "usage limit", "limit", "upgrade" ou "credits" no stderr, repassa a última linha do erro ao usuário
