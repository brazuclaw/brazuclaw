# Chrome Desktop via CDP

Controlar o Chrome real do desktop do usuario via Chrome DevTools Protocol (CDP), usando os logins, extensoes e cookies reais do usuario.

## Pre-requisitos

- Google Chrome ou Chromium instalado no sistema

## Verificar se CDP esta ativo

```bash
curl -s http://localhost:9222/json/version
```

Se retornar JSON com "Browser" e "webSocketDebuggerUrl", o Chrome ja esta rodando com debugging habilitado.

## Detectar binario do Chrome

- **macOS**: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- **Linux**: `which google-chrome || which google-chrome-stable || which chromium-browser`
- **WSL**: `/mnt/c/Program Files/Google/Chrome/Application/chrome.exe` (Chrome do Windows; acessivel via WSL)

## Lancar Chrome com debugging

Se o CDP nao estiver ativo, iniciar o Chrome com a flag de debugging usando o perfil dedicado do BrazuClaw:

```bash
"<caminho-do-chrome>" --remote-debugging-port=9222 --user-data-dir="$HOME/.brazuclaw/chrome-profile/" &
```

Isso usa um perfil separado em `~/.brazuclaw/chrome-profile/`, sem interferir no Chrome pessoal do usuario. Sessoes e cookies do BrazuClaw persistem entre reinicializacoes.

**IMPORTANTE**: Se outro Chrome ja esta usando a porta 9222, verificar com `curl -s http://localhost:9222/json/version` antes de tentar lancar outro. Nunca matar processos do Chrome do usuario sem confirmacao explicita.

## Conexao via Playwright (interacoes complexas)

Conectar ao Chrome existente sem precisar de `playwright install`:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0]  # contexto real do usuario
    page = context.pages[0]        # aba existente
    # ou page = context.new_page() para nova aba
```

## Conexao via CDP raw (leve, sem dependencias)

Usar websocket direto para comandos simples:

```python
import json, websocket

# Obter endpoint da primeira aba
import urllib.request
tabs = json.loads(urllib.request.urlopen("http://localhost:9222/json").read())
ws_url = tabs[0]["webSocketDebuggerUrl"]

ws = websocket.connect(ws_url)
ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": "https://example.com"}}))
resultado = json.loads(ws.recv())
```

## Referencia rapida

| Operacao | Playwright | CDP raw |
|----------|-----------|---------|
| Navegar | `page.goto(url)` | `Page.navigate` |
| Clicar | `page.click(seletor)` | `Runtime.evaluate` + `document.querySelector().click()` |
| Digitar | `page.fill(seletor, texto)` | `Runtime.evaluate` + atribuir `.value` |
| Screenshot | `page.screenshot(path=...)` | `Page.captureScreenshot` |
| Extrair texto | `page.text_content(seletor)` | `Runtime.evaluate` + `.textContent` |
| Listar abas | `context.pages` | `GET http://localhost:9222/json` |
| Nova aba | `context.new_page()` | `Target.createTarget` |
| Fechar aba | `page.close()` | `Target.closeTarget` |

## Remocao de modais e overlays

Ao carregar qualquer pagina, executar limpeza de elementos que bloqueiam visibilidade:

```javascript
// Remover modais, overlays, banners de cookies e popups
document.querySelectorAll('[class*="modal"], [class*="overlay"], [class*="popup"], [class*="cookie"], [class*="consent"], [class*="gdpr"], [class*="banner"], [id*="modal"], [id*="overlay"], [id*="cookie"], [id*="consent"]').forEach(el => el.remove());

// Remover elementos fixed/sticky que cobrem a tela
document.querySelectorAll('*').forEach(el => {
  const s = getComputedStyle(el);
  if ((s.position === 'fixed' || s.position === 'sticky') && parseInt(s.zIndex) > 100) el.remove();
});

// Restaurar scroll do body
document.body.style.overflow = 'auto';
document.documentElement.style.overflow = 'auto';
```

Executar via `Runtime.evaluate` (CDP raw) ou `page.evaluate()` (Playwright) logo apos navegacao.

## Lidando com bot walls e anti-bot

- Se um site bloquear acesso com captcha, cloudflare challenge ou similar, tente:
  1. Navegar pelo Chrome com perfil do BrazuClaw (que tem cookies e sessoes persistentes)
  2. Aguardar carregamento completo da pagina (incluindo desafios JS)
  3. Se o desafio persistir, informar o usuario que o site requer intervencao manual
- Prefira usar o Chrome via CDP em vez de requisicoes HTTP diretas para sites que bloqueiam bots
- O perfil dedicado em `~/.brazuclaw/chrome-profile/` acumula cookies e sessoes entre execucoes, facilitando passagem por desafios recorrentes

## Notas

- O browser fica **visivel** por padrao (e o desktop do usuario)
- Nunca fechar abas pre-existentes do usuario
- Ao terminar a tarefa, fechar apenas as abas que voce abriu
- Preferir reutilizar abas existentes quando possivel
- O perfil do BrazuClaw e separado do Chrome pessoal do usuario
