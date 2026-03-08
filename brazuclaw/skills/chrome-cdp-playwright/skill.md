# Chrome CDP & Playwright

Esta skill permite o controle do Google Chrome através do protocolo CDP (Chrome DevTools Protocol) e da biblioteca Playwright.

## Objetivo
Automatizar interações no navegador, navegação web e extração de dados de forma que o estado do navegador (cookies, logins, cache) seja mantido entre diferentes sessões.

## Configuração de Perfil
O perfil do navegador Chrome deve ser obrigatoriamente armazenado no diretório `~/.brazuclaw/chrome-profile/`. Isso garante o aproveitamento do state do browser por qualquer nova sessão.

## Modo Headless
- **Padrão:** A automação deve ser executada em modo `headless` (invisível).
- **Exceção:** Caso o usuário solicite explicitamente, a execução deve ocorrer em modo não-headless (visual).

## Como utilizar (Para o Agente)
Ao escrever scripts ou usar ferramentas para controlar o navegador:
1. Utilize o Playwright (ex: `playwright-python` ou `playwright` no Node.js).
2. Para manter o perfil, lance o navegador persistente apontando para o diretório de perfil. Exemplo em Python: `playwright.chromium.launch_persistent_context("~/.brazuclaw/chrome-profile/", headless=True)`.
3. Verifique sempre o pedido do usuário para definir o parâmetro `headless` como `False` se um modo visual for requisitado.