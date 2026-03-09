# Chrome Desktop via Playwright

Controlar o Chrome real do desktop do usuario via Playwright com perfil persistente dedicado do BrazuClaw em `~/.brazuclaw/chrome-profile-pw/`. Sessoes, cookies e estado persistem entre execucoes.

## Screenshot rapido (comando unico)

```bash
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py URL [SAIDA] [--headless]
```

Exemplos:

```bash
# Screenshot padrao (headed, salva em /tmp/brazuclaw-screenshot.png)
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py https://example.com

# Screenshot com caminho personalizado
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py https://economist.com /tmp/economist.png

# Screenshot headless (sem janela, para crons e tasks em background)
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py https://economist.com /tmp/economist.png --headless
```

O script:
1. Lanca Chrome via Playwright com perfil persistente `~/.brazuclaw/chrome-profile-pw/`
2. Navega ate a URL com timeout de 30 segundos
3. Aguarda 3 segundos para renderizacao JavaScript
4. Para carregamentos pendentes (`window.stop()`)
5. Remove modais, overlays, banners de cookies e popups automaticamente
6. Captura screenshot do viewport e salva no caminho de saida
7. Fecha o browser ao terminar
8. Imprime o caminho do arquivo salvo em stdout; erros vao para stderr

Saida: exit 0 + caminho em stdout se sucesso, exit 1 + erro em stderr se falha.

**Prerequisito**: `playwright` instalado via pip (`pip install playwright`). Nao precisa de `playwright install` — usa o Chromium bundled do Playwright.

## Fluxo completo: screenshot + envio ao Telegram

Quando estiver em task ou cron e precisar enviar screenshot ao usuario:

```bash
python3 ~/.brazuclaw/skills/chrome-desktop/screenshot.py https://example.com /tmp/screenshot.png --headless && \
brazuclaw tg send --chat CHAT_ID --file /tmp/screenshot.png
```

Substitua `CHAT_ID` pelo ID do chat fornecido no prompt. Esse padrao e o recomendado para tarefas em segundo plano e crons.

## Interacao avancada via Playwright

Para fluxos complexos (pesquisar voos, preencher formularios, navegar entre paginas, extrair dados):

```python
from playwright.sync_api import sync_playwright

PERFIL = "~/.brazuclaw/chrome-profile-pw"  # expandir com Path.home()

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PERFIL, headless=False,
        args=["--no-sandbox", "--disable-gpu"],
        ignore_default_args=["--enable-automation"],
    )
    page = ctx.new_page()
    try:
        # Navegar
        page.goto("https://kayak.com", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Remover modais e overlays
        page.evaluate("""
            document.querySelectorAll('[class*="modal"],[class*="overlay"],[class*="popup"],[class*="cookie"],[class*="consent"],[class*="gdpr"],[class*="banner"],[id*="modal"],[id*="overlay"],[id*="cookie"],[id*="consent"]').forEach(e=>e.remove());
            document.querySelectorAll('body>*,body>*>*').forEach(e=>{try{const s=getComputedStyle(e);if((s.position==='fixed'||s.position==='sticky')&&parseInt(s.zIndex||0)>100)e.remove()}catch(_){}});
            document.body.style.overflow='auto';document.documentElement.style.overflow='auto';
        """)

        # Interagir com a pagina
        page.fill("#search", "Hawaii")
        page.click("button[type=submit]")
        page.wait_for_timeout(5000)

        # Screenshot do resultado
        page.screenshot(path="/tmp/resultado.png", timeout=30000)

        # Extrair texto
        texto = page.text_content("main")

        # Navegar para outra pagina
        page.click("a.result-link")
        page.wait_for_timeout(3000)
        page.screenshot(path="/tmp/detalhe.png", timeout=30000)
    finally:
        page.close()
        ctx.close()
```

### Padrao para tarefas complexas de browsing

Para tarefas que envolvem multiplas etapas (ex: buscar voos, comparar precos):

1. **Abrir o contexto persistente** com `launch_persistent_context` — mantem cookies/sessoes
2. **Navegar** com `page.goto(url, wait_until="domcontentloaded")` — nao usar `networkidle` em sites pesados
3. **Esperar renderizacao** com `page.wait_for_timeout(3000)` apos cada navegacao
4. **Limpar modais** com o JS de limpeza padrao
5. **Interagir** usando `page.fill()`, `page.click()`, `page.select_option()`
6. **Esperar resultados** com `page.wait_for_selector()` ou `page.wait_for_timeout()`
7. **Extrair dados** com `page.text_content()`, `page.inner_text()`, `page.query_selector_all()`
8. **Screenshot** com `page.screenshot()` para enviar ao usuario
9. **Fechar** com `page.close()` e `ctx.close()` ao terminar

### Lidando com paginas que carregam lentamente

Se a pagina travar no carregamento, usar `window.stop()` para forcar parada:

```python
page.goto(url, timeout=20000, wait_until="commit")  # esperar apenas o commit
page.wait_for_timeout(5000)  # dar tempo para renderizar
page.evaluate("window.stop()")  # parar carregamentos pendentes
page.screenshot(path=saida, timeout=30000)
```

## Referencia rapida Playwright

| Operacao | Comando |
|----------|---------|
| Navegar | `page.goto(url, timeout=30000)` |
| Clicar | `page.click(seletor)` |
| Digitar | `page.fill(seletor, texto)` |
| Selecionar | `page.select_option(seletor, valor)` |
| Screenshot | `page.screenshot(path=..., timeout=30000)` |
| Extrair texto | `page.text_content(seletor)` |
| Extrair todos | `page.query_selector_all(seletor)` |
| Esperar elemento | `page.wait_for_selector(seletor, timeout=10000)` |
| Nova aba | `ctx.new_page()` |
| Fechar aba | `page.close()` |
| Executar JS | `page.evaluate("codigo")` |
| Esperar tempo | `page.wait_for_timeout(ms)` |
| Titulo | `page.title()` |
| URL atual | `page.url` |
| Voltar | `page.go_back()` |

## Lidando com bot walls e anti-bot

1. O perfil persistente em `~/.brazuclaw/chrome-profile-pw/` acumula cookies e sessoes entre execucoes, facilitando passagem por desafios recorrentes
2. Usar `ignore_default_args=["--enable-automation"]` remove o header de automacao que sites detectam
3. Apos carregar pagina, sempre remova modais e overlays (o script `screenshot.py` faz isso automaticamente)
4. Se o site bloquear acesso com captcha ou cloudflare challenge, aguarde carregamento completo (aumente o `wait_for_timeout`)
5. Se o desafio persistir, informe o usuario que o site requer intervencao manual
6. Prefira modo headed (padrao) para sites que bloqueiam bots — headless e mais facilmente detectado

## Troubleshooting

| Problema | Causa provavel | Solucao |
|----------|---------------|---------|
| "Playwright not found" | `playwright` nao instalado via pip | `pip install playwright` (nao precisa de `playwright install`) |
| Chrome crasha ao iniciar | Perfil corrompido | Deletar `~/.brazuclaw/chrome-profile-pw/` e tentar novamente |
| Screenshot em branco | Pagina precisa de mais tempo | Aumentar `wait_for_timeout` |
| Modais ainda aparecem | Seletores de limpeza nao cobriram o modal | Adicionar seletores especificos via `page.evaluate()` |
| "Target closed" | Chrome foi fechado durante a operacao | Tentar novamente |
| Cloudflare challenge | Bot detection | Usar modo headed e `ignore_default_args=["--enable-automation"]` |
| Timeout em `page.goto` | Pagina muito pesada | Usar `wait_until="commit"` + `window.stop()` |

## Notas

- O perfil do BrazuClaw e separado do Chrome pessoal do usuario
- Sessoes, cookies e estado persistem em `~/.brazuclaw/chrome-profile-pw/`
- Modo padrao e headed (janela visivel) — melhor para anti-bot e para o usuario ver o que acontece
- Use `--headless` apenas para crons e tasks em background
- O Playwright usa o Chromium bundled — nao depende do Chrome instalado no sistema
