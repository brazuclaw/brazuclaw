#!/usr/bin/env python3
"""Captura screenshot de uma URL via Chrome CDP. Lanca Chrome automaticamente se necessario."""
import json, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:9222"
PERFIL = Path.home() / ".brazuclaw" / "chrome-profile"
SAIDA_PADRAO = "/tmp/brazuclaw-screenshot.png"
JS_LIMPAR = """
document.querySelectorAll('[class*="modal"],[class*="overlay"],[class*="popup"],[class*="cookie"],[class*="consent"],[class*="gdpr"],[class*="banner"],[id*="modal"],[id*="overlay"],[id*="cookie"],[id*="consent"]').forEach(e=>e.remove());
document.querySelectorAll('*').forEach(e=>{const s=getComputedStyle(e);if((s.position==='fixed'||s.position==='sticky')&&parseInt(s.zIndex)>100)e.remove()});
document.body.style.overflow='auto';document.documentElement.style.overflow='auto';
"""

def cdp_ativo():
    try:
        r = urllib.request.urlopen(f"{CDP}/json/version", timeout=3)
        return json.loads(r.read())
    except Exception:
        return None

def chrome_bin():
    for c in [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome", "google-chrome-stable", "chromium-browser", "chromium",
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    ]:
        if Path(c).exists() or shutil.which(c):
            return c if Path(c).exists() else shutil.which(c)
    return None

def _limpar_locks(perfil):
    for lock in ("SingletonLock", "SingletonSocket", "SingletonCookie", "DevToolsActivePort"):
        (perfil / lock).unlink(missing_ok=True)

def _tentar_lancar(b, perfil, headless):
    _limpar_locks(perfil)
    perfil.mkdir(parents=True, exist_ok=True)
    cmd = [b, "--remote-debugging-port=9222", f"--user-data-dir={perfil}",
           "--no-first-run", "--no-default-browser-check", "--no-sandbox", "--disable-gpu",
           "--disable-background-networking", "--disable-sync"]
    if headless:
        cmd.append("--headless=new")
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(30):
        time.sleep(0.5)
        if p.poll() is not None:
            return False
        if cdp_ativo():
            return True
    p.terminate()
    return False

def lancar_chrome(headless=True):
    b = chrome_bin()
    if not b:
        raise RuntimeError(
            "Chrome/Chromium nao encontrado. "
            "Instale com: apt install chromium-browser (Linux) ou baixe de google.com/chrome (macOS).")
    if _tentar_lancar(b, PERFIL, headless):
        return
    perfil_limpo = PERFIL.parent / "chrome-profile-clean"
    if _tentar_lancar(b, perfil_limpo, headless):
        return
    raise RuntimeError("Chrome nao respondeu na porta 9222. Verifique se o binario funciona.")

def screenshot(url, saida=SAIDA_PADRAO, headless=True):
    if not cdp_ativo():
        lancar_chrome(headless)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP)
        page = browser.contexts[0].new_page()
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            page.evaluate(JS_LIMPAR)
            page.wait_for_timeout(500)
            Path(saida).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=saida, full_page=False)
        finally:
            page.close()
    return saida

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: screenshot.py URL [SAIDA] [--headed]", file=sys.stderr)
        print(f"  SAIDA padrao: {SAIDA_PADRAO}", file=sys.stderr)
        sys.exit(1)
    url = sys.argv[1]
    args = sys.argv[2:]
    headed = "--headed" in args
    saida = next((a for a in args if not a.startswith("--")), SAIDA_PADRAO)
    try:
        resultado = screenshot(url, saida, headless=not headed)
        print(resultado)
    except Exception as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(1)
