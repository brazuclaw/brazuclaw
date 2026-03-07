"""CLI principal, daemon, Telegram e scheduler interno."""
from __future__ import annotations
import base64, os, signal, subprocess, sys, time
from datetime import datetime, timedelta
from importlib import resources
from brazuclaw.codex_runner import codex_esta_autenticado, executar_codex_monitorado, interpretar_resposta_codex, montar_prompt, montar_prompt_cron
from brazuclaw.config import ARQUIVO_ALMA, ARQUIVO_DB, ARQUIVO_LOG, ARQUIVO_PID, garantir_estrutura, obter_configuracao
from brazuclaw.memoria import atualizar_cron, criar_cron, crons_vencidos, garantir_banco, limpar_execucoes_crons, listar_crons, montar_contexto, obter_cron, obter_estado, registrar_interacao, remover_cron, salvar_estado, update_processado
from brazuclaw.telegram_api import baixar_anexo, buscar_updates, enviar_acao_digitando, enviar_anexo, enviar_texto, validar_token
from brazuclaw.wizard import executar_wizard

EXECUTANDO, LIMITE_TEXTO, LIMITE_ANEXO = True, 1000, 256 * 1024

def registrar(status: str, chat_id: int | None = None) -> None:
    """Imprime um log simples sem dados sensiveis."""
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {'chat=----' if chat_id is None else f'chat=...{str(chat_id)[-4:]}'} {status}")
def carregar_alma() -> str:
    """Carrega o arquivo ALMA do usuario ou do pacote."""
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
    """Confirma se o PID existe e nao virou zumbi."""
    try:
        estado = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False, timeout=2).stdout.strip()
        if estado:
            return not estado.startswith("Z")
    except Exception:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
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
        os.dup2(entrada.fileno(), 0), os.dup2(saida.fileno(), 1), os.dup2(saida.fileno(), 2)
def _ultimas_linhas(quantidade: int) -> list[str]:
    """Retorna as ultimas linhas do arquivo de log."""
    return ARQUIVO_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-quantidade:] if ARQUIVO_LOG.exists() else []
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
                    print(arquivo.read(), end="")
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
    foto, documento = mensagem.get("photo") or [], mensagem.get("document")
    item = foto[-1] if foto else documento
    if not item or not item.get("file_id"):
        return None
    mimetype, conteudo = baixar_anexo(token, item["file_id"])
    if len(conteudo) > LIMITE_ANEXO:
        raise ValueError(f"Anexo acima do limite de {LIMITE_ANEXO // 1024} KB.")
    return {"nome": ("imagem.jpg" if foto else item.get("file_name", "arquivo.bin"))[:120], "mimetype": documento.get("mime_type", mimetype) if documento else mimetype, "anexo_b64": base64.b64encode(conteudo).decode("ascii")}
def _enviar_resposta(token: str, chat_id: int, resposta: dict[str, object]) -> tuple[str, dict | None]:
    """Envia texto e anexos da resposta ao Telegram."""
    texto, anexos, primeiro = str(resposta.get("texto", "")).strip(), resposta.get("anexos", []), None
    assert isinstance(anexos, list)
    try:
        if texto:
            enviar_texto(token, chat_id, texto)
        for indice, anexo in enumerate(anexos):
            enviar_anexo(token, chat_id, anexo.get("nome", "anexo.bin"), anexo.get("anexo_b64", ""), anexo.get("mimetype", "application/octet-stream"), "" if texto or indice else "Anexo gerado pelo BrazuClaw.")
            primeiro = primeiro or anexo
        if not texto and not anexos:
            texto = "Sem resposta do Codex CLI."
            enviar_texto(token, chat_id, texto)
        return texto, primeiro
    except Exception as erro:
        aviso = f"Falha ao enviar resposta do Codex: {erro}"
        enviar_texto(token, chat_id, aviso[:4000])
        return aviso, None
def _aplicar_crons(chat_id: int, resposta: dict[str, object]) -> dict[str, object]:
    """Cria cron jobs pedidos pelo agente e adiciona confirmacoes ao texto."""
    crons = resposta.get("crons", [])
    if not isinstance(crons, list) or not crons:
        return resposta
    avisos, ids = [], []
    for cron in crons:
        try:
            callback = str(cron.get("callback", "sempre")).strip() or "sempre"
            if callback not in ("nunca", "erro", "sempre"):
                callback = "sempre"
            timeout = max(30, int(cron.get("timeout", 120) or 120))
            schedule = str(cron.get("schedule", "")).strip()
            cron_id = criar_cron(str(cron.get("nome", "cron"))[:80], str(cron.get("prompt", "")).strip(), schedule, chat_id if callback != "nunca" else 0, callback, timeout, _proximo_schedule(schedule))
            ids.append(cron_id)
            avisos.append(f'Cron #{cron_id} criado: "{cron.get("nome", "cron")}" em `{schedule}`.')
        except Exception as erro:
            avisos.append(f'Falha ao criar cron "{cron.get("nome", "cron")}": {erro}')
    texto = str(resposta.get("texto", "")).strip()
    resposta["texto"] = "\n\n".join(parte for parte in [texto, "\n".join(avisos)] if parte).strip()
    resposta["crons"] = []
    registrar(("cron_criado=" + ",".join(map(str, ids))) if ids else "cron_criacao_falhou", chat_id)
    return resposta
def _resposta_local_cron(chat_id: int, texto: str) -> dict[str, object] | None:
    """Resolve listagem e remocao simples de crons sem depender do Codex."""
    t = " ".join((texto or "").lower().split())
    if not t or not any(p in t for p in ("job", "jobs", "agend", "cron")): return None
    crons = [c for c in listar_crons(True) if int(c["chat_callback_id"] or 0) == chat_id]
    if any(p in t for p in ("liste", "listar", "lista", "quais", "mostre")):
        if not crons: return {"texto": "No momento, nao ha nenhum agendamento ativo.", "anexos": []}
        itens = [f'{i}. nome: {c["nome"]}\nschedule: {c["schedule"]}\ncallback: {c["callback_quando"]}\ninstrucao: {c["prompt"]}' for i, c in enumerate(crons, 1)]
        return {"texto": "Jobs em agenda no momento:\n\n" + "\n\n".join(itens), "anexos": []}
    if any(p in t for p in ("remova", "remove", "apague", "delete", "cancele", "cancel", "exclua")):
        alvo = crons[:1] if any(p in t for p in ("antig", "older", "mais velho")) else crons; [remover_cron(int(c["id"])) for c in alvo]
        return {"texto": ("Cron mais antigo removido." if alvo and len(alvo) == 1 and len(crons) > 1 else "Todos os jobs agendados foram removidos.") if alvo else "No momento, nao ha nenhum agendamento ativo.", "anexos": []}
    return None
def _referencia_anexo(chat_id: int, update_id: int, anexo: dict | None) -> list[dict]:
    """Monta uma referencia curta para anexos salvos no banco."""
    return [] if not anexo else [{"chat_id": chat_id, "update_id": update_id, "nome": anexo.get("nome", "anexo.bin"), "mimetype": anexo.get("mimetype", "application/octet-stream"), "banco_sqlite": str(ARQUIVO_DB)}]
def _rodar_instancia(sessao_id: int, mensagem: str, timeout: int = 120, ao_aguardar=None, ao_iniciar=None, deve_abortar=None, referencias_anexos: list[dict] | None = None) -> tuple[dict[str, object], str]:
    """Executa uma chamada ao Codex com memoria e ALMA compartilhadas."""
    prompt = montar_prompt(carregar_alma(), montar_contexto(sessao_id), mensagem, referencias_anexos=referencias_anexos)
    try:
        return interpretar_resposta_codex(executar_codex_monitorado(prompt, ao_aguardar=ao_aguardar, ao_iniciar=ao_iniciar, deve_abortar=deve_abortar, timeout=timeout)), "ok"
    except subprocess.TimeoutExpired:
        return {"texto": f"O Codex demorou mais de {timeout} segundos e a execucao foi abortada.", "anexos": []}, "timeout"
    except Exception as erro:
        abortado = "abortada" in str(erro).lower()
        return {"texto": "Execucao abortada pelo usuario." if abortado else f"Falha ao consultar o Codex: {erro}", "anexos": []}, ("abortado" if abortado else "erro")
def _registrar_saida(sessao_id: int, resposta: dict[str, object], update_id: int = 0) -> None:
    """Registra a saida de uma instancia na memoria."""
    anexo = resposta.get("anexos", [None])[0] if isinstance(resposta.get("anexos", []), list) and resposta.get("anexos") else None
    registrar_interacao(sessao_id, "agente", str(resposta.get("texto", "")), anexo["anexo_b64"] if anexo else "", anexo["mimetype"] if anexo else "", anexo["nome"] if anexo else "", update_id, "respondida")
def _responder_mensagem(token: str, mensagem: dict, update_id: int) -> None:
    """Processa uma unica mensagem valida."""
    chat_id = mensagem["chat"]["id"]
    if mensagem["chat"].get("type") != "private":
        return registrar("ignorado_chat_nao_privado", chat_id)
    texto = (mensagem.get("text") or mensagem.get("caption") or "").strip()
    if len(texto) > LIMITE_TEXTO:
        enviar_texto(token, chat_id, "Mensagem longa demais. Limite de 1000 caracteres.")
        return registrar("ignorado_texto_longo", chat_id)
    try:
        anexo = _extrair_anexo(token, mensagem)
    except ValueError as erro:
        enviar_texto(token, chat_id, str(erro))
        return registrar("ignorado_anexo_longo", chat_id)
    except Exception as erro:
        enviar_texto(token, chat_id, f"Falha ao ler anexo: {erro}")
        return registrar("erro_anexo", chat_id)
    if not texto and not anexo:
        enviar_texto(token, chat_id, "Envie texto, imagem ou arquivo.")
        return registrar("ignorado_sem_conteudo", chat_id)
    registrar_interacao(chat_id, "humano", texto, anexo["anexo_b64"] if anexo else "", anexo["mimetype"] if anexo else "", anexo["nome"] if anexo else "", update_id, "recebida")
    if resposta_local := _resposta_local_cron(chat_id, texto):
        texto_resposta, anexo_resposta = _enviar_resposta(token, chat_id, resposta_local)
        registrar_interacao(chat_id, "agente", texto_resposta, anexo_resposta["anexo_b64"] if anexo_resposta else "", anexo_resposta["mimetype"] if anexo_resposta else "", anexo_resposta["nome"] if anexo_resposta else "", update_id, "respondida")
        return registrar("resposta_local_cron", chat_id)
    registrar("codex_exec_inicio", chat_id)
    resposta, _ = _rodar_instancia(chat_id, texto, ao_aguardar=lambda: _acao_digitando(token, chat_id), referencias_anexos=_referencia_anexo(chat_id, update_id, anexo))
    resposta = _aplicar_crons(chat_id, resposta)
    texto_resposta, anexo_resposta = _enviar_resposta(token, chat_id, resposta)
    registrar_interacao(chat_id, "agente", texto_resposta, anexo_resposta["anexo_b64"] if anexo_resposta else "", anexo_resposta["mimetype"] if anexo_resposta else "", anexo_resposta["nome"] if anexo_resposta else "", update_id, "respondida")
    registrar("resposta_enviada", chat_id)
def _valores_cron(campo: str, minimo: int, maximo: int) -> tuple[set[int] | None, bool]:
    """Converte um campo de cron em um conjunto de inteiros."""
    if campo == "*":
        return None, True
    valores = set()
    for parte in campo.split(","):
        base, passo = (parte.split("/", 1) + ["1"])[:2]
        inicio, fim = (minimo, maximo) if base == "*" else map(int, base.split("-", 1) if "-" in base else [base, base])
        if inicio < minimo or fim > maximo or inicio > fim or int(passo) < 1:
            raise ValueError("Campo cron invalido.")
        valores.update(range(inicio, fim + 1, int(passo)))
    return valores, False
def _cron_casa(schedule: str, instante: datetime) -> bool:
    """Verifica se um horario casa com a expressao cron."""
    minuto, hora, dom, mes, dow = schedule.split()
    vm, _ = _valores_cron(minuto, 0, 59)
    vh, _ = _valores_cron(hora, 0, 23)
    vd, livre_dom = _valores_cron(dom, 1, 31)
    vme, _ = _valores_cron(mes, 1, 12)
    vw, livre_dow = _valores_cron(dow, 0, 6)
    dom_ok, dow_ok = vd is None or instante.day in vd, vw is None or ((instante.weekday() + 1) % 7) in vw
    return (vm is None or instante.minute in vm) and (vh is None or instante.hour in vh) and (vme is None or instante.month in vme) and ((dom_ok or dow_ok) if not livre_dom and not livre_dow else dom_ok and dow_ok)
def _proximo_schedule(schedule: str, base: int | None = None) -> int:
    """Retorna o proximo horario futuro para uma expressao cron."""
    instante = datetime.fromtimestamp(base or time.time()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if _cron_casa(schedule, instante):
            return int(instante.timestamp())
        instante += timedelta(minutes=1)
    raise ValueError("Nao foi possivel calcular o proximo horario.")
def _sincronizar_crons() -> None:
    """Recalcula o proximo horario dos crons ativos ao iniciar o servico."""
    limpar_execucoes_crons()
    base = int(time.time()) - 60
    for cron in listar_crons():
        atualizar_cron(cron["id"], proximo_em=_proximo_schedule(cron["schedule"], base) if cron["ativo"] else 0)
def _deve_notificar(cron: dict, status: str) -> bool:
    """Decide se o cron deve fazer callback para o Telegram."""
    return bool(cron["chat_callback_id"]) and (cron["callback_quando"] == "sempre" or (cron["callback_quando"] == "erro" and status != "ok"))
def _cron_deve_abortar(cron_id: int) -> bool:
    """Interrompe quando o cron foi removido ou recebeu pedido de aborto."""
    cron = obter_cron(cron_id)
    return not cron or bool(cron["abortar"])
def _cron_foi_removido(cron_id: int) -> bool:
    """Informa se o cron nao existe mais no banco."""
    return obter_cron(cron_id) is None
def _notificar_cron(token: str, cron: dict, resposta: dict[str, object], status: str) -> None:
    """Envia callback do cron ao Telegram quando configurado."""
    if not token or not _deve_notificar(cron, status):
        return
    texto = str(resposta.get("texto", "")).strip()
    corpo = {"texto": texto if status == "ok" else f'Cron #{cron["id"]} "{cron["nome"]}" {status}.\n\n{texto}'.strip(), "anexos": resposta.get("anexos", []) if status == "ok" else []}
    _enviar_resposta(token, int(cron["chat_callback_id"]), corpo)
def _executar_cron(cron: dict, token: str) -> None:
    """Executa um cron vencido como instancia BrazuClaw."""
    cron_id, sessao_id = int(cron["id"]), -int(cron["id"])
    cron_atual = obter_cron(cron_id)
    if not cron_atual or not int(cron_atual["ativo"]):
        registrar("cron_ignorado_removido", sessao_id)
        return
    cron = dict(cron_atual)
    prompt = str(cron["prompt"]).strip()
    atualizar_cron(cron_id, ultima_execucao_em=int(time.time()), ultimo_status="executando", abortar=0, pid_atual=-1)
    registrar_interacao(sessao_id, "humano", prompt, status="recebida")
    prompt_codex = montar_prompt_cron(carregar_alma(), montar_contexto(sessao_id), str(cron["nome"]), prompt)
    try:
        resposta, status = interpretar_resposta_codex(executar_codex_monitorado(prompt_codex, ao_iniciar=lambda pid: atualizar_cron(cron_id, pid_atual=pid), deve_abortar=lambda: _cron_deve_abortar(cron_id), timeout=int(cron["timeout_segundos"]))), "ok"
    except subprocess.TimeoutExpired:
        resposta, status = {"texto": f'O cron "{cron["nome"]}" demorou mais de {int(cron["timeout_segundos"])} segundos e foi abortado.', "anexos": []}, "timeout"
    except Exception as erro:
        abortado = "abortada" in str(erro).lower()
        resposta, status = ({"texto": "Execucao cancelada porque o cron foi removido." if abortado and _cron_foi_removido(cron_id) else ("Execucao abortada pelo usuario." if abortado else f"Falha ao consultar o Codex: {erro}"), "anexos": []}, ("removido" if abortado and _cron_foi_removido(cron_id) else ("abortado" if abortado else "erro")))
    _registrar_saida(sessao_id, resposta)
    if cron_final := obter_cron(cron_id):
        atualizar_cron(cron_id, ultimo_status=status, pid_atual=0, abortar=0, proximo_em=_proximo_schedule(cron["schedule"]) if cron_final["ativo"] else 0, ultima_execucao_em=int(time.time()))
        _notificar_cron(token, dict(cron_final), resposta, status)
    registrar(f"cron_{status}", sessao_id)
def rodar_bot() -> int:
    """Executa o loop de polling do Telegram e do scheduler."""
    garantir_estrutura(), garantir_banco()
    config = obter_configuracao()
    if "BRAZUCLAW_TOKEN" not in config:
        print("Configuracao incompleta. Executando wizard.")
        return executar_wizard()
    if not codex_esta_autenticado():
        print("Autenticacao do Codex ausente ou expirada. Executando wizard.")
        return executar_wizard()
    signal.signal(signal.SIGINT, _encerrar), signal.signal(signal.SIGTERM, _encerrar)
    token, offset_texto = config["BRAZUCLAW_TOKEN"], obter_estado("telegram_offset", "")
    offset = int(offset_texto) if offset_texto.isdigit() else None
    _sincronizar_crons(), salvar_estado("scheduler_ativo", "1"), registrar("bot_iniciado")
    try:
        while EXECUTANDO:
            try:
                if vencidos := crons_vencidos(int(time.time())):
                    _executar_cron(vencidos[0], token)
                    continue
                for update in buscar_updates(token, offset):
                    update_id, offset = update["update_id"], update["update_id"] + 1
                    if not update_processado(update_id) and update.get("message"):
                        _responder_mensagem(token, update["message"], update_id)
                    salvar_estado("telegram_offset", str(offset))
            except KeyboardInterrupt:
                break
            except Exception as erro:
                registrar(f"erro_polling={erro}")
                time.sleep(2)
    finally:
        salvar_estado("scheduler_ativo", "0"), _remover_pid(), registrar("bot_encerrado")
    return 0
def _nome_bot() -> str:
    """Retorna um nome legivel do bot configurado."""
    token = obter_configuracao().get("BRAZUCLAW_TOKEN")
    if not token:
        return "desconhecido"
    try:
        bot = validar_token(token)
        return bot.get("username") or bot.get("first_name") or "desconhecido"
    except Exception:
        return "desconhecido"
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
    if pid := _ler_pid():
        print(f"BrazuClaw ja esta em execucao no PID {pid}.")
        return 0
    print(f"servico Brazuclaw iniciado, bot nome {_nome_bot()}")
    _daemonizar(), _gravar_pid(os.getpid())
    return rodar_bot()
def parar_daemon() -> int:
    """Encerra o daemon em execucao."""
    if (pid := _ler_pid()) is None:
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
    return iniciar_daemon() if parar_daemon() == 0 else 1
def mostrar_logs(argumentos: list[str]) -> int:
    """Exibe logs recentes ou segue em tempo real."""
    seguir, numeros = any(arg in ("-f", "--follow", "tail") for arg in argumentos), [arg for arg in argumentos if arg.isdigit()]
    quantidade = int(numeros[-1]) if numeros else 50
    return _acompanhar_logs(quantidade) if seguir else print(*_ultimas_linhas(quantidade), sep="\n") or 0
def _parsear_flags(argumentos: list[str]) -> tuple[list[str], dict[str, str]]:
    """Separa posicionais e flags simples no formato --chave valor."""
    livres, flags, i = [], {}, 0
    while i < len(argumentos):
        atual = argumentos[i]
        if atual.startswith("--"):
            valor = "" if i + 1 >= len(argumentos) or argumentos[i + 1].startswith("--") else argumentos[i + 1]
            flags[atual[2:]] = valor
            i += 1 if not valor else 2
            continue
        livres.append(atual)
        i += 1
    return livres, flags
def _ajuda() -> int:
    """Mostra o uso principal da CLI."""
    print("Uso: brazuclaw [setup|start|stop|restart|logs|cron]")
    print("Cron: brazuclaw cron help")
    return 0
def _ajuda_cron() -> int:
    """Mostra o uso dos subcomandos de cron."""
    print("Uso: brazuclaw cron <subcomando>")
    print("  list")
    print('  add --nome NOME --schedule "*/5 * * * *" --prompt "instrucao" [--chat 123] [--callback nunca|erro|sempre] [--timeout 120]')
    print("  enable ID | disable ID | run ID | abort ID | rm ID")
    return 0
def _cron_list() -> int:
    """Lista os crons cadastrados."""
    for cron in listar_crons():
        proximo = "-" if not cron["proximo_em"] else datetime.fromtimestamp(cron["proximo_em"]).strftime("%Y-%m-%d %H:%M")
        print(f'#{cron["id"]} ativo={cron["ativo"]} status={cron["ultimo_status"] or "-"} pid={cron["pid_atual"]} next={proximo} nome={cron["nome"]} schedule="{cron["schedule"]}" callback={cron["callback_quando"]}:{cron["chat_callback_id"] or "-"}')
    return 0
def _cron_add(argumentos: list[str]) -> int:
    """Cria um cron novo pela CLI."""
    _, flags = _parsear_flags(argumentos)
    nome, schedule, prompt = flags.get("nome", "").strip(), flags.get("schedule", "").strip(), flags.get("prompt", "").strip()
    callback = flags.get("callback", "erro") or "erro"
    if not (nome and schedule and prompt):
        return _ajuda_cron()
    if callback not in ("nunca", "erro", "sempre"):
        raise SystemExit("callback invalido: use nunca, erro ou sempre.")
    cron_id = criar_cron(nome, prompt, schedule, int(flags.get("chat", "0") or 0), callback, int(flags.get("timeout", "120") or 120), _proximo_schedule(schedule))
    print(f"Cron criado com id {cron_id}.")
    return 0
def _cron_trocar(argumentos: list[str], ativo: int) -> int:
    """Ativa ou desativa um cron."""
    if not argumentos or not argumentos[0].isdigit():
        return _ajuda_cron()
    cron = obter_cron(int(argumentos[0]))
    if not cron:
        raise SystemExit("Cron nao encontrado.")
    atualizar_cron(cron["id"], ativo=ativo, proximo_em=_proximo_schedule(cron["schedule"]) if ativo else 0)
    print(f'Cron #{cron["id"]} {"ativado" if ativo else "desativado"}.')
    return 0
def _cron_run(argumentos: list[str]) -> int:
    """Executa um cron agora ou o marca para execucao no daemon."""
    if not argumentos or not argumentos[0].isdigit():
        return _ajuda_cron()
    cron = obter_cron(int(argumentos[0]))
    if not cron:
        raise SystemExit("Cron nao encontrado.")
    if _ler_pid() and cron["ativo"]:
        atualizar_cron(cron["id"], proximo_em=int(time.time()))
        print(f'Cron #{cron["id"]} marcado para execucao.')
        return 0
    garantir_banco()
    _executar_cron(cron, obter_configuracao().get("BRAZUCLAW_TOKEN", ""))
    print(f'Cron #{cron["id"]} executado em foreground.')
    return 0
def _cron_abort(argumentos: list[str]) -> int:
    """Sinaliza aborto para um cron em andamento."""
    if not argumentos or not argumentos[0].isdigit():
        return _ajuda_cron()
    cron = obter_cron(int(argumentos[0]))
    if not cron:
        raise SystemExit("Cron nao encontrado.")
    if not cron["pid_atual"]:
        print(f'Cron #{cron["id"]} nao esta em execucao.')
        return 0
    atualizar_cron(cron["id"], abortar=1)
    print(f'Aborto solicitado para cron #{cron["id"]}.')
    return 0
def cli() -> int:
    """Despacha os subcomandos disponiveis."""
    argumentos = sys.argv[1:]
    if not argumentos:
        return iniciar_daemon()
    if argumentos[0] in ("help", "--help", "-h"):
        return _ajuda()
    if argumentos[0] == "start":
        return iniciar_daemon()
    if argumentos[0] == "setup":
        return executar_wizard()
    if argumentos[0] == "stop":
        return parar_daemon()
    if argumentos[0] == "restart":
        return reiniciar_daemon()
    if argumentos[0] == "logs":
        return mostrar_logs(argumentos[1:])
    if argumentos[0] != "cron":
        return _ajuda()
    garantir_banco()
    if len(argumentos) == 1 or argumentos[1] in ("help", "--help", "-h"):
        return _ajuda_cron()
    if argumentos[1] == "list":
        return _cron_list()
    if argumentos[1] == "add":
        return _cron_add(argumentos[2:])
    if argumentos[1] == "enable":
        return _cron_trocar(argumentos[2:], 1)
    if argumentos[1] == "disable":
        return _cron_trocar(argumentos[2:], 0)
    if argumentos[1] == "run":
        return _cron_run(argumentos[2:])
    if argumentos[1] == "abort":
        return _cron_abort(argumentos[2:])
    if argumentos[1] == "rm" and len(argumentos) > 2 and argumentos[2].isdigit():
        remover_cron(int(argumentos[2]))
        print(f"Cron #{argumentos[2]} removido.")
        return 0
    return _ajuda_cron()
