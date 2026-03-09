#!/usr/bin/env python3
"""Captura screenshot de uma URL via Playwright com perfil persistente."""
import sys
from pathlib import Path

PERFIL = str(Path.home() / ".brazuclaw" / "chrome-profile-pw")
SAIDA_PADRAO = "/tmp/brazuclaw-screenshot.png"
JS_LIMPAR = """
document.querySelectorAll('[class*="modal"],[class*="overlay"],[class*="popup"],[class*="cookie"],[class*="consent"],[class*="gdpr"],[class*="banner"],[id*="modal"],[id*="overlay"],[id*="cookie"],[id*="consent"]').forEach(e=>e.remove());
document.querySelectorAll('body>*,body>*>*').forEach(e=>{try{const s=getComputedStyle(e);if((s.position==='fixed'||s.position==='sticky')&&parseInt(s.zIndex||0)>100)e.remove()}catch(_){}});
document.body.style.overflow='auto';document.documentElement.style.overflow='auto';
"""

def screenshot(url, saida=SAIDA_PADRAO, headless=False):
    """Captura screenshot via Playwright. Padrao: headed (--headless para sem janela)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PERFIL, headless=headless,
            args=["--no-sandbox", "--disable-gpu",
                  "--disable-background-networking", "--disable-sync"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            page.evaluate("window.stop()")
            try:
                page.evaluate(JS_LIMPAR)
            except Exception:
                pass
            page.wait_for_timeout(500)
            Path(saida).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=saida, full_page=False, timeout=30000)
        finally:
            page.close()
            ctx.close()
    return saida

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: screenshot.py URL [SAIDA] [--headless]", file=sys.stderr)
        print(f"  SAIDA padrao: {SAIDA_PADRAO}", file=sys.stderr)
        sys.exit(1)
    url = sys.argv[1]
    args = sys.argv[2:]
    headless = "--headless" in args
    saida = next((a for a in args if not a.startswith("--")), SAIDA_PADRAO)
    try:
        resultado = screenshot(url, saida, headless=headless)
        print(resultado)
    except Exception as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(1)
