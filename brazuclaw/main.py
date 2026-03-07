"""CLI, wizard, bot Telegram e cron do BrazuClaw."""
from __future__ import annotations
import base64, mimetypes, os, platform, re, shutil, signal, sqlite3, subprocess, sys, time
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path
import requests

BASE = Path.home() / ".brazuclaw"
ARQ = {"config": BASE / "config.env", "alma": BASE / "ALMA.md", "db": BASE / "db" / "mensagens.db", "log": BASE / "logs" / "brazuclaw.log", "pid": BASE / "brazuclaw.pid"}
LIMITE_TEXTO, LIMITE_ANEXO, CONTEXTO, EXECUTANDO = 1000, 256 * 1024, 10, True
MODELO_BOT_PADRAO, MODELO_TASK_PADRAO = "codex-mini-latest", "codex-mini-latest"
PADRAO_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
PADRAO_ANEXO = re.compile(r'\[anexo nome="([^"]+)" mimetype="([^"]+)"\]\s*(.*?)\s*\[/anexo\]', re.S)
PADRAO_CRON = re.compile(r"\[cron([^\]]*)\]\s*(.*?)\s*\[/cron\]", re.S)

def garantir_estrutura() -> None:
    """Cria a estrutura minima em ~/.brazuclaw."""
    for pasta in (BASE, ARQ["db"].parent, ARQ["log"].parent): pasta.mkdir(parents=True, exist_ok=True)
    ARQ["config"].touch(exist_ok=True)

def config(so_local: bool = False) -> dict[str, str]:
    """Le config.env e aplica prioridade do ambiente."""
    garantir_estrutura(); dados = {}
    for linha in ARQ["config"].read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1); dados[k.strip()] = v.strip()
    if not so_local:
        for k in ("BRAZUCLAW_TOKEN", "OPENAI_API_KEY"):
            if os.getenv(k): dados[k] = os.environ[k]
    return dados

def salvar_local(chave: str, valor: str) -> None:
    """Grava so no arquivo local, sem copiar segredos do ambiente."""
    dados = config(True); valor = valor.strip()
    if valor: dados[chave] = valor
    else: dados.pop(chave, None)
    texto = "\n".join(f"{k}={v}" for k, v in sorted(dados.items()) if v)
    ARQ["config"].write_text((texto + "\n") if texto else "", encoding="utf-8")

def logar(status: str, chat_id: int | None = None) -> None:
    """Escreve log simples sem dados sensiveis."""
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {'chat=----' if chat_id is None else f'chat=...{str(chat_id)[-4:]}'} {status}")

def banco(sql: str, args: tuple = (), um: bool = False, varios: bool = False):
    """Executa SQL simples no banco local."""
    garantir_estrutura()
    with sqlite3.connect(ARQ["db"]) as con:
        con.row_factory = sqlite3.Row; cur = con.execute(sql, args)
        return cur.fetchone() if um else cur.fetchall() if varios else cur.lastrowid

def preparar_banco() -> None:
    """Cria as tabelas do projeto."""
    banco("CREATE TABLE IF NOT EXISTS estado (chave TEXT PRIMARY KEY, valor TEXT NOT NULL DEFAULT '')")
    banco("CREATE TABLE IF NOT EXISTS mensagens (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, update_id INTEGER NOT NULL DEFAULT 0, ator TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'respondida', texto TEXT NOT NULL DEFAULT '', anexo_b64 TEXT NOT NULL DEFAULT '', mimetype TEXT NOT NULL DEFAULT '', nome_arquivo TEXT NOT NULL DEFAULT '', criado_em INTEGER NOT NULL)")
    banco("CREATE UNIQUE INDEX IF NOT EXISTS idx_update_ator ON mensagens(update_id, ator)")
    banco("CREATE INDEX IF NOT EXISTS idx_chat_msg ON mensagens(chat_id, id)")
    banco("CREATE TABLE IF NOT EXISTS crons (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, prompt TEXT NOT NULL, schedule TEXT NOT NULL, ativo INTEGER NOT NULL DEFAULT 1, chat_callback_id INTEGER NOT NULL DEFAULT 0, callback_quando TEXT NOT NULL DEFAULT 'erro', timeout_segundos INTEGER NOT NULL DEFAULT 120, proximo_em INTEGER NOT NULL DEFAULT 0, ultima_execucao_em INTEGER NOT NULL DEFAULT 0, ultimo_status TEXT NOT NULL DEFAULT '', pid_atual INTEGER NOT NULL DEFAULT 0, abortar INTEGER NOT NULL DEFAULT 0, criado_em INTEGER NOT NULL)")

def estado(chave: str, valor: str | None = None) -> str:
    """Le ou grava estado simples."""
    if valor is not None: banco("INSERT OR REPLACE INTO estado (chave, valor) VALUES (?, ?)", (chave, valor)); return valor
    linha = banco("SELECT valor FROM estado WHERE chave = ?", (chave,), um=True); return linha[0] if linha else ""

def registrar(chat_id: int, ator: str, texto: str = "", anexo_b64: str = "", mimetype: str = "", nome: str = "", update_id: int = 0, status: str = "respondida") -> None:
    """Salva memoria curta persistida."""
    banco("INSERT OR REPLACE INTO mensagens (chat_id, update_id, ator, status, texto, anexo_b64, mimetype, nome_arquivo, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (chat_id, update_id, ator[:20], status[:20], texto[:500 if ator == "agente" else LIMITE_TEXTO], anexo_b64, mimetype[:120], nome[:255], int(time.time())))

def contexto(chat_id: int) -> str:
    """Monta o contexto das ultimas interacoes respondidas."""
    linhas = banco("SELECT ator, texto, anexo_b64, mimetype FROM mensagens WHERE chat_id = ? AND status = 'respondida' ORDER BY id DESC LIMIT ?", (chat_id, CONTEXTO), varios=True)
    partes = []
    for l in reversed(linhas):
        partes += ([f'{"Usuario" if l["ator"] == "humano" else "BrazuClaw"}: {l["texto"]}'] if l["texto"] else []) + ([f'{"Usuario" if l["ator"] == "humano" else "BrazuClaw"} enviou anexo ({l["mimetype"] or "application/octet-stream"}) salvo no banco local.'] if l["anexo_b64"] else [])
    return "\n".join(partes)

def tg(token: str, metodo: str, dados: dict | None = None, timeout: int = 35, arquivos: dict | None = None) -> dict:
    """Chama a API HTTP do Telegram."""
    r = requests.post(f"https://api.telegram.org/bot{token}/{metodo}", json=None if arquivos else (dados or {}), data=dados if arquivos else None, files=arquivos, timeout=timeout)
    r.raise_for_status(); j = r.json()
    if not j.get("ok"): raise RuntimeError(j.get("description", "Erro desconhecido do Telegram"))
    return j["result"]

def validar_token(token: str) -> dict:
    """Valida o token do bot no Telegram."""
    return tg(token, "getMe", {})

def baixar_anexo(token: str, file_id: str) -> tuple[str, bytes]:
    """Baixa foto ou documento do Telegram."""
    caminho = tg(token, "getFile", {"file_id": file_id})["file_path"]
    r = requests.get(f"https://api.telegram.org/file/bot{token}/{caminho}", timeout=40); r.raise_for_status()
    return mimetypes.guess_type(caminho.rsplit("/", 1)[-1])[0] or "application/octet-stream", r.content

def modelo(tipo: str = "bot") -> str:
    """Retorna o modelo configurado para bot ou task."""
    chave = "BRAZUCLAW_MODEL_BOT" if tipo == "bot" else "BRAZUCLAW_MODEL_TASK"
    return config().get(chave) or (MODELO_BOT_PADRAO if tipo == "bot" else MODELO_TASK_PADRAO)

def carregar_alma() -> str:
    """Le ALMA.md do usuario e copia o padrao se faltar."""
    garantir_estrutura()
    if not ARQ["alma"].exists(): ARQ["alma"].write_text(resources.files("brazuclaw").joinpath("ALMA.md").read_text(encoding="utf-8"), encoding="utf-8")
    return ARQ["alma"].read_text(encoding="utf-8").strip()

def codex(prompt: str, timeout: int = 120, ao_aguardar=None, ao_iniciar=None, deve_abortar=None, modelo_nome: str = "") -> str:
    """Executa `codex exec --yolo` com timeout e aborto cooperativo."""
    cmd = [shutil.which("codex") or "", "exec", "--yolo", *(["-m", modelo_nome] if modelo_nome else []), prompt]
    if not cmd[0]: raise RuntimeError("Codex CLI nao encontrado no PATH.")
    if os.name == "posix" and shutil.which("nice"): cmd = ["nice", "-n", "10", *cmd]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=os.environ.copy())
    if ao_iniciar: ao_iniciar(p.pid)
    inicio = prox = time.monotonic()
    try:
        while p.poll() is None:
            if time.monotonic() - inicio >= timeout: p.kill(); p.wait(); raise subprocess.TimeoutExpired(p.args, timeout)
            if deve_abortar and deve_abortar(): p.kill(); p.wait(); raise RuntimeError("Execucao abortada.")
            if ao_aguardar and time.monotonic() >= prox: ao_aguardar(); prox = time.monotonic() + 4
            time.sleep(0.2)
        saida = (p.communicate()[0] or "").strip()
    finally:
        if p.poll() is None: p.kill(); p.wait()
    if p.returncode and not saida: raise RuntimeError("Falha ao executar o Codex CLI.")
    return saida or "Sem resposta do Codex CLI."

def codex_ok() -> bool:
    """Confirma se o Codex CLI esta autenticado."""
    try: return bool(codex("Responda apenas: teste ok", 30))
    except Exception: return False

def montar_prompt(chat_id: int, texto: str, refs: list[dict] | None = None, nome_cron: str = "") -> str:
    """Monta o prompt do Codex com ALMA, memoria e anexos."""
    partes = [
        "Responda em texto simples.",
        "Se precisar devolver anexo, use [anexo nome=\"arquivo.ext\" mimetype=\"tipo/subtipo\"] BASE64 [/anexo].",
        "Se o usuario pedir tarefa recorrente, use [cron nome=\"nome\" schedule=\"*/5 * * * *\" callback=\"sempre\"] instrucao [/cron].",
        "Use apenas callback nunca, erro ou sempre e cron de 5 campos.",
    ]
    if alma := carregar_alma(): partes.append("Arquivo ALMA.md carregado:\n" + alma)
    if hist := contexto(chat_id): partes.append("Contexto recente:\n" + hist)
    partes.append((f'Execucao automatica do cron "{nome_cron}". Nao crie novos blocos [cron].\n\nInstrucao agendada:\n' if nome_cron else "Mensagem atual do usuario:\n") + (texto.strip() or "(sem texto)"))
    if refs: partes.append("Referencias de anexos da mensagem atual salvos no SQLite:\n" + "\n\n".join(f"- chat_id: {r['chat_id']}\n  update_id: {r['update_id']}\n  nome_arquivo: {r['nome']}\n  mimetype: {r['mimetype']}\n  banco_sqlite: {ARQ['db']}" for r in refs))
    return "\n\n".join(partes)

def interpretar(texto: str) -> dict[str, object]:
    """Separa texto, anexos e crons da resposta do Codex."""
    crons = []
    for attrs, corpo in PADRAO_CRON.findall(texto):
        d = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        if d.get("nome") and d.get("schedule") and corpo.strip(): crons.append({"nome": d["nome"][:80], "schedule": d["schedule"].strip(), "callback": (d.get("callback") or "sempre").strip(), "timeout": int(d.get("timeout") or 120), "prompt": corpo.strip()})
    return {"texto": PADRAO_CRON.sub("", PADRAO_ANEXO.sub("", texto)).strip(), "anexos": [{"nome": n[:120], "mimetype": m[:120], "anexo_b64": "".join(c.split())} for n, m, c in PADRAO_ANEXO.findall(texto)], "crons": crons}

def cron_campo(campo: str, minimo: int, maximo: int) -> tuple[set[int] | None, bool]:
    """Converte um campo cron em conjunto de inteiros."""
    if campo == "*": return None, True
    vals = set()
    for parte in campo.split(","):
        base, passo = (parte.split("/", 1) + ["1"])[:2]
        a, b = (minimo, maximo) if base == "*" else map(int, base.split("-", 1) if "-" in base else [base, base])
        if a < minimo or b > maximo or a > b or int(passo) < 1: raise ValueError("Campo cron invalido.")
        vals.update(range(a, b + 1, int(passo)))
    return vals, False

def cron_proximo(schedule: str, base: int | None = None) -> int:
    """Calcula a proxima data futura do cron."""
    m, h, dom, mes, dow = [cron_campo(c, *r) for c, r in zip(schedule.split(), ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6)))]
    t = datetime.fromtimestamp(base or time.time()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        dom_ok, dow_ok = m[0] is None or t.minute in m[0], h[0] is None or t.hour in h[0]
        dia_ok, semana_ok = dom[0] is None or t.day in dom[0], dow[0] is None or ((t.weekday() + 1) % 7) in dow[0]
        if dom_ok and dow_ok and (mes[0] is None or t.month in mes[0]) and ((dia_ok or semana_ok) if not dom[1] and not dow[1] else dia_ok and semana_ok): return int(t.timestamp())
        t += timedelta(minutes=1)
    raise ValueError("Nao foi possivel calcular o proximo horario.")

def pid_ativo(pid: int) -> bool:
    """Informa se um PID parece ativo."""
    try: os.kill(pid, 0); return True
    except OSError: return False

def ler_pid() -> int | None:
    """Le o PID atual do daemon se existir."""
    if not ARQ["pid"].exists(): return None
    try: pid = int(ARQ["pid"].read_text(encoding="utf-8").strip())
    except Exception: ARQ["pid"].unlink(missing_ok=True); return None
    if pid_ativo(pid): return pid
    ARQ["pid"].unlink(missing_ok=True); return None

def enviar(token: str, chat_id: int, resposta: dict[str, object]) -> tuple[str, dict | None]:
    """Envia texto e anexos de volta ao Telegram."""
    texto, primeiro = str(resposta.get("texto", "")).strip(), None
    if texto: tg(token, "sendMessage", {"chat_id": chat_id, "text": texto[:4000]})
    for i, a in enumerate(resposta.get("anexos", []) if isinstance(resposta.get("anexos"), list) else []):
        campo = "photo" if str(a.get("mimetype", "")).startswith("image/") else "document"
        tg(token, "sendPhoto" if campo == "photo" else "sendDocument", {"chat_id": str(chat_id), **({"caption": "Anexo gerado pelo BrazuClaw."} if not texto and not i else {})}, 80, {campo: (a.get("nome", "anexo.bin"), base64.b64decode(str(a.get("anexo_b64", "")).encode("ascii")), a.get("mimetype", "application/octet-stream"))}); primeiro = primeiro or a
    if not texto and not primeiro: texto = "Sem resposta do Codex CLI."; tg(token, "sendMessage", {"chat_id": chat_id, "text": texto})
    return texto, primeiro

def aplicar_crons(chat_id: int, resposta: dict[str, object]) -> dict[str, object]:
    """Cria crons gerados pelo agente e anexa confirmacoes ao texto."""
    avisos = []
    for c in resposta.get("crons", []) if isinstance(resposta.get("crons"), list) else []:
        try:
            callback = str(c.get("callback", "sempre")).strip(); callback = callback if callback in ("nunca", "erro", "sempre") else "sempre"
            cron_id = banco("INSERT INTO crons (nome, prompt, schedule, chat_callback_id, callback_quando, timeout_segundos, proximo_em, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(c.get("nome", "cron"))[:80], str(c.get("prompt", "")).strip(), str(c.get("schedule", "")).strip(), chat_id if callback != "nunca" else 0, callback, max(30, int(c.get("timeout", 120) or 120)), cron_proximo(str(c.get("schedule", "")).strip()), int(time.time())))
            avisos.append(f'Cron #{int(cron_id)} criado: "{c.get("nome", "cron")}".')
        except Exception as erro:
            avisos.append(f'Falha ao criar cron "{c.get("nome", "cron")}": {erro}')
    resposta["crons"] = []; texto = str(resposta.get("texto", "")).strip()
    resposta["texto"] = "\n\n".join(p for p in (texto, "\n".join(avisos)) if p).strip(); return resposta

def cron_local(chat_id: int, texto: str) -> dict[str, object] | None:
    """Resolve listar e remover cron sem chamar o Codex."""
    texto = " ".join(texto.lower().split())
    if not texto or not any(p in texto for p in ("cron", "job", "agend")): return None
    crons = banco("SELECT * FROM crons WHERE ativo = 1 AND chat_callback_id = ? ORDER BY id", (chat_id,), varios=True)
    if any(p in texto for p in ("liste", "listar", "lista", "quais", "mostre")):
        if not crons: return {"texto": "No momento, nao ha nenhum agendamento ativo.", "anexos": []}
        itens = [f'{i}. nome: {c["nome"]}\nschedule: {c["schedule"]}\ncallback: {c["callback_quando"]}\ninstrucao: {c["prompt"]}' for i, c in enumerate(crons, 1)]
        return {"texto": "Jobs em agenda no momento:\n\n" + "\n\n".join(itens), "anexos": []}
    if any(p in texto for p in ("remova", "remove", "apague", "delete", "cancele", "cancel", "exclua")):
        alvos = crons[:1] if any(p in texto for p in ("antig", "older", "mais velho")) else crons
        for c in alvos: banco("DELETE FROM crons WHERE id = ?", (c["id"],))
        return {"texto": "Cron mais antigo removido." if alvos and len(alvos) == 1 and len(crons) > 1 else ("Todos os jobs agendados foram removidos." if alvos else "No momento, nao ha nenhum agendamento ativo."), "anexos": []}
    return None

def extrair_anexo(token: str, msg: dict) -> dict | None:
    """Baixa foto ou documento e converte para base64."""
    item = (msg.get("photo") or [None])[-1] or msg.get("document")
    if not item or not item.get("file_id"): return None
    tipo, conteudo = baixar_anexo(token, item["file_id"])
    if len(conteudo) > LIMITE_ANEXO: raise ValueError(f"Anexo acima do limite de {LIMITE_ANEXO // 1024} KB.")
    return {"nome": ("imagem.jpg" if msg.get("photo") else item.get("file_name", "arquivo.bin"))[:120], "mimetype": (msg.get("document") or {}).get("mime_type", tipo), "anexo_b64": base64.b64encode(conteudo).decode("ascii")}

def instanciar(chat_id: int, texto: str, refs: list[dict] | None = None, timeout: int = 120, ao_aguardar=None, ao_iniciar=None, deve_abortar=None, nome_cron: str = "", modelo_nome: str = "") -> tuple[dict[str, object], str]:
    """Monta prompt, chama Codex e interpreta retorno."""
    try: return interpretar(codex(montar_prompt(chat_id, texto, refs, nome_cron), timeout, ao_aguardar, ao_iniciar, deve_abortar, modelo_nome)), "ok"
    except subprocess.TimeoutExpired: return {"texto": f"O Codex demorou mais de {timeout} segundos e a execucao foi abortada.", "anexos": []}, "timeout"
    except Exception as erro: return {"texto": "Execucao abortada pelo usuario." if "abortada" in str(erro).lower() else f"Falha ao consultar o Codex: {erro}", "anexos": []}, ("abortado" if "abortada" in str(erro).lower() else "erro")

def processar_mensagem(token: str, update: dict) -> None:
    """Processa uma unica mensagem do Telegram."""
    msg, update_id, chat_id = update["message"], update["update_id"], update["message"]["chat"]["id"]
    if msg["chat"].get("type") != "private": return logar("ignorado_chat_nao_privado", chat_id)
    texto = (msg.get("text") or msg.get("caption") or "").strip()
    if len(texto) > LIMITE_TEXTO: tg(token, "sendMessage", {"chat_id": chat_id, "text": "Mensagem longa demais. Limite de 1000 caracteres."}); return logar("ignorado_texto_longo", chat_id)
    try: anexo = extrair_anexo(token, msg)
    except Exception as erro: tg(token, "sendMessage", {"chat_id": chat_id, "text": str(erro) if isinstance(erro, ValueError) else f"Falha ao ler anexo: {erro}"}); return logar("erro_anexo", chat_id)
    if not texto and not anexo: tg(token, "sendMessage", {"chat_id": chat_id, "text": "Envie texto, imagem ou arquivo."}); return logar("ignorado_sem_conteudo", chat_id)
    registrar(chat_id, "humano", texto, anexo["anexo_b64"] if anexo else "", anexo["mimetype"] if anexo else "", anexo["nome"] if anexo else "", update_id, "recebida")
    if local := cron_local(chat_id, texto):
        txt, ax = enviar(token, chat_id, local); registrar(chat_id, "agente", txt, ax["anexo_b64"] if ax else "", ax["mimetype"] if ax else "", ax["nome"] if ax else "", update_id); return logar("resposta_local_cron", chat_id)
    refs = [] if not anexo else [{"chat_id": chat_id, "update_id": update_id, "nome": anexo["nome"], "mimetype": anexo["mimetype"]}]
    resp, _ = instanciar(chat_id, texto, refs, ao_aguardar=lambda: tg(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"}, 10), modelo_nome=modelo("bot"))
    txt, ax = enviar(token, chat_id, aplicar_crons(chat_id, resp))
    registrar(chat_id, "agente", txt, ax["anexo_b64"] if ax else "", ax["mimetype"] if ax else "", ax["nome"] if ax else "", update_id); logar("resposta_enviada", chat_id)

def abortar_cron(cron_id: int) -> bool:
    """Retorna True quando o cron precisa abortar."""
    c = banco("SELECT ativo, abortar FROM crons WHERE id = ?", (cron_id,), um=True); return not c or bool(c["abortar"])

def marcar_pid_cron(cron_id: int, pid: int) -> None:
    """Atualiza o PID atual do cron."""
    banco("UPDATE crons SET pid_atual = ? WHERE id = ?", (pid, cron_id))

def executar_cron(cron: sqlite3.Row, token: str) -> None:
    """Executa um cron vencido e opcionalmente notifica o Telegram."""
    cron_id, sessao = int(cron["id"]), -int(cron["id"])
    atual = banco("SELECT * FROM crons WHERE id = ?", (cron_id,), um=True)
    if not atual or not int(atual["ativo"]): return logar("cron_ignorado_removido", sessao)
    banco("UPDATE crons SET ultima_execucao_em = ?, ultimo_status = 'executando', abortar = 0, pid_atual = -1 WHERE id = ?", (int(time.time()), cron_id)); registrar(sessao, "humano", str(cron["prompt"]).strip(), status="recebida")
    resp, status = instanciar(sessao, str(cron["prompt"]).strip(), timeout=int(cron["timeout_segundos"]), ao_iniciar=lambda pid: marcar_pid_cron(cron_id, pid), deve_abortar=lambda: abortar_cron(cron_id), nome_cron=str(cron["nome"]), modelo_nome=modelo("task"))
    ax = resp.get("anexos", [None])[0] if isinstance(resp.get("anexos"), list) and resp.get("anexos") else None
    registrar(sessao, "agente", str(resp.get("texto", "")), ax["anexo_b64"] if ax else "", ax["mimetype"] if ax else "", ax["nome"] if ax else "")
    final = banco("SELECT * FROM crons WHERE id = ?", (cron_id,), um=True)
    if final:
        banco("UPDATE crons SET ultimo_status = ?, pid_atual = 0, abortar = 0, ultima_execucao_em = ?, proximo_em = ? WHERE id = ?", (status, int(time.time()), cron_proximo(str(final["schedule"])) if int(final["ativo"]) else 0, cron_id))
        if token and int(final["chat_callback_id"]) and (final["callback_quando"] == "sempre" or (final["callback_quando"] == "erro" and status != "ok")):
            enviar(token, int(final["chat_callback_id"]), {"texto": str(resp.get("texto", "")) if status == "ok" else f'Cron #{cron_id} "{final["nome"]}" {status}.\n\n{resp.get("texto", "")}'.strip(), "anexos": resp.get("anexos", []) if status == "ok" else []})
    logar(f"cron_{status}", sessao)

def encerrar(_sig: int, _frame: object) -> None:
    """Pede encerramento do loop principal."""
    global EXECUTANDO; EXECUTANDO = False

def daemonizar() -> None:
    """Desacopla o processo atual do terminal."""
    if os.name != "posix": raise SystemExit("Modo daemon exige POSIX.")
    if os.fork() > 0: raise SystemExit(0)
    os.setsid()
    if os.fork() > 0: raise SystemExit(0)
    with open(os.devnull, "r", encoding="utf-8") as entrada, ARQ["log"].open("a", encoding="utf-8") as saida:
        os.dup2(entrada.fileno(), 0); os.dup2(saida.fileno(), 1); os.dup2(saida.fileno(), 2)

def rodar_bot() -> int:
    """Executa long polling do Telegram e o scheduler local."""
    preparar_banco(); token = config().get("BRAZUCLAW_TOKEN")
    if not token:
        logar("erro_token_ausente"); return 1
    try: validar_token(token)
    except Exception as erro:
        logar(f"erro_token_invalido={erro}"); return 1
    signal.signal(signal.SIGINT, encerrar); signal.signal(signal.SIGTERM, encerrar)
    banco("UPDATE crons SET pid_atual = 0, abortar = 0")
    for c in banco("SELECT id, schedule, ativo FROM crons", varios=True): banco("UPDATE crons SET proximo_em = ? WHERE id = ?", (cron_proximo(str(c["schedule"]), int(time.time()) - 60) if int(c["ativo"]) else 0, c["id"]))
    offset = int(estado("telegram_offset") or "0") or None; logar("bot_iniciado")
    try:
        while EXECUTANDO:
            try:
                if cron := banco("SELECT * FROM crons WHERE ativo = 1 AND pid_atual = 0 AND proximo_em > 0 AND proximo_em <= ? ORDER BY proximo_em, id LIMIT 1", (int(time.time()),), um=True): executar_cron(cron, token); continue
                for update in tg(token, "getUpdates", {"timeout": 30, "allowed_updates": ["message"], **({"offset": offset} if offset else {})}, 40):
                    offset = update["update_id"] + 1
                    if update.get("message") and not banco("SELECT 1 FROM mensagens WHERE update_id = ? AND ator = 'agente' AND status = 'respondida' LIMIT 1", (update["update_id"],), um=True): processar_mensagem(token, update)
                    estado("telegram_offset", str(offset))
            except KeyboardInterrupt: break
            except Exception as erro: logar(f"erro_polling={erro}"); time.sleep(2)
    finally:
        ARQ["pid"].unlink(missing_ok=True); logar("bot_encerrado")
    return 0

def descobrir_so() -> tuple[str, str]:
    """Detecta Linux, macOS, WSL ou Windows nativo."""
    s, r = platform.system().lower(), platform.release().lower()
    return ("wsl", "WSL") if s == "linux" and "microsoft" in r else (s, {"linux": "Linux", "darwin": "macOS", "windows": "Windows"}.get(s, platform.system()))

def perguntar(texto: str) -> str:
    """Le uma resposta simples do terminal."""
    return input(texto).strip()

def confirmar(texto: str) -> bool:
    """Pede confirmacao simples ao usuario."""
    return perguntar(texto + " [s/N]: ").lower() == "s"

def cli_setup() -> int:
    """Executa o wizard interativo de onboarding."""
    garantir_estrutura(); chave_so, nome_so = descobrir_so(); print(f"SO detectado: {nome_so}")
    if chave_so == "windows": print("Windows nativo nao e suportado. Use WSL: https://learn.microsoft.com/windows/wsl/install"); return 1
    if not confirmar("Continuar com este sistema?"): return 1
    print(f"Python detectado: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    if sys.version_info < (3, 11): print("Python 3.11 ou superior e obrigatorio."); return 1
    try: node = int(re.findall(r"\d+", subprocess.check_output(["node", "--version"], text=True, stderr=subprocess.DEVNULL))[0])
    except Exception: node = 0
    if node < 18:
        cmd = "sudo apt-get update && sudo apt-get install -y nodejs npm" if chave_so in ("linux", "wsl") else ("brew install node" if chave_so == "darwin" else "")
        print("Node.js 18+ nao encontrado."); print(f"Comando sugerido: {cmd}")
        if not cmd or not confirmar("Executar este comando agora?") or subprocess.run(["bash", "-lc", cmd]).returncode: return 1
    if not shutil.which("codex"):
        print("Codex CLI nao encontrado.")
        if not confirmar("Instalar com npm install -g @openai/codex?") or subprocess.run(["npm", "install", "-g", "@openai/codex"]).returncode or not shutil.which("codex"): return 1
    if not codex_ok():
        print("Sessao do Codex nao esta ativa.")
        if subprocess.run([shutil.which("codex") or "codex", "login", "--device-auth"]).returncode or not codex_ok(): print("Falha ao autenticar o Codex CLI. Rode `codex login --device-auth` novamente."); return 1
    print("Crie um bot no Telegram:\n1. Abra o Telegram e procure @BotFather\n2. Envie /newbot\n3. Defina nome e username do bot\n4. Cole o token aqui")
    env_token = os.getenv("BRAZUCLAW_TOKEN", "").strip()
    if env_token:
        try: validar_token(env_token); print("BRAZUCLAW_TOKEN veio do ambiente e ja e valido.")
        except Exception as erro: print(f"BRAZUCLAW_TOKEN do ambiente e invalido: {erro}"); env_token = ""
    while True:
        token = env_token or perguntar("Cole o token do bot: "); env_token = ""
        try:
            if not PADRAO_TOKEN.match(token): raise RuntimeError("formato de token invalido")
            print(f'Token validado. Bot: @{validar_token(token).get("username", "sem_username")}'); salvar_local("BRAZUCLAW_TOKEN", token); break
        except Exception as erro: print(f"Token invalido: {erro}")
    carregar_alma(); print(f"ALMA pronta em: {ARQ['alma']}")
    if not codex_ok(): print("Falha no teste local do Codex CLI."); return 1
    print(f"Resumo final:\n- SO: {nome_so}\n- Node.js: ok\n- Codex CLI: ok\n- Token Telegram: ok\n- Personalidade: {ARQ['alma']}\n- Dados locais: {BASE}\n- Iniciar bot: brazuclaw\n- Ver logs: brazuclaw logs -f")
    return 0

def setup_necessario() -> bool:
    """Verifica se o setup precisa rodar."""
    token = config().get("BRAZUCLAW_TOKEN")
    return not token or not PADRAO_TOKEN.match(token)

def iniciar() -> int:
    """Inicia o daemon do bot."""
    if setup_necessario():
        print("Primeira execucao detectada. Iniciando o wizard de configuracao."); ret = cli_setup()
        if ret != 0: return ret
    if pid := ler_pid(): print(f"BrazuClaw ja esta em execucao no PID {pid}."); return 0
    print("servico BrazuClaw iniciado"); daemonizar(); ARQ["pid"].write_text(f"{os.getpid()}\n", encoding="utf-8"); return rodar_bot()

def parar() -> int:
    """Encerra o daemon se estiver ativo."""
    if not (pid := ler_pid()): print("BrazuClaw nao esta em execucao."); return 0
    try: os.kill(pid, signal.SIGTERM)
    except ProcessLookupError: ARQ["pid"].unlink(missing_ok=True); return 0
    for _ in range(30):
        if not pid_ativo(pid): ARQ["pid"].unlink(missing_ok=True); print("BrazuClaw foi encerrado."); return 0
        time.sleep(0.2)
    print(f"Nao foi possivel confirmar o encerramento do PID {pid}."); return 1

def logs(args: list[str]) -> int:
    """Mostra logs recentes ou segue o arquivo."""
    n, seguir, pos = int([a for a in args if a.isdigit()][-1]) if any(a.isdigit() for a in args) else 50, any(a in ("-f", "--follow", "tail") for a in args), 0
    while True:
        if not seguir: return print(*(ARQ["log"].read_text(encoding="utf-8", errors="replace").splitlines()[-n:] if ARQ["log"].exists() else []), sep="\n") or 0
        atual = ARQ["log"].stat().st_size if ARQ["log"].exists() else 0
        if atual > pos:
            with ARQ["log"].open("r", encoding="utf-8", errors="replace") as arq: arq.seek(pos); print(arq.read(), end="")
            pos = atual
        time.sleep(1)

def parsear_flags(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """Separa posicionais e flags simples."""
    livres, flags, i = [], {}, 0
    while i < len(args):
        if args[i].startswith("--"): flags[args[i][2:]] = "" if i + 1 >= len(args) or args[i + 1].startswith("--") else args[i + 1]; i += 1 if not flags[args[i][2:]] else 2
        else: livres.append(args[i]); i += 1
    return livres, flags

def cli() -> int:
    """Despacha a CLI principal."""
    preparar_banco(); args = sys.argv[1:]
    if not args or args[0] == "start": return iniciar()
    if args[0] == "setup": return cli_setup()
    if args[0] == "stop": return parar()
    if args[0] == "restart": return iniciar() if parar() == 0 else 1
    if args[0] == "logs": return logs(args[1:])
    if args[0] in ("help", "--help", "-h"): print("Uso: brazuclaw [setup|start|stop|restart|logs|cron|model]"); return 0
    if args[0] == "model":
        if len(args) < 2 or args[1] not in ("bot", "task"): print(f"Uso: brazuclaw model bot [modelo] | brazuclaw model task [modelo]\nAtual: bot={modelo('bot')} task={modelo('task')}"); return 0
        tipo, chave = args[1], "BRAZUCLAW_MODEL_BOT" if args[1] == "bot" else "BRAZUCLAW_MODEL_TASK"
        if len(args) < 3: print(f"Modelo {tipo}: {modelo(tipo)}"); return 0
        salvar_local(chave, args[2]); print(f"Modelo {tipo} atualizado para: {args[2]}"); return 0
    if args[0] != "cron": print("Uso: brazuclaw [setup|start|stop|restart|logs|cron|model]"); return 0
    if len(args) < 2 or args[1] == "list":
        for c in banco("SELECT * FROM crons ORDER BY id", varios=True):
            prox = "-" if not c["proximo_em"] else datetime.fromtimestamp(c["proximo_em"]).strftime("%Y-%m-%d %H:%M")
            print(f'#{c["id"]} ativo={c["ativo"]} status={c["ultimo_status"] or "-"} pid={c["pid_atual"]} next={prox} nome={c["nome"]} schedule="{c["schedule"]}" callback={c["callback_quando"]}:{c["chat_callback_id"] or "-"}')
        return 0
    livres, flags = parsear_flags(args[2:])
    if args[1] == "add":
        if not (flags.get("nome") and flags.get("schedule") and flags.get("prompt")): raise SystemExit("Use --nome, --schedule e --prompt.")
        cron_id = banco("INSERT INTO crons (nome, prompt, schedule, chat_callback_id, callback_quando, timeout_segundos, proximo_em, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (flags["nome"][:80], flags["prompt"].strip(), flags["schedule"].strip(), int(flags.get("chat", "0") or 0), (flags.get("callback") or "erro")[:10], max(30, int(flags.get("timeout", "120") or 120)), cron_proximo(flags["schedule"].strip()), int(time.time())))
        print(f"Cron criado com id {int(cron_id)}."); return 0
    if not livres or not livres[0].isdigit(): raise SystemExit("Informe o ID do cron.")
    cron = banco("SELECT * FROM crons WHERE id = ?", (int(livres[0]),), um=True)
    if not cron: raise SystemExit("Cron nao encontrado.")
    if args[1] in ("enable", "disable"): ativo = 1 if args[1] == "enable" else 0; banco("UPDATE crons SET ativo = ?, proximo_em = ? WHERE id = ?", (ativo, cron_proximo(str(cron["schedule"])) if ativo else 0, cron["id"])); print(f'Cron #{cron["id"]} {"ativado" if ativo else "desativado"}.'); return 0
    if args[1] == "abort": banco("UPDATE crons SET abortar = 1 WHERE id = ?", (cron["id"],)); print(f'Aborto solicitado para cron #{cron["id"]}.'); return 0
    if args[1] == "rm": banco("DELETE FROM crons WHERE id = ?", (cron["id"],)); print(f"Cron #{cron['id']} removido."); return 0
    if args[1] == "run": executar_cron(cron, config().get("BRAZUCLAW_TOKEN", "")); print(f'Cron #{cron["id"]} executado em foreground.'); return 0
    raise SystemExit("Subcomando cron invalido.")
