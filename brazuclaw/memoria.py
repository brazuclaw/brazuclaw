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
    return sqlite3.connect(ARQUIVO_DB)
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
