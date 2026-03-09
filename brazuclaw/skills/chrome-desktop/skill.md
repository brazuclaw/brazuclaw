# Chrome Desktop via CDP

Controlar o Chrome real do desktop via Chrome DevTools Protocol (CDP). O Chrome roda com perfil dedicado em `~/.brazuclaw/agent-chrome/`, separado do Chrome pessoal do usuario. Sessoes, cookies e logins persistem entre execucoes.

**Regra principal**: Sempre usar o Chrome real via CDP como metodo padrao para qualquer tarefa web. Playwright ou outros browsers de teste so devem ser usados se o usuario pedir explicitamente.

## Iniciar o Chrome (se nao estiver rodando)

ANTES de qualquer tarefa de browser, verificar se o Chrome CDP ja esta ativo:

```bash
curl -s http://localhost:9222/json/version && echo "Chrome CDP ativo" || (
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=~/.brazuclaw/agent-chrome &
  sleep 2
  echo "Chrome iniciado"
)
```

**IMPORTANTE**: NUNCA fechar o Chrome apos uma tarefa. O Chrome deve permanecer aberto para reutilizacao. Fechar somente se o usuario pedir explicitamente.

## Interacao via CDP com Python

Usar `requests` (unica dependencia do BrazuClaw) para controlar o Chrome via CDP websocket ou HTTP endpoints:

### Listar abas abertas

```bash
curl -s http://localhost:9222/json
```

### Navegar para URL

```python
import json, requests

# Pegar primeira aba (ou criar nova)
tabs = requests.get("http://localhost:9222/json").json()
page_tabs = [t for t in tabs if t.get("type") == "page"]
if page_tabs:
    tab = page_tabs[0]
else:
    tab = requests.put("http://localhost:9222/json/new?about:blank").json()

tab_id = tab["id"]

# Navegar
requests.post(f"http://localhost:9222/json/activate/{tab_id}")
```

### Executar JavaScript na pagina (via CDP websocket)

```python
import json, time
from websocket import create_connection  # pip install websocket-client, se precisar

tabs = requests.get("http://localhost:9222/json").json()
ws_url = tabs[0]["webSocketDebuggerUrl"]
ws = create_connection(ws_url)

def cdp_send(method, params=None, timeout=30):
    msg_id = int(time.time() * 1000)
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            return resp.get("result", {})
    raise TimeoutError(f"CDP timeout: {method}")

# Navegar
cdp_send("Page.navigate", {"url": "https://example.com"})
time.sleep(3)

# Executar JS
result = cdp_send("Runtime.evaluate", {"expression": "document.title"})
print(result["result"]["value"])

# Screenshot (retorna base64)
shot = cdp_send("Page.captureScreenshot", {"format": "png"})
import base64
with open("/tmp/screenshot.png", "wb") as f:
    f.write(base64.b64decode(shot["data"]))

ws.close()
```

### Alternativa: controle via CLI sem websocket-client

Se `websocket-client` nao estiver disponivel, usar subprocesso com Chrome DevTools:

```bash
# Abrir URL na aba ativa
curl -s "http://localhost:9222/json/new?https://example.com"

# Screenshot via script Python minimo com apenas requests
python3 -c "
import requests, json, base64, subprocess, time

tabs = requests.get('http://localhost:9222/json').json()
ws_url = tabs[0]['webSocketDebuggerUrl']

# Usar o modulo websocket builtin nao existe, entao usar subprocess com node se disponivel
# Ou navegar e capturar com a API HTTP simples do CDP:
# Criar nova aba com URL
resp = requests.put('http://localhost:9222/json/new?https://example.com')
print(resp.json())
"
```

## Screenshot rapido via CDP

```bash
# Verificar Chrome, iniciar se necessario, navegar e capturar
curl -s http://localhost:9222/json/version > /dev/null 2>&1 || (
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=~/.brazuclaw/agent-chrome &
  sleep 2
)

# Criar aba, navegar, esperar e capturar
python3 << 'PYEOF'
import requests, json, time, base64, sys

url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
saida = sys.argv[2] if len(sys.argv) > 2 else "/tmp/brazuclaw-screenshot.png"

# Criar nova aba com a URL
tab = requests.put(f"http://localhost:9222/json/new?{url}").json()
time.sleep(4)

# Capturar via websocket
try:
    from websocket import create_connection
    ws = create_connection(tab["webSocketDebuggerUrl"])
    msg_id = 1
    ws.send(json.dumps({"id": msg_id, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
    resp = json.loads(ws.recv())
    while resp.get("id") != msg_id:
        resp = json.loads(ws.recv())
    with open(saida, "wb") as f:
        f.write(base64.b64decode(resp["result"]["data"]))
    ws.close()
    # Fechar a aba criada (manter o Chrome aberto)
    requests.post(f"http://localhost:9222/json/close/{tab['id']}")
    print(saida)
except ImportError:
    print("ERRO: pip install websocket-client", file=sys.stderr)
    sys.exit(1)
PYEOF
```

## Fluxo completo: screenshot + envio ao Telegram

```bash
# Screenshot via CDP e enviar ao Telegram
python3 ~/.brazuclaw/skills/chrome-desktop/cdp-screenshot.py https://example.com /tmp/screenshot.png && \
brazuclaw tg send --chat CHAT_ID --file /tmp/screenshot.png
```

## Padrao para tarefas de browsing

1. **Verificar se Chrome CDP esta ativo** com `curl -s http://localhost:9222/json/version`
2. **Iniciar Chrome se necessario** com o comando de lancamento acima
3. **Navegar** criando nova aba ou reutilizando aba existente
4. **Esperar renderizacao** com `time.sleep(3)` apos navegacao
5. **Remover modais** executando JS via CDP `Runtime.evaluate`
6. **Interagir** com `Runtime.evaluate` para clicar, preencher, extrair dados
7. **Screenshot** com `Page.captureScreenshot` via CDP
8. **NUNCA fechar o Chrome** — fechar apenas abas desnecessarias com `/json/close/{id}`

### JS para remover modais e overlays

```javascript
document.querySelectorAll('[class*="modal"],[class*="overlay"],[class*="popup"],[class*="cookie"],[class*="consent"],[class*="gdpr"],[class*="banner"],[id*="modal"],[id*="overlay"],[id*="cookie"],[id*="consent"]').forEach(e=>e.remove());
document.querySelectorAll('body>*,body>*>*').forEach(e=>{try{const s=getComputedStyle(e);if((s.position==='fixed'||s.position==='sticky')&&parseInt(s.zIndex||0)>100)e.remove()}catch(_){}});
document.body.style.overflow='auto';document.documentElement.style.overflow='auto';
```

Executar via CDP:
```python
cdp_send("Runtime.evaluate", {"expression": "/* JS de limpeza acima */"})
```

## Referencia rapida CDP HTTP API

| Operacao | Endpoint |
|----------|----------|
| Listar abas | `GET http://localhost:9222/json` |
| Info do browser | `GET http://localhost:9222/json/version` |
| Nova aba | `PUT http://localhost:9222/json/new?URL` |
| Fechar aba | `POST http://localhost:9222/json/close/TAB_ID` |
| Ativar aba | `POST http://localhost:9222/json/activate/TAB_ID` |

## Referencia rapida CDP Websocket

| Operacao | Metodo CDP |
|----------|-----------|
| Navegar | `Page.navigate` `{"url": "..."}` |
| Screenshot | `Page.captureScreenshot` `{"format": "png"}` |
| Executar JS | `Runtime.evaluate` `{"expression": "..."}` |
| Esperar load | `Page.loadEventFired` (evento) |
| Cookies | `Network.getCookies` / `Network.setCookie` |
| HTML da pagina | `Runtime.evaluate` `{"expression": "document.documentElement.outerHTML"}` |
| Clicar elemento | `Runtime.evaluate` `{"expression": "document.querySelector('sel').click()"}` |
| Preencher input | `Runtime.evaluate` `{"expression": "document.querySelector('sel').value='texto'"}` |
| Scroll | `Runtime.evaluate` `{"expression": "window.scrollBy(0, 500)"}` |

## Fallback: Playwright (somente se pedido pelo usuario)

Playwright so deve ser usado quando o usuario pedir EXPLICITAMENTE. Nesse caso, consultar a documentacao do Playwright para `launch_persistent_context` com perfil em `~/.brazuclaw/chrome-profile-pw/`.

## Troubleshooting

| Problema | Causa provavel | Solucao |
|----------|---------------|---------|
| Connection refused :9222 | Chrome nao esta rodando | Iniciar com o comando de lancamento |
| "websocket-client not found" | Lib nao instalada | `pip install websocket-client` |
| Chrome crasha ao iniciar | Perfil corrompido | Deletar `~/.brazuclaw/agent-chrome/` e reiniciar |
| Screenshot em branco | Pagina precisa de mais tempo | Aumentar `time.sleep()` antes do screenshot |
| Porta 9222 ocupada | Outra instancia do Chrome com CDP | `lsof -i :9222` e matar se necessario |

## Notas

- O perfil do agente fica em `~/.brazuclaw/agent-chrome/`, separado do Chrome pessoal
- Sessoes, cookies e logins persistem entre execucoes
- O Chrome DEVE permanecer aberto entre tarefas — nunca fechar automaticamente
- CDP usa o Chrome real instalado no sistema — nao e browser de teste
- Sem dependencia de Playwright ou Selenium por padrao
