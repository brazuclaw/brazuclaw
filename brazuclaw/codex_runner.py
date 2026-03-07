"""Execucao do Codex CLI."""
from __future__ import annotations
import os, re, shutil, subprocess, time

PADRAO_ANEXO = re.compile(r"\[anexo nome=\"([^\"]+)\" mimetype=\"([^\"]+)\"\]\s*(.*?)\s*\[/anexo\]", re.DOTALL)


def _caminho_codex() -> str:
    """Resolve o caminho absoluto do executavel do Codex CLI."""
    if caminho := shutil.which("codex"):
        return caminho
    raise RuntimeError("Codex CLI nao encontrado no PATH.")


def _montar_comando_codex(prompt: str) -> list[str]:
    """Monta o comando do Codex CLI."""
    comando = [_caminho_codex(), "exec", "--yolo", prompt]
    return ["nice", "-n", "10", *comando] if os.name == "posix" and shutil.which("nice") else comando


def _serializar_anexos(anexos: list[dict], referencia: bool = False) -> str:
    """Transforma anexos ou referencias em texto para o prompt."""
    blocos = []
    for anexo in anexos:
        if referencia:
            blocos.append(
                "\n".join(
                    [
                        f"- chat_id: {anexo.get('chat_id', '')}",
                        f"  update_id: {anexo.get('update_id', '')}",
                        f"  nome_arquivo: {anexo.get('nome', 'anexo.bin')}",
                        f"  mimetype: {anexo.get('mimetype', 'application/octet-stream')}",
                        f"  banco_sqlite: {anexo.get('banco_sqlite', '')}",
                    ]
                )
            )
        else:
            blocos.append(
                f"[anexo nome=\"{anexo.get('nome', 'anexo.bin')}\" mimetype=\"{anexo.get('mimetype', 'application/octet-stream')}\"]\n{anexo.get('anexo_b64', '')}\n[/anexo]"
            )
    return "\n\n".join(blocos)


def montar_prompt(personalidade: str, contexto: str, mensagem: str, anexos: list[dict] | None = None, referencias_anexos: list[dict] | None = None) -> str:
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
        partes.append("Referencias de anexos da mensagem atual salvos no SQLite:\n" + _serializar_anexos(referencias_anexos, True))
    return "\n\n".join(partes)


def interpretar_resposta_codex(texto: str) -> dict[str, object]:
    """Separa texto e anexos retornados pelo Codex."""
    return {
        "texto": PADRAO_ANEXO.sub("", texto).strip(),
        "anexos": [{"nome": n[:120], "mimetype": m[:120], "anexo_b64": "".join(c.split())} for n, m, c in PADRAO_ANEXO.findall(texto)],
    }


def codex_esta_autenticado(timeout: int = 30) -> bool:
    """Verifica se o Codex CLI responde com uma sessao valida."""
    try:
        processo = subprocess.run(_montar_comando_codex("Responda apenas: teste ok"), stdout=subprocess.PIPE, text=True, timeout=timeout, env=os.environ.copy(), stderr=subprocess.DEVNULL)
    except Exception:
        return False
    return processo.returncode == 0 and bool((processo.stdout or "").strip())


def executar_codex_monitorado(prompt: str, ao_aguardar=None, ao_iniciar=None, deve_abortar=None, timeout: int = 120, intervalo: int = 4) -> str:
    """Executa o Codex CLI chamando callbacks periodicos enquanto aguarda."""
    inicio = proxima_acao = time.monotonic()
    processo = subprocess.Popen(_montar_comando_codex(prompt), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=os.environ.copy())
    if ao_iniciar:
        ao_iniciar(processo.pid)
    try:
        while processo.poll() is None:
            agora = time.monotonic()
            if agora - inicio >= timeout:
                processo.kill(), processo.wait()
                raise subprocess.TimeoutExpired(processo.args, timeout)
            if deve_abortar and deve_abortar():
                processo.kill(), processo.wait()
                raise RuntimeError("Execucao abortada.")
            if ao_aguardar and agora >= proxima_acao:
                ao_aguardar()
                proxima_acao = agora + intervalo
            time.sleep(0.2)
        saida, _ = processo.communicate()
    finally:
        if processo.poll() is None:
            processo.kill(), processo.wait()
    texto = (saida or "").strip()
    if processo.returncode != 0 and not texto:
        raise RuntimeError("Falha ao executar o Codex CLI.")
    return texto or "Sem resposta do Codex CLI."
