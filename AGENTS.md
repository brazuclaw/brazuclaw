# AGENTS.md — BrazuClaw

## Geral
- O projeto BrazuClaw é um chatbot Telegram que repassa mensagens do usuário ao Codex CLI e devolve a resposta
- Linguagem: Python 3.11+, código-fonte 100% em português (variáveis, comentários, docstrings)
- Hardware alvo: Raspberry Pi 3 (1GB RAM, ARM quad-core 1.2GHz) ou laptop x86 equivalente (ex: Core 2 Duo, 2GB RAM, HDD)
- O sistema deve funcionar bem com apenas 512MB de RAM livre e CPU lenta
- Limite rígido: máximo 1000 linhas de código somando todos os arquivos `.py` do projeto (incluindo wizard)
- Dependências permitidas: apenas `requests`
- Nenhuma outra lib externa pode ser adicionada sem aprovação explícita
- Todo arquivo gerado, configuração e dado do BrazuClaw fica em `~/.brazuclaw/`; nenhum arquivo é criado fora desse diretório
- MUITO IMPORTANTE - o bot deve sempre rodar codex em linha de comando como este exemplo: `codex exec --yolo "<prompt aqui>" 2>/dev/null` para toda e qualquer tarefa, para garantir uma experiência de usuário fluida.

## Empacotamento e Instalação
- O projeto deve ser instalável via `pip install git+...` (ou `pip install .` do repo)
- Usar `pyproject.toml` como único arquivo de configuração do pacote (sem setup.py, sem setup.cfg)
- O `pyproject.toml` deve declarar `requires-python = ">=3.11"` para que pip recuse instalação em versões anteriores
- O pip deve falhar com erro claro se o usuário tentar instalar em Python < 3.11; isso é responsabilidade do campo `requires-python`
- O pacote deve registrar os comandos CLI já implementados: entry points `brazuclaw` e `brazuclaw-setup`, com subcomandos `brazuclaw setup`, `brazuclaw start`, `brazuclaw stop`, `brazuclaw restart` e `brazuclaw logs`
- Após `pip install`, o usuário roda `brazuclaw-setup` e o wizard guia tudo; depois roda `brazuclaw` para iniciar o bot
- O pacote deve incluir o arquivo padrão de personalidade (`ALMA.md`) via `package_data`

## Diretório `~/.brazuclaw/`
- Criado automaticamente pelo wizard ou pelo bot na primeira execução, se não existir
- `~/.brazuclaw/config.env` — armazena configuração local em formato `CHAVE=valor`
- `~/.brazuclaw/ALMA.md` — arquivo de personalidade do bot; copiado do padrão do pacote se não existir
- `~/.brazuclaw/logs/brazuclaw.log` — arquivo de log do daemon
- `~/.brazuclaw/db/mensagens.db` — SQLite com histórico, anexos e estado do bot
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

### Etapa 3 — Verificar e instalar Node.js
- Codex CLI precisa de Node.js >= 18; checar com `node --version`
- Se não instalado ou versão menor, perguntar se quer instalar via gerenciador de pacotes do SO
- Oferecer o comando exato para o SO detectado (apt, brew, etc.) e pedir confirmação antes de executar

### Etapa 4 — Verificar e instalar Codex CLI
- Checar se `codex` está no PATH com `which codex` ou `command -v codex`
- Se não instalado, executar `npm install -g @openai/codex` (após confirmação do usuário)
- Após instalação, verificar novamente se `codex` está acessível

### Etapa 5 — Configurar autenticação do Codex
- Checar se o Codex CLI já está autenticado
- Se não estiver, iniciar `codex login --device-auth`
- Validar a autenticação executando uma chamada simples ao `codex exec --yolo`
- Se falhar, exibir erro claro e instruir o usuário a refazer o login

### Etapa 6 — Configurar token do Telegram (BotFather)
- Exibir instruções passo a passo de como criar um bot no `@BotFather` no Telegram
- Pedir ao usuário para colar o token recebido do BotFather
- Validar formato do token (padrão `123456:ABC-xyz`)
- Testar o token com uma chamada a `getMe` da API do Telegram
- Se válido, salvar em `~/.brazuclaw/config.env` como `BRAZUCLAW_TOKEN=...`
- Se inválido, exibir erro e permitir reinserir

### Etapa 7 — Criar personalidade padrão
- Verificar se já existe `~/.brazuclaw/ALMA.md`
- Se não existir, copiar o arquivo padrão do pacote para `~/.brazuclaw/ALMA.md`
- Informar ao usuário que pode editar o arquivo a qualquer momento

### Etapa 8 — Teste de ponta a ponta
- Validar localmente que o Codex CLI autenticado responde
- Orientar o usuário a iniciar o bot e fazer o teste manual no Telegram
- Informar o comando de consulta de logs caso algo falhe

### Etapa 9 — Resumo final
- Exibir um resumo de tudo que foi configurado: SO, Node.js, Codex, token Telegram, personalidade e caminhos locais
- Exibir o comando para iniciar o bot: `brazuclaw`

## Bot Telegram
- O token é lido de `~/.brazuclaw/config.env` ou da variável de ambiente `BRAZUCLAW_TOKEN`
- A comunicação com o Telegram usa a API HTTP direta via `requests`, sem wrappers
- Long polling com `getUpdates` e `timeout=30` para reduzir chamadas HTTP e CPU idle
- O parâmetro `offset` deve ser atualizado corretamente para nunca reprocessar mensagens
- Cada mensagem é repassada ao Codex via subprocess `codex exec --yolo`
- O subprocess roda com `nice -n 10` em Linux; em SO sem `nice`, ignorar sem erro
- Timeout do subprocess: 120 segundos; após isso, abortar e avisar o usuário
- O bot processa apenas uma mensagem por vez (sem threading, sem multiprocessing, sem async)
- Ignorar chats que não sejam privados
- Responder apenas em chats privados; ignorar grupos por padrão
- Mensagens com mais de 1000 caracteres: rejeitar com aviso ao usuário
- Suportar texto, imagem e arquivo simples como entrada; stickers, áudio e outros tipos continuam fora do escopo
- Permitir que o Codex devolva anexos em base64 para reenvio ao Telegram
- O modo padrão de execução do CLI deve iniciar o daemon em background
- Deve existir suporte a `stop`, `restart` e `logs`

## Memória
- Últimas 10 interações respondidas por chat devem ser usadas como contexto
- Persistência local em SQLite, sem depender de serviço externo
- Cada resposta armazenada truncada em 500 caracteres para economizar RAM
- Memória injetada no prompt antes da mensagem atual; FIFO ao atingir 10
- O offset do Telegram também deve ser persistido localmente para evitar reprocessamento após reinício

## Cron e banco de dados
- SQLite já é usado para histórico, anexos e estado do bot
- Cron continua como trabalho futuro para tarefas recorrentes e jobs agendados

## Personalidade
- Arquivo `~/.brazuclaw/ALMA.md`; lido sob demanda e criado a partir do padrão do pacote quando ausente
- Se não existir, bot funciona sem personalidade customizada

## Estrutura de Arquivos
- `pyproject.toml` — configuração do pacote, dependências, `requires-python = ">=3.11"` e entry points
- `brazuclaw/main.py` — CLI principal, daemonização, logs e loop de polling
- `brazuclaw/telegram_api.py` — funções para API do Telegram
- `brazuclaw/codex_runner.py` — monta prompt e executa subprocess
- `brazuclaw/memoria.py` — gerencia histórico e estado persistidos em SQLite
- `brazuclaw/config.py` — lê `~/.brazuclaw/config.env` e variáveis de ambiente
- `brazuclaw/wizard.py` — wizard de onboarding interativo
- `brazuclaw/ALMA.md` — personalidade padrão incluída no pacote
- `AGENTS.md` — este documento, fonte de verdade do projeto

## Código
- Total de todos os `.py` somados: máximo 1000 linhas
- Todas as funções com docstrings em português
- Sem classes; apenas funções puras e dicionários
- Log via `print()`: timestamp, chat_id ofuscado, status; saída redirecionada para arquivo quando em daemon
- Nenhum dado sensível nos logs
- Sem arquivos temporários em disco
- Encoding UTF-8; compatível com terminais sem suporte a emoji
- O AGENTS.md é a fonte de verdade para qualquer agente de código neste projeto
