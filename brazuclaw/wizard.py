"""Wizard interativo de onboarding."""
from __future__ import annotations
import platform, re, shutil, subprocess, sys
from importlib import resources
from brazuclaw.codex_runner import codex_esta_autenticado
from brazuclaw.config import ARQUIVO_ALMA, garantir_estrutura, obter_configuracao, salvar_chave
from brazuclaw.telegram_api import validar_token

PADRAO_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")

def _perguntar(texto: str) -> str:
    """Le uma resposta simples do terminal."""
    return input(texto).strip()
def _confirmar(texto: str) -> bool:
    """Solicita confirmacao do usuario."""
    return _perguntar(texto + " [s/N]: ").lower() == "s"
def _descobrir_so() -> tuple[str, str]:
    """Detecta o sistema operacional atual."""
    sistema, release = platform.system().lower(), platform.release().lower()
    if sistema == "linux" and "microsoft" in release:
        return "wsl", "WSL"
    if sistema == "linux":
        return "linux", "Linux"
    if sistema == "darwin":
        return "macos", "macOS"
    if sistema == "windows":
        return "windows", "Windows"
    return sistema, platform.system()
def _comando_instalacao_node(chave_so: str) -> str:
    """Retorna um comando sugerido para instalar Node.js."""
    return "sudo apt-get update && sudo apt-get install -y nodejs npm" if chave_so in ("linux", "wsl") else ("brew install node" if chave_so == "macos" else "")
def _versao_maior(comando: list[str]) -> int:
    """Le a versao principal de um comando como inteiro."""
    try:
        saida = subprocess.check_output(comando, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return 0
    numeros = re.findall(r"\d+", saida)
    return int(numeros[0]) if numeros else 0
def _executar_comando(comando: str, env: dict[str, str] | None = None) -> bool:
    """Executa um comando shell simples."""
    return subprocess.run(["bash", "-lc", comando], env=env).returncode == 0
def _codex_login() -> None:
    """Abre o fluxo de login do Codex CLI via device auth."""
    if not (caminho := shutil.which("codex")):
        raise SystemExit("Codex CLI nao encontrado no PATH.")
    if subprocess.run([caminho, "login", "--device-auth"]).returncode != 0:
        raise SystemExit("Falha ao iniciar `codex login --device-auth`.")
def _configurar_chave(nome: str, prompt: str, validador, invalida: str) -> str:
    """Pede um valor, valida e salva quando aprovado."""
    while True:
        valor = obter_configuracao().get(nome) or _perguntar(prompt)
        if not valor:
            print("Valor vazio.")
            continue
        try:
            retorno = validador(valor)
        except Exception as erro:
            print(f"{invalida}: {erro}")
            salvar_chave(nome, "")
            continue
        salvar_chave(nome, valor)
        return retorno
def _etapa_so() -> str:
    """Executa a verificacao do sistema operacional."""
    chave_so, nome_so = _descobrir_so()
    print(f"SO detectado: {nome_so}")
    if chave_so == "windows":
        print("Windows nativo nao e suportado. Use WSL: https://learn.microsoft.com/windows/wsl/install")
        raise SystemExit(1)
    if not _confirmar("Continuar com este sistema?"):
        raise SystemExit(1)
    return chave_so
def _etapa_python() -> None:
    """Confirma Python 3.11 ou superior."""
    versao = sys.version_info
    print(f"Python detectado: {versao.major}.{versao.minor}.{versao.micro}")
    if versao < (3, 11):
        print("Python 3.11 ou superior e obrigatorio.")
        raise SystemExit(1)
def _etapa_node(chave_so: str) -> None:
    """Verifica e opcionalmente instala Node.js."""
    if (versao := _versao_maior(["node", "--version"])) >= 18:
        print(f"Node.js detectado: v{versao}")
        return
    comando = _comando_instalacao_node(chave_so)
    print("Node.js 18+ nao encontrado.")
    if not comando:
        raise SystemExit("Instale Node.js 18+ manualmente e rode o wizard novamente.")
    print(f"Comando sugerido: {comando}")
    if not _confirmar("Executar este comando agora?") or not _executar_comando(comando) or _versao_maior(["node", "--version"]) < 18:
        raise SystemExit("Falha ao instalar Node.js 18+.")
def _etapa_codex() -> None:
    """Verifica e opcionalmente instala o Codex CLI."""
    if shutil.which("codex"):
        print("Codex CLI detectado.")
        return
    print("Codex CLI nao encontrado.")
    if not _confirmar("Instalar com npm install -g @openai/codex?") or not _executar_comando("npm install -g @openai/codex") or not shutil.which("codex"):
        raise SystemExit("Falha ao instalar o Codex CLI.")
def _etapa_openai() -> None:
    """Garante autenticacao do Codex CLI via OAuth."""
    print("Verificando autenticacao do Codex CLI...")
    if codex_esta_autenticado():
        return print("Codex CLI autenticado com sucesso.")
    print("Sessao do Codex nao esta ativa.")
    print("O BrazuClaw usa login OAuth do Codex CLI.")
    print("Se esta em maquina remota ou headless, use o fluxo por device auth.")
    _codex_login()
    if not codex_esta_autenticado():
        raise SystemExit("Falha ao autenticar o Codex CLI. Rode `codex login --device-auth` e tente novamente.")
    print("Codex CLI autenticado com sucesso.")
def _mostrar_instrucoes_botfather() -> None:
    """Mostra o passo a passo resumido para criar o bot."""
    print("Crie um bot no Telegram:")
    print("1. Abra o Telegram e procure @BotFather")
    print("2. Envie /newbot")
    print("3. Defina nome e username do bot")
    print("4. Copie o token gerado")
def _etapa_telegram() -> None:
    """Configura e valida BRAZUCLAW_TOKEN."""
    _mostrar_instrucoes_botfather()
    def validar(token: str) -> str:
        if not PADRAO_TOKEN.match(token):
            raise RuntimeError("formato de token invalido")
        return validar_token(token).get("username", "sem_username")
    print(f'Token validado. Bot: @{_configurar_chave("BRAZUCLAW_TOKEN", "Cole o token do bot: ", validar, "Token invalido")}')
def _etapa_personalidade() -> None:
    """Cria o arquivo ALMA.md se estiver ausente."""
    if ARQUIVO_ALMA.exists():
        return print(f"Arquivo ALMA existente: {ARQUIVO_ALMA}")
    ARQUIVO_ALMA.write_text(resources.files("brazuclaw").joinpath("ALMA.md").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Arquivo ALMA criado em: {ARQUIVO_ALMA}")
def _etapa_teste_final() -> None:
    """Faz um teste simples do Codex CLI e orienta o teste manual no Telegram."""
    print("Teste local do Codex CLI em andamento...")
    if not codex_esta_autenticado():
        raise SystemExit("Falha no teste local do Codex CLI.")
    print("Teste local OK.")
    print("Teste de ponta a ponta desta PoC e manual:")
    print("1. Rode o comando: brazuclaw")
    print("2. Envie uma mensagem privada ao seu bot no Telegram")
    print("3. Confirme se a resposta chegou")
def _etapa_resumo(chave_so: str) -> None:
    """Exibe o resumo final da configuracao."""
    config = obter_configuracao()
    print("Resumo final:")
    print(f"- SO: {chave_so}")
    print(f"- Node.js: {_versao_maior(['node', '--version'])}")
    print(f"- Codex CLI: {'ok' if shutil.which('codex') else 'pendente'}")
    print(f"- Token Telegram: {'ok' if config.get('BRAZUCLAW_TOKEN') else 'pendente'}")
    print(f"- ALMA: {ARQUIVO_ALMA}")
    print("Para iniciar o bot: brazuclaw")
def executar_wizard() -> int:
    """Executa o wizard completo."""
    garantir_estrutura()
    chave_so = _etapa_so()
    _etapa_python(), _etapa_node(chave_so), _etapa_codex(), _etapa_openai(), _etapa_telegram(), _etapa_personalidade(), _etapa_teste_final(), _etapa_resumo(chave_so)
    return 0
def cli() -> int:
    """Ponto de entrada do comando brazuclaw-setup."""
    return executar_wizard()
