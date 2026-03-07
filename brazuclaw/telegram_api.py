"""Chamadas HTTP para a API do Telegram."""
from __future__ import annotations
import base64, mimetypes, requests

def _url_api(token: str, metodo: str) -> str:
    """Monta a URL de um metodo da API do Telegram."""
    return f"https://api.telegram.org/bot{token}/{metodo}"
def chamar_api(token: str, metodo: str, dados: dict | None = None, timeout: int = 35) -> dict:
    """Executa uma chamada simples na API do Telegram."""
    resposta = requests.post(_url_api(token, metodo), json=dados or {}, timeout=timeout)
    resposta.raise_for_status()
    retorno = resposta.json()
    if not retorno.get("ok"):
        raise RuntimeError(retorno.get("description", "Erro desconhecido do Telegram"))
    return retorno["result"]
def validar_token(token: str) -> dict:
    """Valida o token chamando o metodo getMe."""
    return chamar_api(token, "getMe", {})
def buscar_updates(token: str, offset: int | None) -> list[dict]:
    """Busca updates via long polling."""
    dados = {"timeout": 30, "allowed_updates": ["message"]}
    if offset is not None:
        dados["offset"] = offset
    return chamar_api(token, "getUpdates", dados, timeout=40)
def baixar_anexo(token: str, file_id: str) -> tuple[str, bytes]:
    """Baixa um anexo do Telegram retornando mimetype e conteudo."""
    arquivo = chamar_api(token, "getFile", {"file_id": file_id})
    caminho = arquivo["file_path"]
    url = f"https://api.telegram.org/file/bot{token}/{caminho}"
    resposta = requests.get(url, timeout=40)
    resposta.raise_for_status()
    return mimetypes.guess_type(caminho.rsplit("/", 1)[-1])[0] or "application/octet-stream", resposta.content
def enviar_texto(token: str, chat_id: int, texto: str) -> dict:
    """Envia uma mensagem de texto simples."""
    return chamar_api(token, "sendMessage", {"chat_id": chat_id, "text": texto[:4000]})
def enviar_acao_digitando(token: str, chat_id: int) -> dict:
    """Informa ao Telegram que o bot esta digitando."""
    return chamar_api(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)
def enviar_anexo(token: str, chat_id: int, nome: str, anexo_b64: str, mimetype: str, legenda: str = "") -> dict:
    """Envia um anexo em base64 como foto ou documento."""
    campo = "photo" if mimetype.startswith("image/") else "document"
    resposta = requests.post(_url_api(token, "sendPhoto" if campo == "photo" else "sendDocument"), data={"chat_id": str(chat_id), **({"caption": legenda[:1024]} if legenda else {})}, files={campo: (nome, base64.b64decode(anexo_b64.encode("ascii")), mimetype or "application/octet-stream")}, timeout=80)
    resposta.raise_for_status()
    retorno = resposta.json()
    if not retorno.get("ok"):
        raise RuntimeError(retorno.get("description", "Erro desconhecido do Telegram"))
    return retorno["result"]
