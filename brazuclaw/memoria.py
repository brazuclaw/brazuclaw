"""Memoria curta persistida em SQLite por chat."""
from __future__ import annotations
import sqlite3
import time
from brazuclaw.config import ARQUIVO_DB, garantir_estrutura
LIMITE_CONTEXTO = 10
LIMITE_TEXTO = 1000
LIMITE_RESPOSTA = 500
def _conexao() -> sqlite3.Connection:
    """Abre uma conexao simples com o banco local."""
    garantir_estrutura()
    conexao = sqlite3.connect(ARQUIVO_DB)
    conexao.row_factory = sqlite3.Row
    return conexao
def garantir_banco() -> None:
    """Cria o banco SQLite e as tabelas quando necessario."""
    with _conexao() as conexao:
        conexao.execute(
            "CREATE TABLE IF NOT EXISTS estado (chave TEXT PRIMARY KEY, valor TEXT NOT NULL DEFAULT '')"
        )
        conexao.execute(
            """
            CREATE TABLE IF NOT EXISTS mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                update_id INTEGER NOT NULL DEFAULT 0,
                ator TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'respondida',
                texto TEXT NOT NULL DEFAULT '',
                anexo_b64 TEXT NOT NULL DEFAULT '',
                mimetype TEXT NOT NULL DEFAULT '',
                nome_arquivo TEXT NOT NULL DEFAULT '',
                criado_em INTEGER NOT NULL
            )
            """
        )
        conexao.execute("CREATE INDEX IF NOT EXISTS idx_mensagens_chat_id_id ON mensagens(chat_id, id)")
        conexao.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mensagens_update_ator ON mensagens(update_id, ator)")
        conexao.execute(
            """
            CREATE TABLE IF NOT EXISTS crons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                prompt TEXT NOT NULL,
                schedule TEXT NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1,
                chat_callback_id INTEGER NOT NULL DEFAULT 0,
                callback_quando TEXT NOT NULL DEFAULT 'erro',
                timeout_segundos INTEGER NOT NULL DEFAULT 120,
                proximo_em INTEGER NOT NULL DEFAULT 0,
                ultima_execucao_em INTEGER NOT NULL DEFAULT 0,
                ultimo_status TEXT NOT NULL DEFAULT '',
                pid_atual INTEGER NOT NULL DEFAULT 0,
                abortar INTEGER NOT NULL DEFAULT 0,
                criado_em INTEGER NOT NULL
            )
            """
        )
def obter_estado(chave: str, padrao: str = "") -> str:
    """Le um valor simples da tabela de estado."""
    garantir_banco()
    with _conexao() as conexao:
        linha = conexao.execute("SELECT valor FROM estado WHERE chave = ?", (chave,)).fetchone()
    return linha[0] if linha else padrao
def salvar_estado(chave: str, valor: str) -> None:
    """Persiste um valor simples da tabela de estado."""
    garantir_banco()
    with _conexao() as conexao:
        conexao.execute("INSERT OR REPLACE INTO estado (chave, valor) VALUES (?, ?)", (chave, valor))
def update_processado(update_id: int) -> bool:
    """Informa se este update ja foi concluido no banco."""
    garantir_banco()
    with _conexao() as conexao:
        linha = conexao.execute(
            "SELECT 1 FROM mensagens WHERE update_id = ? AND ator = 'agente' AND status = 'respondida' LIMIT 1",
            (update_id,),
        ).fetchone()
    return bool(linha)
def registrar_interacao(
    chat_id: int,
    ator: str,
    texto: str = "",
    anexo_b64: str = "",
    mimetype: str = "",
    nome_arquivo: str = "",
    update_id: int = 0,
    status: str = "respondida",
) -> None:
    """Salva uma interacao no historico persistente."""
    garantir_banco()
    with _conexao() as conexao:
        conexao.execute(
            """
            INSERT OR REPLACE INTO mensagens
            (chat_id, update_id, ator, status, texto, anexo_b64, mimetype, nome_arquivo, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                update_id,
                ator[:20],
                status[:20],
                texto[: (LIMITE_RESPOSTA if ator == "agente" else LIMITE_TEXTO)],
                anexo_b64,
                mimetype[:120],
                nome_arquivo[:255],
                int(time.time()),
            ),
        )
def montar_contexto(chat_id: int) -> str:
    """Monta o contexto textual das ultimas interacoes do chat."""
    garantir_banco()
    with _conexao() as conexao:
        linhas = conexao.execute(
            """
            SELECT ator, texto, anexo_b64, mimetype
            FROM mensagens WHERE chat_id = ? AND status = 'respondida'
            ORDER BY id DESC LIMIT ?
            """,
            (chat_id, LIMITE_CONTEXTO),
        ).fetchall()
    linhas.reverse()
    contexto: list[str] = []
    for ator, texto, anexo_b64, mimetype in linhas:
        nome = "Usuario" if ator == "humano" else "BrazuClaw"
        if texto:
            contexto.append(f"{nome}: {texto}")
        if anexo_b64:
            contexto.append(f"{nome} enviou anexo ({mimetype or 'application/octet-stream'}) salvo no banco local.")
    return "\n".join(contexto)


def criar_cron(nome: str, prompt: str, schedule: str, chat_callback_id: int = 0, callback_quando: str = "erro", timeout_segundos: int = 120, proximo_em: int = 0) -> int:
    """Cria um cron e retorna seu identificador."""
    with _conexao() as conexao:
        cursor = conexao.execute(
            """
            INSERT INTO crons (nome, prompt, schedule, chat_callback_id, callback_quando, timeout_segundos, proximo_em, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nome[:80], prompt.strip(), schedule.strip(), chat_callback_id, callback_quando[:10], max(30, timeout_segundos), proximo_em, int(time.time())),
        )
        return int(cursor.lastrowid)


def listar_crons(apenas_ativos: bool = False) -> list[sqlite3.Row]:
    """Lista os crons cadastrados."""
    consulta = "SELECT * FROM crons"
    if apenas_ativos:
        consulta += " WHERE ativo = 1"
    with _conexao() as conexao:
        return list(conexao.execute(consulta + " ORDER BY id"))


def obter_cron(cron_id: int) -> sqlite3.Row | None:
    """Busca um cron pelo identificador."""
    with _conexao() as conexao:
        return conexao.execute("SELECT * FROM crons WHERE id = ?", (cron_id,)).fetchone()


def atualizar_cron(cron_id: int, **campos: int | str) -> None:
    """Atualiza campos permitidos de um cron."""
    if not campos:
        return
    colunas = ", ".join(f"{nome} = ?" for nome in campos)
    with _conexao() as conexao:
        conexao.execute(f"UPDATE crons SET {colunas} WHERE id = ?", (*campos.values(), cron_id))


def remover_cron(cron_id: int) -> None:
    """Remove um cron cadastrado."""
    with _conexao() as conexao:
        conexao.execute("DELETE FROM crons WHERE id = ?", (cron_id,))


def crons_vencidos(agora: int) -> list[sqlite3.Row]:
    """Lista os crons ativos vencidos e sem execucao em curso."""
    with _conexao() as conexao:
        return list(conexao.execute("SELECT * FROM crons WHERE ativo = 1 AND pid_atual = 0 AND proximo_em > 0 AND proximo_em <= ? ORDER BY proximo_em, id", (agora,)))


def limpar_execucoes_crons() -> None:
    """Limpa PIDs e abortos pendentes apos reinicio do processo."""
    with _conexao() as conexao:
        conexao.execute("UPDATE crons SET pid_atual = 0, abortar = 0 WHERE pid_atual != 0 OR abortar != 0")
