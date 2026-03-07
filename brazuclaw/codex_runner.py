"""Execucao do Codex CLI."""
from __future__ import annotations
import os, re, shutil, subprocess, time

PADRAO_ANEXO = re.compile(r"\[anexo nome=\"([^\"]+)\" mimetype=\"([^\"]+)\"\]\s*(.*?)\s*\[/anexo\]", re.DOTALL)
PADRAO_CRON = re.compile(r"\[cron([^\]]*)\]\s*(.*?)\s*\[/cron\]", re.DOTALL)

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


def _instrucoes_base(permitir_cron: bool) -> list[str]:
    """Retorna as instrucoes fixas da chamada ao Codex."""
    partes = [
        "Responda em texto simples.",
        "Se precisar devolver imagem ou arquivo, use exatamente este formato:",
        "[anexo nome=\"arquivo.ext\" mimetype=\"tipo/subtipo\"]",
        "BASE64_AQUI",
        "[/anexo]",
        "Nunca use markdown para anexos.",
    ]
    if permitir_cron:
        partes.extend(
            [
                "Se o usuario pedir uma tarefa recorrente ou um agendamento continuo, crie um bloco de cron neste formato:",
                "[cron nome=\"nome-curto\" schedule=\"*/5 * * * *\" callback=\"sempre\"]",
                "instrucao que devera rodar em cada execucao",
                "[/cron]",
                "Use `callback=\"sempre\"` quando o usuario precisar receber o resultado no Telegram.",
                "Use `callback=\"erro\"` quando so precisar avisar em caso de falha.",
                "Use apenas expressoes cron de 5 campos.",
            ]
        )
    return partes


def montar_prompt(personalidade: str, contexto: str, mensagem: str, anexos: list[dict] | None = None, referencias_anexos: list[dict] | None = None, permitir_cron: bool = True) -> str:
    """Monta o prompt final enviado ao Codex CLI."""
    partes = _instrucoes_base(permitir_cron)
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


def montar_prompt_cron(personalidade: str, contexto: str, nome: str, instrucao: str) -> str:
    """Monta o prompt para uma execucao automatica de cron."""
    partes = _instrucoes_base(False)
    if personalidade.strip():
        partes.append("Arquivo ALMA.md carregado para esta chamada:\n" + personalidade.strip())
    if contexto.strip():
        partes.append("Contexto recente:\n" + contexto.strip())
    partes.append(f'Execucao automatica do cron "{nome.strip() or "cron"}".')
    partes.append("Execute a instrucao abaixo agora e devolva somente o resultado util da tarefa.")
    partes.append("Nao crie novos blocos [cron] nesta execucao e nao descreva metadados internos do scheduler.")
    partes.append("Instrucao agendada:\n" + (instrucao.strip() or "(sem instrucao)"))
    return "\n\n".join(partes)


def interpretar_resposta_codex(texto: str) -> dict[str, object]:
    """Separa texto e anexos retornados pelo Codex."""
    crons = []
    for atributos, conteudo in PADRAO_CRON.findall(texto):
        campos = dict(re.findall(r'(\w+)="([^"]*)"', atributos))
        if campos.get("nome") and campos.get("schedule") and conteudo.strip():
            crons.append(
                {
                    "nome": campos["nome"][:80],
                    "schedule": campos["schedule"].strip(),
                    "callback": (campos.get("callback") or "sempre").strip(),
                    "timeout": int(campos.get("timeout") or 120),
                    "prompt": conteudo.strip(),
                }
            )
    return {
        "texto": PADRAO_CRON.sub("", PADRAO_ANEXO.sub("", texto)).strip(),
        "anexos": [{"nome": n[:120], "mimetype": m[:120], "anexo_b64": "".join(c.split())} for n, m, c in PADRAO_ANEXO.findall(texto)],
        "crons": crons,
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
