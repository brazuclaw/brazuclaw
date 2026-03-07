"""Execucao do Codex CLI."""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import time

PADRAO_ANEXO = re.compile(
    r"\[anexo nome=\"([^\"]+)\" mimetype=\"([^\"]+)\"\]\s*(.*?)\s*\[/anexo\]",
    re.DOTALL,
)
def _caminho_codex() -> str:
    """Resolve o caminho absoluto do executavel do Codex CLI."""
    caminho = shutil.which("codex")
    if not caminho:
        raise RuntimeError("Codex CLI nao encontrado no PATH.")
    return caminho
def _montar_comando_codex(prompt: str) -> list[str]:
    """Monta o comando do Codex CLI."""
    comando = [_caminho_codex(), "exec", "--yolo", prompt]
    if os.name == "posix" and shutil.which("nice"):
        comando = ["nice", "-n", "10", *comando]
    return comando
def _serializar_anexos(anexos: list[dict]) -> str:
    """Transforma anexos em texto para o prompt."""
    blocos: list[str] = []
    for anexo in anexos:
        nome = anexo.get("nome", "anexo.bin")
        mimetype = anexo.get("mimetype", "application/octet-stream")
        conteudo = anexo.get("anexo_b64", "")
        blocos.append(f"[anexo nome=\"{nome}\" mimetype=\"{mimetype}\"]\n{conteudo}\n[/anexo]")
    return "\n\n".join(blocos)
def _serializar_referencias_anexos(referencias: list[dict]) -> str:
    """Transforma referencias de anexos salvos em texto curto para o prompt."""
    linhas: list[str] = []
    for referencia in referencias:
        linhas.append(
            "\n".join(
                [
                    f"- chat_id: {referencia.get('chat_id', '')}",
                    f"  update_id: {referencia.get('update_id', '')}",
                    f"  nome_arquivo: {referencia.get('nome', 'anexo.bin')}",
                    f"  mimetype: {referencia.get('mimetype', 'application/octet-stream')}",
                    f"  banco_sqlite: {referencia.get('banco_sqlite', '')}",
                ]
            )
        )
    return "\n".join(linhas)
def montar_prompt(
    personalidade: str,
    contexto: str,
    mensagem: str,
    anexos: list[dict] | None = None,
    referencias_anexos: list[dict] | None = None,
) -> str:
    """Monta o prompt final enviado ao Codex CLI."""
    partes = [
        "Responda em texto simples.",
        "Se precisar devolver imagem ou arquivo, use exatamente este formato:",
        "[anexo nome=\"arquivo.ext\" mimetype=\"tipo/subtipo\"]",
        "BASE64_AQUI",
        "[/anexo]",
        "Nunca use markdown para anexos.",
    ]
    if personalidade.strip():
        partes.append("Arquivo ALMA.md carregado para esta chamada:\n" + personalidade.strip())
    if contexto.strip():
        partes.append("Contexto recente:\n" + contexto.strip())
    partes.append("Mensagem atual do usuario:\n" + (mensagem.strip() or "(sem texto)"))
    if anexos:
        partes.append("Anexos atuais do usuario:\n" + _serializar_anexos(anexos))
    if referencias_anexos:
        partes.append(
            "Referencias de anexos da mensagem atual salvos no SQLite:\n"
            + _serializar_referencias_anexos(referencias_anexos)
        )
    return "\n\n".join(partes)
def interpretar_resposta_codex(texto: str) -> dict[str, object]:
    """Separa texto e anexos retornados pelo Codex."""
    anexos: list[dict] = []
    for nome, mimetype, conteudo in PADRAO_ANEXO.findall(texto):
        anexos.append(
            {
                "nome": nome[:120],
                "mimetype": mimetype[:120],
                "anexo_b64": "".join(conteudo.split()),
            }
        )
    texto_limpo = PADRAO_ANEXO.sub("", texto).strip()
    return {"texto": texto_limpo, "anexos": anexos}
def codex_esta_autenticado(timeout: int = 30) -> bool:
    """Verifica se o Codex CLI responde com uma sessao valida."""
    try:
        processo = subprocess.run(
            _montar_comando_codex("Responda apenas: teste ok"),
            stdout=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return processo.returncode == 0 and bool((processo.stdout or "").strip())
def executar_codex_monitorado(prompt: str, ao_aguardar=None, timeout: int = 120, intervalo: int = 4) -> str:
    """Executa o Codex CLI chamando um callback periodico enquanto aguarda."""
    inicio = time.monotonic()
    processo = subprocess.Popen(
        _montar_comando_codex(prompt),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=os.environ.copy(),
    )
    proxima_acao = inicio
    try:
        while True:
            retorno = processo.poll()
            agora = time.monotonic()
            if retorno is not None:
                break
            if agora - inicio >= timeout:
                processo.kill()
                processo.wait()
                raise subprocess.TimeoutExpired(processo.args, timeout)
            if ao_aguardar and agora >= proxima_acao:
                ao_aguardar()
                proxima_acao = agora + intervalo
            time.sleep(0.2)
        saida, _ = processo.communicate()
    finally:
        if processo.poll() is None:
            processo.kill()
            processo.wait()
    texto = (saida or "").strip()
    if processo.returncode != 0 and not texto:
        raise RuntimeError("Falha ao executar o Codex CLI.")
    return texto or "Sem resposta do Codex CLI."
