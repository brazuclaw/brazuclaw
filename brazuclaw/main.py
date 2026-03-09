"""CLI, wizard, bot Telegram e cron do BrazuClaw."""
from __future__ import annotations
import asyncio, base64, json, mimetypes, os, platform, re, shutil, signal, sqlite3, subprocess, sys, time, threading
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path
import requests

BASE = Path.home() / ".brazuclaw"
ARQ = {"config": BASE / "config.env", "alma": BASE / "ALMA.md", "db": BASE / "db" / "mensagens.db", "log": BASE / "logs" / "brazuclaw.log", "pid": BASE / "brazuclaw.pid"}
LIMITE_TEXTO, LIMITE_ANEXO, CONTEXTO = 1000, 256 * 1024, 10
MODELO_BOT_PADRAO, MODELO_TASK_PADRAO = "", ""
MODELOS_GEMINI = ["gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
MODELO_GEMINI_PADRAO = MODELOS_GEMINI[0]
MARCAS_QUOTA_GEMINI = ("exhausted", "quota", "terminalquotaerror", "unexpected critical error")
_override_modelo: dict[str, str] = {}  # fallback de sessao; resetado a cada reinicio
PROVEDORES = {
    "codex":  {"binario": "codex",  "args_base": ["exec", "--yolo"], "flag_modelo": "-m",      "modelo_antes": False, "requer_node": True},
    "claude": {"binario": "claude", "args_base": ["-p"],             "flag_modelo": "--model",  "modelo_antes": True,  "requer_node": False},
    "gemini": {"binario": "gemini", "args_base": ["--yolo", "-p"],    "flag_modelo": "--model",  "modelo_antes": True,  "requer_node": False},
}
PROVEDOR_PADRAO = "codex"
PADRAO_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
PADRAO_ANEXO = re.compile(r'\[anexo([^\]]+)\]\s*(.*?)\s*\[/anexo\]', re.S)
PADRAO_CRON = re.compile(r"\[cron([^\]]*)\]\s*(.*?)\s*\[/cron\]", re.S)
PADRAO_TAREFA = re.compile(r"\[task\]\s*(.*?)\s*\[/task\]", re.S)
MAX_BG_TAREFAS = 2

def garantir_estrutura() -> None:
    """Cria a estrutura minima em ~/.brazuclaw e copia skills padrao se ausentes."""
    for pasta in (BASE, ARQ["db"].parent, ARQ["log"].parent): pasta.mkdir(parents=True, exist_ok=True)
    ARQ["config"].touch(exist_ok=True)
    pkg_skills = resources.files("brazuclaw").joinpath("skills")
    for arq in pkg_skills.iterdir():
        destino = BASE / "skills" / arq.name
        if arq.is_dir():
            destino.mkdir(parents=True, exist_ok=True)
            for sub in arq.iterdir():
                dest_sub = destino / sub.name
                if not dest_sub.exists(): dest_sub.write_text(sub.read_text(encoding="utf-8"), encoding="utf-8")
        elif not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True); destino.write_text(arq.read_text(encoding="utf-8"), encoding="utf-8")

def config(so_local: bool = False) -> dict[str, str]:
    """Le config.env e aplica prioridade do ambiente."""
    garantir_estrutura(); dados = {}
    for linha in ARQ["config"].read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1); dados[k.strip()] = v.strip()
    if not so_local:
        for k in ("BRAZUCLAW_TOKEN", "OPENAI_API_KEY", "BRAZUCLAW_PROVIDER_BOT", "BRAZUCLAW_PROVIDER_TASK", "BRAZUCLAW_MODEL_BOT", "BRAZUCLAW_MODEL_TASK"):
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
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {'chat=----' if chat_id is None else f'chat=...{str(chat_id)[-4:]}'} {status}", flush=True)

_tlocal = threading.local()

def banco(sql: str, args: tuple = (), um: bool = False, varios: bool = False):
    """Executa SQL simples no banco local com conexao reutilizada por thread."""
    con = getattr(_tlocal, "con", None)
    if con is None:
        garantir_estrutura()
        con = sqlite3.connect(ARQ["db"], isolation_level=None, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL"); con.row_factory = sqlite3.Row; _tlocal.con = con
    try:
        cur = con.execute(sql, args)
        return cur.fetchone() if um else cur.fetchall() if varios else cur.lastrowid
    except sqlite3.OperationalError:
        try: con.close()
        except Exception: pass
        _tlocal.con = None; return banco(sql, args, um, varios)

def preparar_banco() -> None:
    """Cria as tabelas do projeto."""
    banco("CREATE TABLE IF NOT EXISTS estado (chave TEXT PRIMARY KEY, valor TEXT NOT NULL DEFAULT '')")
    banco("CREATE TABLE IF NOT EXISTS mensagens (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, update_id INTEGER NOT NULL DEFAULT 0, ator TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'respondida', texto TEXT NOT NULL DEFAULT '', anexo_b64 TEXT NOT NULL DEFAULT '', mimetype TEXT NOT NULL DEFAULT '', nome_arquivo TEXT NOT NULL DEFAULT '', criado_em INTEGER NOT NULL)")
    banco("CREATE UNIQUE INDEX IF NOT EXISTS idx_update_ator ON mensagens(update_id, ator)")
    banco("CREATE INDEX IF NOT EXISTS idx_chat_msg ON mensagens(chat_id, id)")
    banco("CREATE TABLE IF NOT EXISTS crons (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, prompt TEXT NOT NULL, schedule TEXT NOT NULL, ativo INTEGER NOT NULL DEFAULT 1, chat_callback_id INTEGER NOT NULL DEFAULT 0, callback_quando TEXT NOT NULL DEFAULT 'erro', timeout_segundos INTEGER NOT NULL DEFAULT 120, proximo_em INTEGER NOT NULL DEFAULT 0, ultima_execucao_em INTEGER NOT NULL DEFAULT 0, ultimo_status TEXT NOT NULL DEFAULT '', pid_atual INTEGER NOT NULL DEFAULT 0, abortar INTEGER NOT NULL DEFAULT 0, criado_em INTEGER NOT NULL)")
    banco("CREATE TABLE IF NOT EXISTS tarefas (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, prompt TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pendente', resultado TEXT NOT NULL DEFAULT '', criado_em INTEGER NOT NULL, iniciado_em INTEGER NOT NULL DEFAULT 0, concluido_em INTEGER NOT NULL DEFAULT 0, pid_atual INTEGER NOT NULL DEFAULT 0, abortar INTEGER NOT NULL DEFAULT 0)")

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
    """Retorna o modelo configurado para bot ou task, respeitando override de sessao."""
    if tipo in _override_modelo: return _override_modelo[tipo]
    chave = "BRAZUCLAW_MODEL_BOT" if tipo == "bot" else "BRAZUCLAW_MODEL_TASK"
    m = config().get(chave) or (MODELO_BOT_PADRAO if tipo == "bot" else MODELO_TASK_PADRAO)
    if not m and provedor(tipo) == "gemini": return MODELO_GEMINI_PADRAO
    return m

def provedor(tipo: str = "bot") -> str:
    """Retorna o provedor configurado para bot ou task."""
    chave = "BRAZUCLAW_PROVIDER_BOT" if tipo == "bot" else "BRAZUCLAW_PROVIDER_TASK"
    nome = config().get(chave, PROVEDOR_PADRAO).strip().lower()
    return nome if nome in PROVEDORES else PROVEDOR_PADRAO

def carregar_alma() -> str:
    """Le ALMA.md do usuario e copia o padrao se faltar."""
    garantir_estrutura()
    if not ARQ["alma"].exists(): ARQ["alma"].write_text(resources.files("brazuclaw").joinpath("ALMA.md").read_text(encoding="utf-8"), encoding="utf-8")
    return ARQ["alma"].read_text(encoding="utf-8").strip()

def executar_ia(prompt: str, ao_aguardar=None, ao_iniciar=None, deve_abortar=None, modelo_nome: str = "", provedor_nome: str = "codex", timeout_segundos: int = 0) -> str:
    """Executa o provedor de IA com aborto cooperativo e timeout opcional para tasks."""
    prov = PROVEDORES.get(provedor_nome, PROVEDORES[PROVEDOR_PADRAO])
    binario = shutil.which(prov["binario"]) or ""
    if not binario: raise RuntimeError(f'{prov["binario"]} nao encontrado no PATH.')
    flag_mod = [prov["flag_modelo"], modelo_nome] if modelo_nome else []
    cmd = [binario, *(flag_mod if prov.get("modelo_antes") else []), *prov["args_base"], *([] if prov.get("modelo_antes") else flag_mod), prompt]
    if os.name == "posix" and shutil.which("nice"): cmd = ["nice", "-n", "10", *cmd]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy(), cwd=str(Path.home()), start_new_session=True)
    if ao_iniciar: ao_iniciar(p.pid)
    prox = time.monotonic(); prazo = (time.monotonic() + timeout_segundos) if timeout_segundos > 0 else None

    def matar_grupo():
        try: os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception: pass
        p.wait()

    try:
        while p.poll() is None:
            if prazo and time.monotonic() >= prazo: matar_grupo(); raise RuntimeError(f"Timeout de {timeout_segundos}s atingido.")
            if deve_abortar and deve_abortar(): matar_grupo(); raise RuntimeError("Execucao abortada.")
            if ao_aguardar and time.monotonic() >= prox: ao_aguardar(); prox = time.monotonic() + 4
            time.sleep(0.2)
        stdout, stderr = p.communicate()
        saida = (stdout or "").strip()
        erros = (stderr or "").strip()
        if provedor_nome == "gemini":
            _filtro = ("Loaded cached credentials.", "YOLO mode is enabled.")
            saida = "\n".join(l for l in saida.splitlines() if not any(f in l for f in _filtro)).strip()
            erros = "\n".join(l for l in erros.splitlines() if not any(f in l for f in _filtro)).strip()
            if any(mk in (saida + " " + erros).lower() for mk in MARCAS_QUOTA_GEMINI): raise RuntimeError("quota_gemini")
    finally:
        if p.poll() is None: matar_grupo()
    if p.returncode and not saida:
        for marca in ("usage limit", "limit", "upgrade", "credits"):
            if marca in erros.lower(): raise RuntimeError(erros.split("\n")[-1])
        raise RuntimeError(erros.split("\n")[-1] if erros else f'Falha ao executar {prov["binario"]}.')
    if not saida and erros: logar(f"stderr_sem_stdout={erros[:300]}")
    return saida

def fallback_gemini(m: str) -> str:
    """Retorna o proximo modelo flash como fallback quando a cota pro esta esgotada."""
    flash = [x for x in MODELOS_GEMINI if "flash" in x and x != m]
    return flash[0] if flash else "gemini-2.5-flash"

def provedor_ok(nome: str = "") -> bool:
    """Confirma se o provedor de IA esta disponivel e autenticado."""
    nome = nome or provedor("bot")
    prov = PROVEDORES.get(nome, PROVEDORES[PROVEDOR_PADRAO])
    if not shutil.which(prov["binario"]): return False
    if nome == "codex":
        arq_auth = Path.home() / ".codex" / "auth.json"
        if arq_auth.exists():
            try:
                dados = json.loads(arq_auth.read_text(encoding="utf-8"))
                if dados.get("tokens"): return True
            except Exception: pass
    try: return bool(executar_ia("Responda apenas: teste ok", 30, provedor_nome=nome))
    except Exception: return False

def montar_prompt(chat_id: int, texto: str, refs: list[dict] | None = None, nome_cron: str = "", chat_callback_id: int = 0) -> str:
    """Monta o prompt do provedor de IA com ALMA, memoria e anexos."""
    partes = [
        "Responda em texto simples.",
        "Se precisar devolver anexo, use [anexo nome=\"arquivo.ext\" mimetype=\"tipo/subtipo\"] BASE64 [/anexo].",
        "SOMENTE use [task]instrucao[/task] quando o usuario PEDIR EXPLICITAMENTE para rodar em segundo plano (ex: 'bg:', 'segundo plano', 'em background'). NUNCA decida sozinho enviar algo para background.",
        "SOMENTE para tarefas RECORRENTES/periodicas que o usuario pedir, use [cron nome=\"nome\" schedule=\"*/5 * * * *\" callback=\"sempre\"] instrucao [/cron]. Use apenas callback nunca, erro ou sempre e cron de 5 campos.",
        "NUNCA use [cron] para tarefas unicas. NUNCA use [task] a menos que o usuario peca explicitamente.",
    ]
    if alma := carregar_alma(): partes.append("Arquivo ALMA.md carregado:\n" + alma)
    if hist := contexto(chat_id): partes.append("Contexto recente:\n" + hist)
    partes.append((f'Execucao automatica do cron "{nome_cron}". Nao crie novos blocos [cron].\n\nInstrucao agendada:\n' if nome_cron else "Mensagem atual do usuario:\n") + (texto.strip() or "(sem texto)"))
    if refs: partes.append("Referencias de anexos da mensagem atual salvos no SQLite:\n" + "\n\n".join(f"- chat_id: {r['chat_id']}\n  update_id: {r['update_id']}\n  nome_arquivo: {r['nome']}\n  mimetype: {r['mimetype']}\n  banco_sqlite: {ARQ['db']}" for r in refs))
    cli_chat = chat_id if not nome_cron and chat_id > 0 else (chat_callback_id if nome_cron and chat_callback_id else 0)
    if cli_chat: partes.append(f"CLI do BrazuClaw disponivel para enviar ao Telegram (chat_id={cli_chat}):\n  brazuclaw tg send --chat {cli_chat} --file /caminho/arquivo\n  brazuclaw tg send --chat {cli_chat} --text \"mensagem\"\nPREFIRA este recurso para enviar imagens, audios, videos ou qualquer arquivo gerado. Reserve o bloco [anexo] apenas quando nao for possivel salvar o arquivo em disco.\nIMPORTANTE: ao usar brazuclaw tg send para enviar um arquivo, NAO inclua nenhum texto na resposta e NAO envie mensagem separada. Envie apenas o arquivo, em silencio.")
    return "\n\n".join(partes)

def interpretar(texto: str) -> dict[str, object]:
    """Separa texto, anexos, crons e tarefas da resposta do provedor de IA."""
    crons = []
    for attrs, corpo in PADRAO_CRON.findall(texto):
        d = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        if d.get("nome") and d.get("schedule") and corpo.strip(): crons.append({"nome": d["nome"][:80], "schedule": d["schedule"].strip(), "callback": (d.get("callback") or "sempre").strip(), "timeout": int(d.get("timeout") or 120), "prompt": corpo.strip()})
    anexos = []
    for attrs, corpo in PADRAO_ANEXO.findall(texto):
        d = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        if corpo.strip(): anexos.append({"nome": d.get("nome", "anexo.bin")[:120], "mimetype": d.get("mimetype", "application/octet-stream")[:120], "anexo_b64": "".join(corpo.split())})
    tasks = [corpo.strip() for corpo in PADRAO_TAREFA.findall(texto) if corpo.strip()]
    logar(f"interpretar anexos={len(anexos)} tasks={len(tasks)}")
    limpo = PADRAO_TAREFA.sub("", PADRAO_CRON.sub("", PADRAO_ANEXO.sub("", texto))).strip()
    return {"texto": limpo, "anexos": anexos, "crons": crons, "tasks": tasks}

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
        try:
            tg(token, "sendPhoto" if campo == "photo" else "sendDocument", {"chat_id": str(chat_id), **({"caption": "Anexo gerado pelo BrazuClaw."} if not texto and not i else {})}, 80, {campo: (a.get("nome", "anexo.bin"), (lambda b: base64.b64decode(b + "=" * (-len(b) % 4)))(str(a.get("anexo_b64", ""))), a.get("mimetype", "application/octet-stream"))}); primeiro = primeiro or a
        except Exception as erro_envio: logar(f"erro_envio_anexo={erro_envio}", chat_id); tg(token, "sendMessage", {"chat_id": chat_id, "text": f"Falha ao enviar anexo '{a.get('nome', 'anexo')}': {erro_envio}"})
    if not texto and not primeiro: logar("resposta_vazia", chat_id)
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
    """Resolve listar e remover cron sem chamar o provedor de IA."""
    texto = " ".join(texto.lower().split())
    if not texto or not any(p in texto for p in ("cron", "job", "agend")): return None
    crons = banco("SELECT * FROM crons WHERE ativo = 1 AND chat_callback_id = ? ORDER BY id", (chat_id,), varios=True)
    if any(p in texto for p in ("liste", "listar", "lista", "quais", "mostre")):
        if not crons: return {"texto": "No momento, nao ha nenhum agendamento ativo.", "anexos": []}
        itens = [f'{i}. nome: {c["nome"]}\nschedule: {c["schedule"]}\ncallback: {c["callback_quando"]}\ninstrucao: {c["prompt"]}' for i, c in enumerate(crons, 1)]
        return {"texto": "Jobs em agenda no momento:\n\n" + "\n\n".join(itens), "anexos": []}
    if any(p in texto for p in ("remova", "remove", "apague", "delete", "cancele", "cancel", "exclua")):
        if not crons: return {"texto": "No momento, nao ha nenhum agendamento ativo.", "anexos": []}
        por_nome = [c for c in crons if c["nome"].lower() in texto]
        if por_nome:
            for c in por_nome: banco("DELETE FROM crons WHERE id = ?", (c["id"],))
            nomes = ", ".join(f'"{c["nome"]}"' for c in por_nome)
            return {"texto": f"Cron {nomes} removido.", "anexos": []}
        if any(p in texto for p in ("todos", "tudo", "all")):
            for c in crons: banco("DELETE FROM crons WHERE id = ?", (c["id"],))
            return {"texto": "Todos os jobs agendados foram removidos.", "anexos": []}
        return None  # nome nao identificado; delega ao agente de IA
    return None

def extrair_anexo(token: str, msg: dict) -> dict | None:
    """Baixa foto ou documento e converte para base64."""
    item = (msg.get("photo") or [None])[-1] or msg.get("document")
    if not item or not item.get("file_id"): return None
    tipo, conteudo = baixar_anexo(token, item["file_id"])
    if len(conteudo) > LIMITE_ANEXO: raise ValueError(f"Anexo acima do limite de {LIMITE_ANEXO // 1024} KB.")
    return {"nome": ("imagem.jpg" if msg.get("photo") else item.get("file_name", "arquivo.bin"))[:120], "mimetype": (msg.get("document") or {}).get("mime_type", tipo), "anexo_b64": base64.b64encode(conteudo).decode("ascii")}

def instanciar(chat_id: int, texto: str, refs: list[dict] | None = None, ao_aguardar=None, ao_iniciar=None, deve_abortar=None, nome_cron: str = "", modelo_nome: str = "", provedor_nome: str = "codex", chat_callback_id: int = 0, timeout_segundos: int = 0) -> tuple[dict[str, object], str]:
    """Monta prompt, chama provedor de IA e interpreta retorno."""
    try:
        saida = executar_ia(montar_prompt(chat_id, texto, refs, nome_cron, chat_callback_id), ao_aguardar, ao_iniciar, deve_abortar, modelo_nome, provedor_nome, timeout_segundos)
        logar(f"raw_ia_ini={saida[:200].replace(chr(10),'|')}", chat_id if chat_id >= 0 else None)
        logar(f"raw_ia_fim={saida[-200:].replace(chr(10),'|')}", chat_id if chat_id >= 0 else None)
        return interpretar(saida), "ok"
    except Exception as erro:
        if str(erro) == "quota_gemini" and provedor_nome == "gemini":
            novo = fallback_gemini(modelo_nome)
            logar(f"quota_gemini_fallback={novo}", chat_id if chat_id >= 0 else None)
            _override_modelo["bot"] = novo; _override_modelo["task"] = novo
            try:
                saida = executar_ia(montar_prompt(chat_id, texto, refs, nome_cron, chat_callback_id), ao_aguardar, ao_iniciar, deve_abortar, novo, provedor_nome, timeout_segundos)
                logar(f"raw_ia_ini={saida[:200].replace(chr(10),'|')}", chat_id if chat_id >= 0 else None); logar(f"raw_ia_fim={saida[-200:].replace(chr(10),'|')}", chat_id if chat_id >= 0 else None)
                return interpretar(saida), "ok"
            except Exception as erro: pass
        abortado = "abortada" in str(erro).lower()
        logar(f"{'abortado' if abortado else 'erro_ia'}={erro}", chat_id if chat_id >= 0 else None)
        return {"texto": "Execucao abortada pelo usuario." if abortado else f"Falha ao consultar o provedor: {erro}", "anexos": []}, ("abortado" if abortado else "erro")

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
    prefixo_bg = next((p for p in ("bg:", "segundo plano:") if texto.lower().startswith(p)), None)
    if prefixo_bg and not anexo:
        prompt_bg = texto[len(prefixo_bg):].strip()
        if prompt_bg:
            tid = banco("INSERT INTO tarefas (chat_id, prompt, criado_em) VALUES (?, ?, ?)", (chat_id, prompt_bg, int(time.time())))
            tg(token, "sendMessage", {"chat_id": chat_id, "text": f"Tarefa #{int(tid)} enfileirada. Aviso quando concluir."})
            registrar(chat_id, "agente", f"Tarefa #{int(tid)} enfileirada.", update_id=update_id); return logar("tarefa_enfileirada", chat_id)
    if local := cron_local(chat_id, texto):
        txt, ax = enviar(token, chat_id, local); registrar(chat_id, "agente", txt, ax["anexo_b64"] if ax else "", ax["mimetype"] if ax else "", ax["nome"] if ax else "", update_id); return logar("resposta_local_cron", chat_id)
    refs = [] if not anexo else [{"chat_id": chat_id, "update_id": update_id, "nome": anexo["nome"], "mimetype": anexo["mimetype"]}]
    idade_msg = int(time.time()) - int(msg.get("date", time.time()))
    if idade_msg > 180: logar(f"msg_atrasada={idade_msg}s", chat_id); tg(token, "sendMessage", {"chat_id": chat_id, "text": f"Desculpe pela demora ({idade_msg // 60}min). Processando agora..."}, 10)
    inicio = time.monotonic(); logar(f"processando prov={provedor('bot')} model={modelo('bot') or 'padrao'} anexo={'sim' if anexo else 'nao'}", chat_id)
    resp, status = instanciar(chat_id, texto, refs, ao_aguardar=lambda: tg(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"}, 10), modelo_nome=modelo("bot"), provedor_nome=provedor("bot"))
    if status == "erro": logar(f"erro_resposta={resp.get('texto', '')[:200]}", chat_id)
    txt, ax = enviar(token, chat_id, aplicar_tarefas(chat_id, aplicar_crons(chat_id, resp)))
    tempo_real = int(time.monotonic()-inicio); logar(f"resposta_enviada tempo={tempo_real}s idade_msg={idade_msg}s", chat_id)
    registrar(chat_id, "agente", txt, ax["anexo_b64"] if ax else "", ax["mimetype"] if ax else "", ax["nome"] if ax else "", update_id)

def abortar_cron(cron_id: int) -> bool:
    """Retorna True quando o cron precisa abortar."""
    c = banco("SELECT ativo, abortar FROM crons WHERE id = ?", (cron_id,), um=True); return not c or bool(c["abortar"])

def abortar_tarefa(tid: int) -> bool:
    """Retorna True quando a tarefa em segundo plano precisa abortar."""
    r = banco("SELECT abortar FROM tarefas WHERE id = ?", (tid,), um=True); return not r or bool(r["abortar"])

def marcar_pid_cron(cron_id: int, pid: int) -> None:
    """Atualiza o PID atual do cron."""
    banco("UPDATE crons SET pid_atual = ? WHERE id = ?", (pid, cron_id))

def executar_cron(cron: sqlite3.Row, token: str) -> None:
    """Executa um cron vencido e opcionalmente notifica o Telegram."""
    cron_id, sessao = int(cron["id"]), -int(cron["id"])
    atual = banco("SELECT * FROM crons WHERE id = ?", (cron_id,), um=True)
    if not atual or not int(atual["ativo"]): return logar("cron_ignorado_removido", sessao)
    banco("UPDATE crons SET ultima_execucao_em = ?, ultimo_status = 'executando', abortar = 0, pid_atual = -1 WHERE id = ?", (int(time.time()), cron_id)); registrar(sessao, "humano", str(cron["prompt"]).strip(), status="recebida")
    resp, status = instanciar(sessao, str(cron["prompt"]).strip(), ao_iniciar=lambda pid: marcar_pid_cron(cron_id, pid), deve_abortar=lambda: abortar_cron(cron_id), nome_cron=str(cron["nome"]), modelo_nome=modelo("task"), provedor_nome=provedor("task"), chat_callback_id=int(cron["chat_callback_id"]), timeout_segundos=3600)
    cb = int(cron["chat_callback_id"]); resp = aplicar_tarefas(cb, resp) if cb else resp
    ax = resp.get("anexos", [None])[0] if isinstance(resp.get("anexos"), list) and resp.get("anexos") else None
    registrar(sessao, "agente", str(resp.get("texto", "")), ax["anexo_b64"] if ax else "", ax["mimetype"] if ax else "", ax["nome"] if ax else "")
    final = banco("SELECT * FROM crons WHERE id = ?", (cron_id,), um=True)
    if final:
        banco("UPDATE crons SET ultimo_status = ?, pid_atual = 0, abortar = 0, ultima_execucao_em = ?, proximo_em = ? WHERE id = ?", (status, int(time.time()), cron_proximo(str(final["schedule"])) if int(final["ativo"]) else 0, cron_id))
        if token and int(final["chat_callback_id"]) and (final["callback_quando"] == "sempre" or (final["callback_quando"] == "erro" and status != "ok")):
            enviar(token, int(final["chat_callback_id"]), {"texto": str(resp.get("texto", "")) if status == "ok" else f'Cron #{cron_id} "{final["nome"]}" {status}.\n\n{resp.get("texto", "")}'.strip(), "anexos": resp.get("anexos", []) if status == "ok" else []})
    logar(f"cron_{status}", sessao)

def executar_tarefa(tarefa: sqlite3.Row, token: str) -> None:
    """Executa uma tarefa de segundo plano e notifica o usuario ao concluir."""
    tid, chat_id = int(tarefa["id"]), int(tarefa["chat_id"])
    banco("UPDATE tarefas SET status = 'executando', iniciado_em = ? WHERE id = ?", (int(time.time()), tid))
    resp, status = instanciar(chat_id, str(tarefa["prompt"]).strip(), ao_iniciar=lambda pid: banco("UPDATE tarefas SET pid_atual = ? WHERE id = ?", (pid, tid)), deve_abortar=lambda: abortar_tarefa(tid), modelo_nome=modelo("task"), provedor_nome=provedor("task"))
    resp = aplicar_tarefas(chat_id, aplicar_crons(chat_id, resp))
    resultado = str(resp.get("texto", ""))
    banco("UPDATE tarefas SET status = ?, resultado = ?, concluido_em = ?, pid_atual = 0 WHERE id = ?", (status, resultado[:2000], int(time.time()), tid))
    if token and chat_id:
        aviso = f"Tarefa #{tid} " + ("concluida." if status == "ok" else "falhou.")
        resp["texto"] = "\n\n".join(p for p in (aviso, resultado) if p).strip()
        enviar(token, chat_id, resp)
    logar(f"tarefa_{status} id={tid}", chat_id)

def aplicar_tarefas(chat_id: int, resposta: dict[str, object]) -> dict[str, object]:
    """Enfileira tarefas de segundo plano geradas pelo agente."""
    avisos = []
    for prompt in resposta.get("tasks", []) if isinstance(resposta.get("tasks"), list) else []:
        tid = banco("INSERT INTO tarefas (chat_id, prompt, criado_em) VALUES (?, ?, ?)", (chat_id, str(prompt).strip(), int(time.time())))
        avisos.append(f"Tarefa #{int(tid)} enfileirada. Aviso quando concluir.")
    resposta["tasks"] = []; texto = str(resposta.get("texto", "")).strip()
    resposta["texto"] = "\n\n".join(p for p in (texto, "\n".join(avisos)) if p).strip(); return resposta

def daemonizar() -> None:
    """Desacopla o processo atual do terminal."""
    if os.name != "posix": raise SystemExit("Modo daemon exige POSIX.")
    sys.stdout.flush(); sys.stderr.flush()
    if os.fork() > 0: raise SystemExit(0)
    os.setsid()
    if os.fork() > 0: raise SystemExit(0)
    with open(os.devnull, "r", encoding="utf-8") as entrada, ARQ["log"].open("a", encoding="utf-8") as saida:
        os.dup2(entrada.fileno(), 0); os.dup2(saida.fileno(), 1); os.dup2(saida.fileno(), 2)

async def rodar_bot() -> int:
    """Executa long polling do Telegram e o scheduler local de forma assincrona."""
    preparar_banco(); token = config().get("BRAZUCLAW_TOKEN")
    if not token: logar("erro_token_ausente"); return 1
    try: validar_token(token)
    except Exception as erro: logar(f"erro_token_invalido={erro}"); return 1
    parar = asyncio.Event(); loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, parar.set)
        except NotImplementedError: signal.signal(sig, lambda *_: parar.set())
    banco("UPDATE crons SET pid_atual = 0, abortar = 0")
    for c in banco("SELECT id, schedule, ativo FROM crons", varios=True): banco("UPDATE crons SET proximo_em = ? WHERE id = ?", (cron_proximo(str(c["schedule"]), int(time.time()) - 60) if int(c["ativo"]) else 0, c["id"]))
    offset = int(estado("telegram_offset") or "0") or None; logar("bot_iniciado")
    banco("UPDATE tarefas SET status = 'pendente', pid_atual = 0 WHERE status = 'executando'")
    threads_ativas: set[asyncio.Task] = set()
    try:
        while not parar.is_set():
            try:
                if cron := banco("SELECT * FROM crons WHERE ativo = 1 AND pid_atual = 0 AND proximo_em > 0 AND proximo_em <= ? ORDER BY proximo_em, id LIMIT 1", (int(time.time()),), um=True):
                    t = asyncio.create_task(asyncio.to_thread(executar_cron, cron, token)); threads_ativas.add(t); t.add_done_callback(threads_ativas.discard)
                em_exec = banco("SELECT COUNT(*) FROM tarefas WHERE status = 'executando'", um=True)[0]
                if em_exec < MAX_BG_TAREFAS:
                    if pendente := banco("SELECT * FROM tarefas WHERE status = 'pendente' ORDER BY id LIMIT 1", um=True):
                        t = asyncio.create_task(asyncio.to_thread(executar_tarefa, pendente, token)); threads_ativas.add(t); t.add_done_callback(threads_ativas.discard)
                for update in await asyncio.to_thread(tg, token, "getUpdates", {"timeout": 30, "allowed_updates": ["message"], **({"offset": offset} if offset else {})}, 40):
                    offset = update["update_id"] + 1
                    if update.get("message") and not banco("SELECT 1 FROM mensagens WHERE update_id = ? AND ator = 'agente' AND status = 'respondida' LIMIT 1", (update["update_id"],), um=True):
                        await asyncio.to_thread(processar_mensagem, token, update)
                    estado("telegram_offset", str(offset))
            except Exception as erro: logar(f"erro_polling={erro}"); await asyncio.sleep(2)
    finally:
        if threads_ativas: await asyncio.gather(*threads_ativas, return_exceptions=True)
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

def escolher_modelo(prov: str, uso: str) -> str:
    """Apresenta selecao de modelo para o provedor escolhido."""
    if prov == "gemini":
        print(f"\nModelos disponiveis para {uso} (gemini):")
        for i, m in enumerate(MODELOS_GEMINI, 1): print(f"  {i}. {m}")
        resp = perguntar(f"Escolha o numero do modelo [1]: ") or "1"
        if resp.isdigit() and 1 <= int(resp) <= len(MODELOS_GEMINI): return MODELOS_GEMINI[int(resp) - 1]
        if resp in MODELOS_GEMINI: return resp
        print(f"Opcao invalida, usando padrao: {MODELO_GEMINI_PADRAO}"); return MODELO_GEMINI_PADRAO
    return perguntar(f"Modelo para {uso} (Enter para padrao): ")

def cli_setup() -> int:
    """Executa o wizard interativo de onboarding."""
    garantir_estrutura(); chave_so, nome_so = descobrir_so(); print(f"SO detectado: {nome_so}")
    if chave_so == "windows": print("Windows nativo nao e suportado. Use WSL: https://learn.microsoft.com/windows/wsl/install"); return 1
    if not confirmar("Continuar com este sistema?"): return 1
    print(f"Python detectado: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    if sys.version_info < (3, 11): print("Python 3.11 ou superior e obrigatorio."); return 1
    # Selecao de provedor
    nomes = ", ".join(PROVEDORES.keys())
    prov_bot = perguntar(f"Provedor para chat ({nomes}) [codex]: ").lower() or "codex"
    if prov_bot not in PROVEDORES: print(f"Provedor invalido: {prov_bot}"); return 1
    prov_task = perguntar(f"Provedor para task/cron ({nomes}) [{prov_bot}]: ").lower() or prov_bot
    if prov_task not in PROVEDORES: print(f"Provedor invalido: {prov_task}"); return 1
    mod_bot = escolher_modelo(prov_bot, "chat")
    mod_task = escolher_modelo(prov_task, "task")
    salvar_local("BRAZUCLAW_PROVIDER_BOT", prov_bot); salvar_local("BRAZUCLAW_PROVIDER_TASK", prov_task)
    salvar_local("BRAZUCLAW_MODEL_BOT", mod_bot); salvar_local("BRAZUCLAW_MODEL_TASK", mod_task)
    escolhidos = {prov_bot, prov_task}
    # Node.js e Codex (condicional)
    if "codex" in escolhidos:
        try: node = int(re.findall(r"\d+", subprocess.check_output(["node", "--version"], text=True, stderr=subprocess.DEVNULL))[0])
        except Exception: node = 0
        if node < 18:
            cmd = "sudo apt-get update && sudo apt-get install -y nodejs npm" if chave_so in ("linux", "wsl") else ("brew install node" if chave_so == "darwin" else "")
            print("Node.js 18+ nao encontrado."); print(f"Comando sugerido: {cmd}")
            if not cmd or not confirmar("Executar este comando agora?") or subprocess.run(["bash", "-lc", cmd]).returncode: return 1
        if not shutil.which("codex"):
            print("Codex CLI nao encontrado.")
            if not confirmar("Instalar com npm install -g @openai/codex?") or subprocess.run(["npm", "install", "-g", "@openai/codex"]).returncode or not shutil.which("codex"): return 1
        if not provedor_ok("codex"):
            print("Sessao do Codex nao esta ativa.")
            if subprocess.run([shutil.which("codex") or "codex", "login", "--device-auth"]).returncode or not provedor_ok("codex"): print("Falha ao autenticar o Codex CLI. Rode `codex login --device-auth` novamente."); return 1
    if "claude" in escolhidos:
        if not shutil.which("claude"):
            print("Claude CLI nao encontrado. Instale com: npm install -g @anthropic-ai/claude-code")
            if not confirmar("Instalar com npm install -g @anthropic-ai/claude-code?") or subprocess.run(["npm", "install", "-g", "@anthropic-ai/claude-code"]).returncode or not shutil.which("claude"): return 1
        if not provedor_ok("claude"): print("Falha ao validar o Claude CLI. Verifique a autenticacao."); return 1
    if "gemini" in escolhidos:
        if not shutil.which("gemini"):
            print("Gemini CLI nao encontrado. Instale seguindo: https://github.com/google-gemini/gemini-cli"); return 1
        if not provedor_ok("gemini"): print("Falha ao validar o Gemini CLI. Verifique a autenticacao."); return 1
    # Token Telegram
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
    # Teste final
    for p in escolhidos:
        if not provedor_ok(p): print(f"Falha no teste do provedor {p}."); return 1
    print(f"Resumo final:\n- SO: {nome_so}\n- Provedor bot: {prov_bot}" + (f" (modelo: {mod_bot})" if mod_bot else "") + f"\n- Provedor task: {prov_task}" + (f" (modelo: {mod_task})" if mod_task else "") + f"\n- Token Telegram: ok\n- Personalidade: {ARQ['alma']}\n- Dados locais: {BASE}\n- Iniciar bot: brazuclaw\n- Ver logs: brazuclaw logs -f")
    return 0

def setup_necessario() -> bool:
    """Verifica se o setup precisa rodar."""
    cfg = config(); token = cfg.get("BRAZUCLAW_TOKEN")
    if not token or not PADRAO_TOKEN.match(token): return True
    prov = PROVEDORES.get(cfg.get("BRAZUCLAW_PROVIDER_BOT", PROVEDOR_PADRAO), PROVEDORES[PROVEDOR_PADRAO])
    return not shutil.which(prov["binario"])

def matar_instancias_orfas() -> None:
    """Mata processos brazuclaw orfaos que nao estao no PID file."""
    pid_atual = ler_pid()
    try:
        saida = subprocess.check_output(["pgrep", "-f", "brazuclaw"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception: return
    for linha in saida.splitlines():
        try:
            pid = int(linha.strip())
            if pid != os.getpid() and pid != pid_atual:
                os.kill(pid, signal.SIGTERM)
        except (ValueError, ProcessLookupError): pass

def iniciar() -> int:
    """Inicia o daemon do bot."""
    if setup_necessario():
        print("Primeira execucao detectada. Iniciando o wizard de configuracao."); ret = cli_setup()
        if ret != 0: return ret
    matar_instancias_orfas()
    if pid := ler_pid(): print(f"BrazuClaw ja esta em execucao no PID {pid}."); return 0
    garantir_estrutura(); ARQ["pid"].write_text(f"{os.getpid()}\n", encoding="utf-8")
    print("servico BrazuClaw iniciado"); daemonizar(); ARQ["pid"].write_text(f"{os.getpid()}\n", encoding="utf-8"); return asyncio.run(rodar_bot())

def parar() -> int:
    """Encerra o daemon se estiver ativo."""
    if not (pid := ler_pid()): print("BrazuClaw nao esta em execucao."); return 0
    try: os.kill(pid, signal.SIGTERM)
    except ProcessLookupError: ARQ["pid"].unlink(missing_ok=True); return 0
    for _ in range(50):
        if not pid_ativo(pid): ARQ["pid"].unlink(missing_ok=True); print("BrazuClaw foi encerrado."); return 0
        time.sleep(0.2)
    try: os.kill(pid, signal.SIGKILL)
    except ProcessLookupError: ARQ["pid"].unlink(missing_ok=True); return 0
    for _ in range(10):
        if not pid_ativo(pid): ARQ["pid"].unlink(missing_ok=True); print("BrazuClaw foi encerrado (forcado)."); return 0
        time.sleep(0.2)
    print(f"Nao foi possivel confirmar o encerramento do PID {pid}."); return 1

def cli_tg(args: list[str]) -> int:
    """Envia mensagem ou arquivo ao Telegram via CLI."""
    livres, flags = parsear_flags(args)
    if not livres or livres[0] != "send": raise SystemExit("Uso: brazuclaw tg send --chat ID [--text TEXTO] [--file CAMINHO]")
    token = config().get("BRAZUCLAW_TOKEN")
    if not token: raise SystemExit("Token nao configurado. Execute brazuclaw setup.")
    chat_id = flags.get("chat")
    if not chat_id: raise SystemExit("Informe --chat CHAT_ID.")
    texto = flags.get("text", "")
    arquivo = flags.get("file", "")
    if not texto and not arquivo: raise SystemExit("Informe --text e/ou --file.")
    if arquivo:
        caminho = Path(arquivo).expanduser().resolve()
        if not caminho.exists(): raise SystemExit(f"Arquivo nao encontrado: {arquivo}")
        mime = mimetypes.guess_type(caminho.name)[0] or "application/octet-stream"
        campo = "photo" if mime.startswith("image/") else "audio" if mime.startswith("audio/") else "video" if mime.startswith("video/") else "document"
        dados: dict = {"chat_id": str(chat_id), **({"caption": texto[:1024]} if texto else {})}
        tg(token, {"photo": "sendPhoto", "audio": "sendAudio", "video": "sendVideo", "document": "sendDocument"}[campo], dados, 120, {campo: (caminho.name, caminho.read_bytes(), mime)})
    else:
        tg(token, "sendMessage", {"chat_id": chat_id, "text": texto[:4000]})
    print(f"Enviado para chat {chat_id}."); return 0

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

def cli_task(args: list[str]) -> int:
    """Gerencia a fila de tarefas em segundo plano."""
    if not args or args[0] == "list":
        for t in banco("SELECT * FROM tarefas ORDER BY id DESC", varios=True):
            ts = datetime.fromtimestamp(t["criado_em"]).strftime("%Y-%m-%d %H:%M")
            print(f'#{t["id"]} {t["status"]} chat=...{str(t["chat_id"])[-4:]} criado={ts} prompt={str(t["prompt"])[:60]}')
        return 0
    if len(args) < 2 or not args[1].isdigit(): raise SystemExit("Uso: brazuclaw task [list|abort ID|result ID|rm ID]")
    tarefa = banco("SELECT * FROM tarefas WHERE id = ?", (int(args[1]),), um=True)
    if not tarefa: raise SystemExit("Tarefa nao encontrada.")
    if args[0] == "abort": banco("UPDATE tarefas SET abortar = 1 WHERE id = ?", (tarefa["id"],)); print(f'Aborto solicitado para tarefa #{tarefa["id"]}.'); return 0
    if args[0] == "result": print(str(tarefa["resultado"]) or "(sem resultado ainda)"); return 0
    if args[0] == "rm": banco("DELETE FROM tarefas WHERE id = ?", (tarefa["id"],)); print(f"Tarefa #{tarefa['id']} removida."); return 0
    raise SystemExit("Uso: brazuclaw task [list|abort ID|result ID|rm ID]")

def cli() -> int:
    """Despacha a CLI principal."""
    preparar_banco(); args = sys.argv[1:]
    if not args or args[0] == "start": return iniciar()
    if args[0] == "setup": return cli_setup()
    if args[0] == "stop": return parar()
    if args[0] == "restart": return iniciar() if parar() == 0 else 1
    if args[0] == "logs": return logs(args[1:])
    if args[0] in ("help", "--help", "-h"): print("Uso: brazuclaw [setup|start|stop|restart|logs|cron|task|model|provider|tg]"); return 0
    if args[0] == "tg": return cli_tg(args[1:])
    if args[0] == "task": return cli_task(args[1:])
    if args[0] == "provider":
        if len(args) < 2 or args[1] not in ("bot", "task"): print(f"Uso: brazuclaw provider bot [provedor] | brazuclaw provider task [provedor]\nAtual: bot={provedor('bot')} task={provedor('task')}"); return 0
        tipo, chave = args[1], "BRAZUCLAW_PROVIDER_BOT" if args[1] == "bot" else "BRAZUCLAW_PROVIDER_TASK"
        if len(args) < 3: print(f"Provedor {tipo}: {provedor(tipo)}"); return 0
        if args[2] not in PROVEDORES: print(f"Provedor invalido. Opcoes: {', '.join(PROVEDORES.keys())}"); return 1
        salvar_local(chave, args[2]); print(f"Provedor {tipo} atualizado para: {args[2]}"); return 0
    if args[0] == "model":
        if len(args) < 2 or args[1] not in ("bot", "task"): print(f"Uso: brazuclaw model bot [modelo] | brazuclaw model task [modelo]\nAtual: bot={modelo('bot')} task={modelo('task')}"); return 0
        tipo, chave = args[1], "BRAZUCLAW_MODEL_BOT" if args[1] == "bot" else "BRAZUCLAW_MODEL_TASK"
        if len(args) < 3: print(f"Modelo {tipo}: {modelo(tipo)}"); return 0
        salvar_local(chave, args[2]); print(f"Modelo {tipo} atualizado para: {args[2]}"); return 0
    if args[0] != "cron": print("Uso: brazuclaw [setup|start|stop|restart|logs|cron|model|provider|tg]"); return 0
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
