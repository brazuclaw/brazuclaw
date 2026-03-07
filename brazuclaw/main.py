"""CLI principal, daemon e loop do bot Telegram."""
from __future__ import annotations
import base64
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from importlib import resources

from brazuclaw.codex_runner import (
    codex_esta_autenticado,
    executar_codex_monitorado,
    interpretar_resposta_codex,
    montar_prompt,
)
from brazuclaw.config import (
    ARQUIVO_ALMA,
    ARQUIVO_DB,
    ARQUIVO_LOG,
    ARQUIVO_PID,
    garantir_estrutura,
    obter_configuracao,
)
from brazuclaw.memoria import (
    garantir_banco,
    montar_contexto,
    obter_estado,
    registrar_interacao,
    salvar_estado,
    update_processado,
)
from brazuclaw.telegram_api import (
    baixar_anexo,
    buscar_updates,
    enviar_acao_digitando,
    enviar_anexo,
    enviar_texto,
    validar_token,
)
from brazuclaw.wizard import executar_wizard
EXECUTANDO = True
LIMITE_TEXTO = 1000
LIMITE_ANEXO = 256 * 1024
def registrar(status: str, chat_id: int | None = None) -> None:
    """Imprime um log simples sem dados sensiveis."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chat = "chat=----" if chat_id is None else f"chat=...{str(chat_id)[-4:]}"
    print(f"{agora} {chat} {status}")
def carregar_alma() -> str:
    """Carrega o arquivo ALMA.md do usuario ou o padrao do pacote."""
    garantir_estrutura()
    if ARQUIVO_ALMA.exists():
        return ARQUIVO_ALMA.read_text(encoding="utf-8").strip()
    conteudo = resources.files("brazuclaw").joinpath("ALMA.md").read_text(encoding="utf-8").strip()
    ARQUIVO_ALMA.write_text(conteudo + ("\n" if conteudo else ""), encoding="utf-8")
    return conteudo

def _encerrar(_sig: int, _frame: object) -> None:
    """Marca o encerramento do loop principal."""
    global EXECUTANDO
    EXECUTANDO = False

def _pid_ativo(pid: int) -> bool:
    """Confirma se um PID ainda existe e nao virou zumbi."""
    try:
        processo = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        estado = (processo.stdout or "").strip()
        if processo.returncode == 0 and estado:
            return not estado.startswith("Z")
    except Exception:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
def _aguardar_pid_encerrar(pid: int, tentativas: int, intervalo: float) -> bool:
    """Aguarda o PID encerrar dentro do limite informado."""
    for _ in range(tentativas):
        if not _pid_ativo(pid):
            return True
        time.sleep(intervalo)
    return not _pid_ativo(pid)
def _ler_pid() -> int | None:
    """Le o PID atual se existir e ainda estiver valido."""
    if not ARQUIVO_PID.exists():
        return None
    try:
        pid = int(ARQUIVO_PID.read_text(encoding="utf-8").strip())
    except Exception:
        ARQUIVO_PID.unlink(missing_ok=True)
        return None
    if _pid_ativo(pid):
        return pid
    ARQUIVO_PID.unlink(missing_ok=True)
    return None
def _gravar_pid(pid: int) -> None:
    """Persiste o PID do daemon."""
    ARQUIVO_PID.write_text(f"{pid}\n", encoding="utf-8")

def _remover_pid() -> None:
    """Remove o arquivo de PID."""
    ARQUIVO_PID.unlink(missing_ok=True)
def _daemonizar() -> None:
    """Desacopla o processo atual do terminal."""
    if os.name != "posix":
        raise SystemExit("Modo daemon exige POSIX.")
    if os.fork() > 0:
        raise SystemExit(0)
    os.setsid()
    if os.fork() > 0:
        raise SystemExit(0)
    os.umask(0o077)
    with open(os.devnull, "r", encoding="utf-8") as entrada, ARQUIVO_LOG.open("a", encoding="utf-8") as saida:
        os.dup2(entrada.fileno(), 0)
        os.dup2(saida.fileno(), 1)
        os.dup2(saida.fileno(), 2)
def _ultimas_linhas(quantidade: int) -> list[str]:
    """Retorna as ultimas linhas do arquivo de log."""
    if not ARQUIVO_LOG.exists():
        return []
    linhas = ARQUIVO_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return linhas[-quantidade:]
def _acompanhar_logs(quantidade: int) -> int:
    """Mostra as ultimas linhas e segue novas entradas."""
    for linha in _ultimas_linhas(quantidade):
        print(linha)
    posicao = ARQUIVO_LOG.stat().st_size if ARQUIVO_LOG.exists() else 0
    try:
        while True:
            if not ARQUIVO_LOG.exists():
                time.sleep(1)
                continue
            tamanho = ARQUIVO_LOG.stat().st_size
            if tamanho < posicao:
                posicao = 0
            if tamanho > posicao:
                with ARQUIVO_LOG.open("r", encoding="utf-8", errors="replace") as arquivo:
                    arquivo.seek(posicao)
                    trecho = arquivo.read()
                if trecho:
                    print(trecho, end="")
                posicao = tamanho
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
def _acao_digitando(token: str, chat_id: int) -> None:
    """Dispara o estado de digitacao sem interromper a resposta."""
    try:
        enviar_acao_digitando(token, chat_id)
    except Exception as erro:
        registrar(f"erro_digitando={erro}", chat_id)
def _extrair_anexo(token: str, mensagem: dict) -> dict | None:
    """Converte foto ou documento recebido em base64."""
    foto = mensagem.get("photo") or []
    documento = mensagem.get("document")
    item = foto[-1] if foto else documento
    if not item:
        return None
    file_id = item.get("file_id")
    if not file_id:
        return None
    mimetype, conteudo = baixar_anexo(token, file_id)
    if len(conteudo) > LIMITE_ANEXO:
        raise ValueError(f"Anexo acima do limite de {LIMITE_ANEXO // 1024} KB.")
    nome = "imagem.jpg" if foto else item.get("file_name", "arquivo.bin")
    return {
        "nome": nome[:120],
        "mimetype": documento.get("mime_type", mimetype) if documento else mimetype,
        "anexo_b64": base64.b64encode(conteudo).decode("ascii"),
    }
def _enviar_resposta(token: str, chat_id: int, resposta: dict[str, object]) -> tuple[str, dict | None]:
    """Envia texto e anexos da resposta ao Telegram."""
    texto = str(resposta.get("texto", "")).strip()
    anexos = resposta.get("anexos", [])
    assert isinstance(anexos, list)
    try:
        if texto:
            enviar_texto(token, chat_id, texto)
        anexo_salvo = None
        for indice, anexo in enumerate(anexos):
            legenda = "" if texto or indice > 0 else "Anexo gerado pelo BrazuClaw."
            enviar_anexo(
                token,
                chat_id,
                anexo.get("nome", "anexo.bin"),
                anexo.get("anexo_b64", ""),
                anexo.get("mimetype", "application/octet-stream"),
                legenda,
            )
            if anexo_salvo is None:
                anexo_salvo = anexo
        if not texto and not anexos:
            texto = "Sem resposta do Codex CLI."
            enviar_texto(token, chat_id, texto)
        return texto, anexo_salvo
    except Exception as erro:
        aviso = f"Falha ao enviar resposta do Codex: {erro}"
        enviar_texto(token, chat_id, aviso[:4000])
        return aviso, None
def _referencia_anexo(chat_id: int, update_id: int, anexo: dict | None) -> list[dict]:
    """Monta uma referencia curta para anexos salvos no banco."""
    if not anexo:
        return []
    return [
        {
            "chat_id": chat_id,
            "update_id": update_id,
            "nome": anexo.get("nome", "anexo.bin"),
            "mimetype": anexo.get("mimetype", "application/octet-stream"),
            "banco_sqlite": str(ARQUIVO_DB),
        }
    ]
def _responder_mensagem(token: str, mensagem: dict, update_id: int) -> None:
    """Processa uma unica mensagem valida."""
    chat = mensagem["chat"]
    chat_id = chat["id"]
    if chat.get("type") != "private":
        registrar("ignorado_chat_nao_privado", chat_id)
        return
    texto = (mensagem.get("text") or mensagem.get("caption") or "").strip()
    if len(texto) > LIMITE_TEXTO:
        enviar_texto(token, chat_id, "Mensagem longa demais. Limite de 1000 caracteres.")
        registrar("ignorado_texto_longo", chat_id)
        return
    try:
        anexo = _extrair_anexo(token, mensagem)
    except ValueError as erro:
        enviar_texto(token, chat_id, str(erro))
        registrar("ignorado_anexo_longo", chat_id)
        return
    except Exception as erro:
        enviar_texto(token, chat_id, f"Falha ao ler anexo: {erro}")
        registrar("erro_anexo", chat_id)
        return
    if not texto and not anexo:
        enviar_texto(token, chat_id, "Envie texto, imagem ou arquivo.")
        registrar("ignorado_sem_conteudo", chat_id)
        return
    registrar_interacao(
        chat_id,
        "humano",
        texto,
        anexo["anexo_b64"] if anexo else "",
        anexo["mimetype"] if anexo else "",
        anexo["nome"] if anexo else "",
        update_id,
        "recebida",
    )
    contexto = montar_contexto(chat_id)
    prompt = montar_prompt(
        carregar_alma(),
        contexto,
        texto,
        referencias_anexos=_referencia_anexo(chat_id, update_id, anexo),
    )
    registrar("codex_exec_inicio", chat_id)
    try:
        bruto = executar_codex_monitorado(prompt, ao_aguardar=lambda: _acao_digitando(token, chat_id))
        resposta = interpretar_resposta_codex(bruto)
    except subprocess.TimeoutExpired:
        resposta = {"texto": "O Codex demorou mais de 120 segundos e a execucao foi abortada.", "anexos": []}
    except Exception as erro:
        resposta = {"texto": f"Falha ao consultar o Codex: {erro}", "anexos": []}
    texto_resposta, anexo_resposta = _enviar_resposta(token, chat_id, resposta)
    registrar_interacao(
        chat_id,
        "agente",
        texto_resposta,
        anexo_resposta["anexo_b64"] if anexo_resposta else "",
        anexo_resposta["mimetype"] if anexo_resposta else "",
        anexo_resposta["nome"] if anexo_resposta else "",
        update_id,
        "respondida",
    )
    registrar("resposta_enviada", chat_id)
def rodar_bot() -> int:
    """Executa o loop de polling do Telegram."""
    garantir_estrutura()
    garantir_banco()
    config = obter_configuracao()
    if "BRAZUCLAW_TOKEN" not in config:
        print("Configuracao incompleta. Executando wizard.")
        return executar_wizard()
    if not codex_esta_autenticado():
        print("Autenticacao do Codex ausente ou expirada. Executando wizard.")
        return executar_wizard()
    signal.signal(signal.SIGINT, _encerrar)
    signal.signal(signal.SIGTERM, _encerrar)
    token = config["BRAZUCLAW_TOKEN"]
    offset_texto = obter_estado("telegram_offset", "")
    offset = int(offset_texto) if offset_texto.isdigit() else None
    registrar("bot_iniciado")
    try:
        while EXECUTANDO:
            try:
                updates = buscar_updates(token, offset)
                for update in updates:
                    update_id = update["update_id"]
                    proximo_offset = update_id + 1
                    if update_processado(update_id):
                        offset = proximo_offset
                        salvar_estado("telegram_offset", str(offset))
                        continue
                    mensagem = update.get("message")
                    if mensagem:
                        _responder_mensagem(token, mensagem, update_id)
                    offset = proximo_offset
                    salvar_estado("telegram_offset", str(offset))
            except KeyboardInterrupt:
                break
            except Exception as erro:
                registrar(f"erro_polling={erro}")
                time.sleep(2)
    finally:
        _remover_pid()
        registrar("bot_encerrado")
    return 0
def _nome_bot() -> str:
    """Retorna um nome legivel do bot configurado."""
    token = obter_configuracao().get("BRAZUCLAW_TOKEN")
    if not token:
        return "desconhecido"
    try:
        bot = validar_token(token)
    except Exception:
        return "desconhecido"
    return bot.get("username") or bot.get("first_name") or "desconhecido"
def iniciar_daemon() -> int:
    """Inicia o bot em background."""
    garantir_estrutura()
    config = obter_configuracao()
    if "BRAZUCLAW_TOKEN" not in config:
        print("Configuracao incompleta. Executando wizard.")
        return executar_wizard()
    if not codex_esta_autenticado():
        print("Autenticacao do Codex ausente ou expirada. Executando wizard.")
        return executar_wizard()
    pid = _ler_pid()
    if pid is not None:
        print(f"BrazuClaw ja esta em execucao no PID {pid}.")
        return 0
    nome_bot = _nome_bot()
    print(f"serviço Brazuclaw iniciado, bot nome {nome_bot}")
    _daemonizar()
    _gravar_pid(os.getpid())
    return rodar_bot()
def parar_daemon() -> int:
    """Encerra o daemon em execucao."""
    pid = _ler_pid()
    if pid is None:
        print("BrazuClaw nao esta em execucao.")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _remover_pid()
        print("BrazuClaw foi encerrado.")
        return 0
    if _aguardar_pid_encerrar(pid, 150, 0.2):
        _remover_pid()
        print("BrazuClaw foi encerrado.")
        return 0
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        _remover_pid()
        print("BrazuClaw foi encerrado.")
        return 0
    if _aguardar_pid_encerrar(pid, 25, 0.2):
        _remover_pid()
        print("BrazuClaw foi encerrado a forca.")
        return 0
    print(f"Nao foi possivel confirmar o encerramento do PID {pid}.")
    return 1
def reiniciar_daemon() -> int:
    """Reinicia o daemon em execucao."""
    codigo = parar_daemon()
    if codigo != 0:
        return codigo
    return iniciar_daemon()
def mostrar_logs(argumentos: list[str]) -> int:
    """Exibe logs recentes ou segue em tempo real."""
    seguir = any(arg in ("-f", "--follow", "tail") for arg in argumentos)
    numeros = [arg for arg in argumentos if arg.isdigit()]
    quantidade = int(numeros[-1]) if numeros else 50
    if seguir:
        return _acompanhar_logs(quantidade)
    for linha in _ultimas_linhas(quantidade):
        print(linha)
    return 0
def cli() -> int:
    """Despacha os subcomandos disponiveis."""
    argumentos = sys.argv[1:]
    if not argumentos or argumentos[0] == "start":
        return iniciar_daemon()
    if argumentos[0] == "setup":
        return executar_wizard()
    if argumentos[0] == "stop":
        return parar_daemon()
    if argumentos[0] == "restart":
        return reiniciar_daemon()
    if argumentos[0] == "logs":
        return mostrar_logs(argumentos[1:])
    print("Uso: brazuclaw [setup|start|stop|restart|logs]")
    return 1
