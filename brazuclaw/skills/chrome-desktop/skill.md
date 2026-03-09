# Chrome Desktop via CDP

Controlar o Chrome real do desktop do usuario via Chrome DevTools Protocol (CDP), usando o perfil dedicado do BrazuClaw com sessoes e cookies persistentes.

## Screenshot rapido (comando unico)

Para capturar screenshot de qualquer URL, execute o script auxiliar:

```bash
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py URL [SAIDA] [--headed]
```

Exemplos:

```bash
# Screenshot padrao (headless, salva em /tmp/brazuclaw-screenshot.png)
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py https://example.com

# Screenshot com caminho personalizado
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py https://economist.com /tmp/economist.png

# Screenshot com janela visivel (modo headed, util para debug)
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py https://economist.com /tmp/economist.png --headed
```

O script faz tudo automaticamente:
1. Detecta o binario do Chrome/Chromium no sistema (macOS, Linux, WSL)
2. Verifica se o CDP ja esta ativo na porta 9222
3. Se nao estiver, lanca o Chrome em modo headless com perfil dedicado `~/.brazuclaw/chrome-profile/`
4. Aguarda ate 15 segundos pelo CDP ficar pronto
5. Conecta via Playwright (`connect_over_cdp`), abre nova aba
6. Navega ate a URL com timeout de 30 segundos
7. Aguarda 3 segundos para renderizacao JavaScript
8. Remove modais, overlays, banners de cookies e popups automaticamente
9. Captura screenshot do viewport e salva no caminho de saida
10. Fecha apenas a aba que abriu (Chrome continua rodando para reuso)
11. Imprime o caminho do arquivo salvo em stdout; erros vao para stderr

Saida: exit 0 + caminho em stdout se sucesso, exit 1 + erro em stderr se falha.

**Prerequisito**: `playwright` instalado via pip (`pip install playwright`). Nao precisa de `playwright install` pois conecta ao Chrome do sistema via CDP.

## Fluxo completo: screenshot + envio ao Telegram

Quando estiver em task ou cron e precisar enviar screenshot ao usuario:

```bash
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py https://example.com /tmp/screenshot.png && \
brazuclaw tg send --chat CHAT_ID --file /tmp/screenshot.png
```

Substitua `CHAT_ID` pelo ID do chat fornecido no prompt. Esse padrao e o recomendado para tarefas em segundo plano e crons.

## Gerenciamento do Chrome

### Verificar se CDP esta ativo

```bash
curl -s http://127.0.0.1:9222/json/version
```

Se retornar JSON com "Browser" e "webSocketDebuggerUrl", o Chrome ja esta rodando com debugging.

### Detectar binario do Chrome

- **macOS**: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- **Linux**: `which google-chrome || which google-chrome-stable || which chromium-browser || which chromium`
- **WSL**: `/mnt/c/Program Files/Google/Chrome/Application/chrome.exe`

### Lancar Chrome manualmente

Se precisar lancar o Chrome manualmente (fora do script), primeiro remover locks de sessoes anteriores e depois lancar:

```bash
# Remover locks de sessoes anteriores (obrigatorio)
rm -f ~/.brazuclaw/chrome-profile/SingletonLock ~/.brazuclaw/chrome-profile/SingletonSocket ~/.brazuclaw/chrome-profile/SingletonCookie ~/.brazuclaw/chrome-profile/DevToolsActivePort

# Headless (para tasks e crons em background)
"<binario>" --remote-debugging-port=9222 --user-data-dir="$HOME/.brazuclaw/chrome-profile/" --headless=new --no-first-run --no-default-browser-check --no-sandbox --disable-gpu --disable-background-networking --disable-sync &

# Headed (janela visivel, para debug ou interacao)
"<binario>" --remote-debugging-port=9222 --user-data-dir="$HOME/.brazuclaw/chrome-profile/" --no-first-run --no-default-browser-check --no-sandbox &
```

O perfil em `~/.brazuclaw/chrome-profile/` e separado do Chrome pessoal do usuario. Sessoes, cookies e extensoes persistem entre reinicializacoes.

**Flags obrigatorias**:
- `--no-sandbox`: necessario no macOS e em ambientes sem X11 para evitar crash de subprocessos (Mach rendezvous failed)
- `--disable-gpu`: previne erros de GPU em modo headless
- `--disable-background-networking` e `--disable-sync`: evita crash por tentativas de sync com perfis corrompidos

**Se o Chrome crashar ao iniciar**: o perfil pode estar corrompido por encerramento anterior nao-limpo. O script `screenshot.py` lida com isso automaticamente (remove locks e, se necessario, usa perfil temporario limpo). Para resolver manualmente, remover os locks acima ou deletar o perfil inteiro e recriar.

**IMPORTANTE**: Se outro Chrome ja esta usando a porta 9222, verificar com `curl -s http://127.0.0.1:9222/json/version` antes de tentar lancar outro. O script `screenshot.py` ja faz essa verificacao automaticamente.

### Encerrar Chrome do BrazuClaw

Para encerrar o Chrome lancado pelo BrazuClaw sem afetar o Chrome pessoal do usuario:

```bash
# Encontrar PID do Chrome com perfil brazuclaw
ps aux | grep 'brazuclaw/chrome-profile' | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null
```

## Interacao avancada via Playwright

Para fluxos que vao alem de screenshot (preencher formularios, clicar botoes, extrair dados):

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = browser.contexts[0].new_page()
    try:
        page.goto("https://example.com", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Remover modais (sempre executar apos navegacao)
        page.evaluate("""
            document.querySelectorAll('[class*="modal"],[class*="overlay"],[class*="popup"],[class*="cookie"],[class*="consent"],[class*="gdpr"],[class*="banner"],[id*="modal"],[id*="overlay"],[id*="cookie"],[id*="consent"]').forEach(e=>e.remove());
            document.querySelectorAll('*').forEach(e=>{const s=getComputedStyle(e);if((s.position==='fixed'||s.position==='sticky')&&parseInt(s.zIndex)>100)e.remove()});
            document.body.style.overflow='auto';document.documentElement.style.overflow='auto';
        """)

        # Interagir
        page.fill("#search", "termo")
        page.click("button[type=submit]")
        page.wait_for_timeout(3000)

        # Screenshot
        page.screenshot(path="/tmp/resultado.png")

        # Extrair texto
        texto = page.text_content("main")
    finally:
        page.close()  # fechar apenas a aba que abriu
```

**IMPORTANTE**: Sempre garanta que o Chrome esteja rodando com CDP antes de usar Playwright. Use o script `screenshot.py` como referencia ou execute `curl -s http://127.0.0.1:9222/json/version` para verificar. Se o CDP nao estiver ativo, lance o Chrome conforme a secao "Lancar Chrome manualmente".

## Referencia rapida Playwright

| Operacao | Comando |
|----------|---------|
| Navegar | `page.goto(url, timeout=30000)` |
| Clicar | `page.click(seletor)` |
| Digitar | `page.fill(seletor, texto)` |
| Screenshot | `page.screenshot(path=...)` |
| Extrair texto | `page.text_content(seletor)` |
| Listar abas | `browser.contexts[0].pages` |
| Nova aba | `browser.contexts[0].new_page()` |
| Fechar aba | `page.close()` |
| Executar JS | `page.evaluate("codigo")` |
| Esperar | `page.wait_for_timeout(ms)` |

## Lidando com bot walls e anti-bot

1. O perfil dedicado em `~/.brazuclaw/chrome-profile/` acumula cookies e sessoes entre execucoes, facilitando passagem por desafios recorrentes
2. Apos carregar pagina, sempre remova modais e overlays (o script `screenshot.py` faz isso automaticamente)
3. Se o site bloquear acesso com captcha ou cloudflare challenge, aguarde carregamento completo (aumente o `wait_for_timeout`)
4. Se o desafio persistir, informe o usuario que o site requer intervencao manual
5. Prefira usar o Chrome via CDP em vez de requisicoes HTTP diretas para sites que bloqueiam bots

## Troubleshooting

| Problema | Causa provavel | Solucao |
|----------|---------------|---------|
| "Chrome/Chromium nao encontrado" | Chrome nao instalado | Instalar: `apt install chromium-browser` (Linux) ou baixar de google.com/chrome (macOS) |
| "Chrome nao respondeu na porta 9222" | Falha ao iniciar, perfil corrompido, ou outro processo na porta | Verificar `lsof -i :9222`; remover locks do perfil; o script tenta perfil limpo automaticamente |
| Chrome crasha ao iniciar (exit -5) | Perfil corrompido por encerramento anterior nao-limpo | Remover `~/.brazuclaw/chrome-profile/Singleton*` e `DevToolsActivePort`; se persistir, deletar perfil inteiro |
| "Mach rendezvous failed" | macOS: sandbox ou subprocessos perderam conexao | Usar `--no-sandbox`; o script ja inclui essa flag |
| "Playwright not found" | `playwright` nao instalado via pip | `pip install playwright` (nao precisa de `playwright install`) |
| "connect ECONNREFUSED ::1:9222" | Playwright resolveu localhost como IPv6 | Usar `http://127.0.0.1:9222` em vez de `localhost`; o script ja faz isso |
| Screenshot em branco | Pagina precisa de mais tempo para renderizar | Aumentar `wait_for_timeout` ou usar `wait_until="networkidle"` |
| Modais ainda aparecem | Seletores de limpeza nao cobriram o modal | Adicionar seletores especificos via `page.evaluate()` |
| "Target closed" | Chrome foi fechado durante a operacao | Relancar Chrome e tentar novamente |

## Notas

- O Chrome lancado pelo script fica em background e persiste para reuso entre execucoes
- Nunca fechar abas pre-existentes; fechar apenas as abas que voce abriu
- O perfil do BrazuClaw e separado do Chrome pessoal do usuario
- Em modo headless, nao ha janela visivel (ideal para tasks e crons)
- Em modo headed, a janela aparece no desktop (util para debug)
