"""Configuracao e arquivos locais do BrazuClaw."""
from __future__ import annotations
import os
from pathlib import Path

PASTA_BASE = Path.home() / ".brazuclaw"
ARQUIVO_CONFIG = PASTA_BASE / "config.env"
ARQUIVO_ALMA = PASTA_BASE / "ALMA.md"
PASTA_LOGS = PASTA_BASE / "logs"
PASTA_DB = PASTA_BASE / "db"
ARQUIVO_DB = PASTA_DB / "mensagens.db"
ARQUIVO_PID = PASTA_BASE / "brazuclaw.pid"
ARQUIVO_LOG = PASTA_LOGS / "brazuclaw.log"
def garantir_estrutura() -> None:
    """Cria a estrutura minima de diretorios do BrazuClaw."""
    PASTA_BASE.mkdir(parents=True, exist_ok=True)
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    PASTA_DB.mkdir(parents=True, exist_ok=True)
    if not ARQUIVO_CONFIG.exists():
        ARQUIVO_CONFIG.touch()
def obter_configuracao() -> dict[str, str]:
    """Le config.env e aplica prioridade para variaveis do ambiente."""
    garantir_estrutura()
    dados: dict[str, str] = {}
    for linha in ARQUIVO_CONFIG.read_text(encoding="utf-8").splitlines():
        texto = linha.strip()
        if not texto or texto.startswith("#") or "=" not in texto:
            continue
        chave, valor = texto.split("=", 1)
        dados[chave.strip()] = valor.strip()
    dados.update({k: v for k, v in os.environ.items() if k in ("BRAZUCLAW_TOKEN", "OPENAI_API_KEY")})
    return dados
def salvar_chave(chave: str, valor: str) -> None:
    """Salva ou atualiza uma chave no config.env."""
    dados = obter_configuracao()
    valor_limpo = valor.strip()
    if valor_limpo:
        dados[chave] = valor_limpo
    else:
        dados.pop(chave, None)
    linhas = [f"{nome}={dados[nome]}" for nome in sorted(dados)]
    conteudo = "\n".join(linhas)
    ARQUIVO_CONFIG.write_text((conteudo + "\n") if conteudo else "", encoding="utf-8")
