from __future__ import annotations

import json
import os
import codecs
import html
import re
import unicodedata
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, quote, unquote, urlparse


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
HOST = "127.0.0.1"
PORT = 8765
TIMEOUT_SECONDS = 240
MAX_JOBS = 30
# Opção A1: a resposta de cada IA viaja inteira — para a tela e para o histórico.
# O número abaixo é só uma trava de segurança (≈10 páginas) para uma resposta
# fora do normal não engordar o arquivo nem travar o desenho. É o mesmo teto nos
# dois lugares, para a conversa reaberta mostrar exatamente o que apareceu na tela.
MAX_NOTE_CHARS = 20000

# Gemini and Ollama are reached through their HTTP APIs instead of spawning a
# terminal process. Streaming straight from the API removes the slow CLI startup
# (and lets Ollama answer without the model "thinking out loud" first).
GEMINI_API_BASE = os.environ.get(
    "MESA_GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta"
).rstrip("/")
GEMINI_MODEL = os.environ.get("MESA_GEMINI_MODEL", "gemini-3.8-flash")
OLLAMA_MODEL = os.environ.get("MESA_OLLAMA_MODEL", "qwen3.5:4b")
OLLAMA_KEEP_ALIVE = os.environ.get("MESA_OLLAMA_KEEP_ALIVE", "30m")


def ollama_base_url() -> str:
    """Resolve the local Ollama address, accepting host:port or a full URL."""
    raw = (
        os.environ.get("MESA_OLLAMA_BASE")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).strip().rstrip("/")
    if "://" not in raw:
        raw = "http://" + raw
    return raw


PROVIDERS = {
    "claude": {"label": "Claude Code", "command": "claude"},
    "codex": {"label": "Codex", "command": "codex"},
    "opencode": {"label": "OpenCode", "command": "opencode"},
    "gemini": {"label": "Gemini", "command": None},
    "openrouter": {"label": "OpenRouter · modelos grátis", "command": None},
    "cursor": {"label": "Cursor Agent", "command": "cursor-agent"},
    "qwen": {"label": "Qwen Code", "command": "qwen"},
    "ollama": {"label": "Ollama local", "command": None},
}

# Providers the Mesa talks to directly over HTTP — no terminal is involved.
DIRECT_API_PROVIDERS = ("gemini", "openrouter", "ollama")

# Temporarily pause slow providers in the Mesa without uninstalling their CLIs:
# add an entry here (e.g. "claude": "Pausado por enquanto") to hide it again.
# Empty means every provider found on this computer is offered.
PAUSED_PROVIDERS: dict[str, str] = {}

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()
ollama_status_cache: dict[str, Any] = {"checked": 0.0, "ready": False, "mode": "unknown", "reason": ""}
ollama_status_lock = threading.Lock()

# Histórico de conversas: um JSON nesta pasta, gravado de forma atômica.
HISTORY_FILE = ROOT / "historico.json"
MAX_HISTORY = 50
history_lock = threading.Lock()

# Último erro de cada provedor nesta sessão do servidor. Serve para a barra
# lateral não marcar de novo quem acabou de falhar (falta de login, de saldo…).
provider_last_error: dict[str, str] = {}
provider_error_lock = threading.Lock()


def short_failure_reason(detail: str) -> str:
    """Traduz o erro cru de um provedor numa etiqueta curta e legível.

    A ordem importa: um erro pode citar dinheiro e limite ao mesmo tempo (a cota
    do Gemini, por exemplo, fala em "billing"), e o limite é o motivo mais útil.
    """
    text = (detail or "").lower()
    if any(mark in text for mark in (
        "not logged in", "/login", "authentication required", "agent login",
        "unauthorized", "401", "invalid api key", "api key not valid", "no auth type",
    )):
        return "sem login"
    if any(mark in text for mark in (
        "usage limit", "quota", "429", "rate limit", "exceeded", "try again at",
        "limite de uso",
    )):
        return "limite atingido"
    if any(mark in text for mark in (
        "insufficient", "balance", "credit", "payment required", "402", "billing",
    )):
        return "sem saldo"
    if any(mark in text for mark in (
        "recusou", "connection", "timed out", "timeout", "refused", "offline",
        "unreachable", "demorou",
    )):
        return "sem conexão"
    return "falhou agora"


def format_seconds(value: float) -> str:
    """3.4 -> '3,4 s' — ponto decimal não é o costume em português."""
    return f"{value:.1f}".replace(".", ",") + " s"


def command_prefix(provider_id: str) -> list[str] | None:
    name = PROVIDERS[provider_id]["command"]
    if not name:
        return None
    executable = shutil.which(name + ".exe") or shutil.which(name)
    if executable:
        suffix = Path(executable).suffix.lower()
        if suffix not in (".ps1", ".cmd", ".bat"):
            return [executable]
    if os.name == "nt":
        script = executable if executable and Path(executable).suffix.lower() == ".ps1" else None
        if not script:
            # shutil.which on Windows follows PATHEXT, which usually excludes
            # npm's .ps1 shims even though PowerShell can run them directly.
            for folder in os.environ.get("PATH", "").split(os.pathsep):
                candidate = Path(folder.strip('"')) / f"{name}.ps1"
                if candidate.is_file():
                    script = str(candidate)
                    break
        # npm's Windows .ps1 shims use modern PowerShell behavior for argument
        # forwarding. Prefer pwsh so long prompts remain a single argument.
        powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if script and powershell:
            return [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
        script = executable if executable and Path(executable).suffix.lower() in (".cmd", ".bat") else None
        if script:
            command_shell = shutil.which("cmd.exe") or os.environ.get("COMSPEC", "cmd.exe")
            return [command_shell, "/d", "/s", "/c", script]
    return None


def provider_status() -> list[dict[str, Any]]:
    result = []
    for key, provider in PROVIDERS.items():
        if key in PAUSED_PROVIDERS:
            result.append({
                "id": key,
                "label": provider["label"],
                "installed": False,
                "command": provider["command"],
                "state": PAUSED_PROVIDERS[key],
                "reason": "Desativado temporariamente na Mesa. O programa continua instalado no computador.",
            })
            continue
        if key == "openrouter":
            configured = bool(os.environ.get("OPENROUTER_API_KEY") or read_dotenv_value("OPENROUTER_API_KEY"))
            result.append({
                "id": key,
                "label": provider["label"],
                "installed": configured,
                "command": "OpenRouter API",
                "state": "grátis · limite diário" if configured else "chave ausente",
                "reason": "Modelos gratuitos variam em qualidade e disponibilidade; limite publicado de 50 chamadas por dia."
                if configured else "Crie uma chave gratuita em openrouter.ai/keys e adicione OPENROUTER_API_KEY ao .env.",
            })
            continue
        if key == "gemini":
            configured = bool(gemini_api_key())
            result.append({
                "id": key,
                "label": provider["label"],
                "installed": configured,
                "command": f"Gemini API · {GEMINI_MODEL}",
                "state": "pronta · API" if configured else "chave ausente",
                "reason": (
                    f"Chamada direta à API do Gemini (modelo {GEMINI_MODEL}); não usa o terminal."
                    if configured else
                    "Crie uma chave gratuita em aistudio.google.com/apikey e adicione "
                    "GEMINI_API_KEY ao .env."
                ),
            })
            continue
        if key == "ollama":
            now = time.time()
            with ollama_status_lock:
                if now - ollama_status_cache["checked"] > 20:
                    # Três situações bem diferentes, para o usuário saber o que fazer:
                    # "offline" = aplicativo fechado, "missing" = falta o modelo, "ready".
                    ready, mode = False, "offline"
                    reason = (
                        f"O Ollama não respondeu em {ollama_base_url()}. Abra o aplicativo do "
                        "Ollama para ativar; a Mesa conversa com ele por HTTP, sem terminal."
                    )
                    try:
                        with urlopen(f"{ollama_base_url()}/api/tags", timeout=5) as response:
                            tags = {
                                str(model.get("name") or model.get("model") or "")
                                for model in json.loads(response.read().decode("utf-8")).get("models", [])
                            }
                        if OLLAMA_MODEL in tags:
                            ready, mode, reason = True, "ready", ""
                        else:
                            mode = "missing"
                            reason = (
                                f"O Ollama está aberto, mas falta o modelo {OLLAMA_MODEL}. "
                                f"Baixe com: ollama pull {OLLAMA_MODEL}"
                            )
                    except Exception:
                        pass
                    ollama_status_cache.update(
                        ready=ready, mode=mode, reason=reason, checked=time.time()
                    )
                installed = bool(ollama_status_cache["ready"])
                state = {
                    "ready": "modelo pronto",
                    "missing": "modelo ausente",
                    "offline": "Ollama fechado",
                }.get(str(ollama_status_cache["mode"]), "indisponível")
                reason = str(ollama_status_cache["reason"])
            result.append({
                "id": key,
                "label": provider["label"],
                "installed": installed,
                "command": f"Ollama API · {OLLAMA_MODEL}",
                "state": state,
                "reason": reason,
            })
            continue
        command = command_prefix(key)
        installed = bool(command)
        state = "instalado" if installed else "não detectada"
        reason = ""
        if key == "qwen" and command:
            settings_path = Path.home() / ".qwen" / "settings.json"
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                auth = settings.get("security", {}).get("auth", {})
                configured = bool(auth.get("selectedType") or settings.get("modelProviders"))
            except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
                configured = False
            if not configured:
                installed = False
                state = "configure /auth"
                reason = "Abra o Qwen Code, use /auth e escolha um provedor de modelo. Depois atualize a Mesa."
        result.append({
            "id": key,
            "label": provider["label"],
            "installed": installed,
            "command": provider["command"],
            "state": state,
            "reason": reason,
        })
    # Memória de falhas: expõe o último erro e, para um CLI que apenas "parece
    # instalado", troca o estado genérico pelo motivo real (sem login, sem saldo).
    for item in result:
        error = provider_last_error.get(item["id"], "")
        item["last_error"] = error
        if error and item["installed"] and item["state"] == "instalado":
            item["state"] = short_failure_reason(error)
            item["reason"] = error
    return result


def build_prompt(provider_id: str, phase: str, message: str,
                 history: list[dict[str, str]], contributions: dict[str, str]) -> str:
    transcript = []
    for item in history[-12:]:
        role = "Pessoa" if item.get("role") == "user" else "Resposta final anterior"
        content = str(item.get("content", ""))[:8000]
        transcript.append(f"{role}: {content}")
    history_text = "\n\n".join(transcript) or "(início da conversa)"

    base = (
        "Você participa de uma mesa local de IAs. Responda em português brasileiro, "
        "com clareza e sem inventar fatos. Você não está autorizado a executar comandos, "
        "alterar arquivos, acessar a internet nem revelar raciocínio interno detalhado. "
        "Entregue conclusões, evidências, incertezas e sugestões úteis, sem expor raciocínio privado. "
        "Fale diretamente com a pessoa e responda ao pedido concreto; não faça propaganda das suas capacidades "
        "nem use respostas genéricas como 'posso ajudar com muitas coisas'. Adapte a forma ao pedido: "
        "conversa simples recebe resposta natural e curta; explicações complexas usam títulos e seções; "
        "instruções usam passos numerados; comparações usam tabela quando isso facilitar; código vem em bloco "
        "formatado; pedidos criativos recebem um resultado pronto, original e bem acabado. Use Markdown legível, "
        "sem exagerar em títulos, listas ou emojis. "
        "Se perguntarem sobre a Mesa, explique este aplicativo e seus limites atuais; "
        "não responda como um assistente genérico. Nesta versão, a Mesa não edita arquivos do usuário.\n\n"
        f"Histórico da conversa:\n{history_text}\n\n"
        f"Nova mensagem da pessoa:\n{message}\n\n"
    )
    if phase == "first":
        return base + (
            "Dê sua resposta inicial independente, útil e específica. Se o pedido for para criar algo, entregue "
            "uma primeira versão completa em vez de apenas sugerir que pode fazê-lo. Aponte incertezas relevantes."
        )

    others = "\n\n".join(
        f"Contribuição de {name}:\n{text}" for name, text in contributions.items()
        if name != provider_id
    ) or "Nenhuma outra contribuição disponível."
    return base + (
        "Etapa 2 de 3: leia as contribuições dos outros participantes, corrija erros, "
        "aponte concordâncias e divergências relevantes e atualize sua resposta. "
        "Não repita raciocínio interno.\n\n"
        f"Contribuições dos outros:\n{others}"
    )


def build_command(provider: str, prompt: str, workdir: str) -> list[str]:
    if provider == "claude":
        return ["claude", "-p", "--permission-mode", "plan", "--output-format", "text", prompt]
    if provider == "codex":
        return ["codex", "exec", "--ephemeral", "--sandbox", "read-only",
                "--skip-git-repo-check", "--cd", workdir, prompt]
    if provider == "opencode":
        return ["opencode", "run", "--dir", workdir, prompt]
    if provider == "cursor":
        return ["cursor-agent", "-p", "--output-format", "text", prompt]
    if provider == "qwen":
        # Qwen Code now recommends the positional prompt over deprecated -p/--prompt.
        return ["qwen", prompt, "--output-format", "text"]
    # Gemini and Ollama are handled by their HTTP clients, never here.
    raise ValueError("Provedor desconhecido")


def read_dotenv_value(name: str) -> str | None:
    env_file = Path(os.environ.get("MESA_ENV_FILE", Path.home() / "MEUS PROJETOS" / ".env"))
    try:
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '\"'):
                    value = value[1:-1]
                return value or None
    except (OSError, UnicodeError):
        pass
    return None


def gemini_api_key() -> str | None:
    """Read the Google AI Studio key from the environment or the shared .env."""
    return os.environ.get("GEMINI_API_KEY") or read_dotenv_value("GEMINI_API_KEY")


def run_gemini(prompt: str, on_output: Callable[[str], None] | None = None) -> str:
    """Call the Gemini API straight over HTTP, streaming server-sent events."""
    key = gemini_api_key()
    if not key:
        raise RuntimeError("Adicione GEMINI_API_KEY ao arquivo .env para usar o Gemini")

    url = f"{GEMINI_API_BASE}/models/{quote(GEMINI_MODEL, safe='')}:streamGenerateContent?alt=sse"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192},
    }).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    chunks: list[str] = []
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("error"):
                    raise RuntimeError(event["error"].get("message", "Gemini interrompeu a resposta"))
                for candidate in event.get("candidates") or []:
                    for part in (candidate.get("content") or {}).get("parts") or []:
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            chunks.append(text)
                            if on_output:
                                on_output(text)
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = (body.get("error") or {}).get("message", "")
        except Exception:
            detail = ""
        raise RuntimeError(
            f"Gemini retornou HTTP {exc.code}: {detail or 'verifique a chave ou o limite de uso'}"
        ) from exc
    except URLError as exc:
        raise RuntimeError("Não foi possível conectar à API do Gemini; confira sua internet") from exc

    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError("O Gemini respondeu sem texto; tente novamente")
    return text[-18000:]


def run_ollama(prompt: str, on_output: Callable[[str], None] | None = None) -> str:
    """Call the local Ollama server over HTTP and stream the answer as it arrives."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "think": False,            # skip the model's "thinking out loud" first
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"temperature": 0.7},
    }).encode("utf-8")
    request = Request(
        f"{ollama_base_url()}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chunks: list[str] = []
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("error"):
                    raise RuntimeError(str(event["error"]))
                text = (event.get("message") or {}).get("content")
                if isinstance(text, str) and text:
                    chunks.append(text)
                    if on_output:
                        on_output(text)
                if event.get("done"):
                    break
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:
            detail = ""
        raise RuntimeError(
            f"Ollama retornou HTTP {exc.code}: {detail or f'baixe o modelo {OLLAMA_MODEL}'}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"O Ollama não respondeu em {ollama_base_url()}. Abra o aplicativo do Ollama "
            "e tente de novo; a Mesa fala com ele por HTTP, sem terminal."
        ) from exc

    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError("O Ollama respondeu sem texto; tente novamente")
    return text[-18000:]


def warm_ollama() -> None:
    """Preload the local model so the first answer is not a cold start."""
    try:
        payload = json.dumps({"model": OLLAMA_MODEL, "keep_alive": OLLAMA_KEEP_ALIVE}).encode("utf-8")
        request = Request(
            f"{ollama_base_url()}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=120):
            pass
    except Exception:
        pass


def run_openrouter(prompt: str, on_output: Callable[[str], None] | None = None) -> str:
    key = os.environ.get("OPENROUTER_API_KEY") or read_dotenv_value("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Adicione OPENROUTER_API_KEY ao arquivo .env para usar esta opção")

    payload = json.dumps({
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }).encode("utf-8")
    request = Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": f"http://{HOST}:{PORT}/",
            "X-Title": "Mesa de IAs",
        },
        method="POST",
    )
    chunks: list[str] = []
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("error"):
                    raise RuntimeError(event["error"].get("message", "OpenRouter interrompeu a resposta"))
                choices = event.get("choices") or []
                delta = choices[0].get("delta", {}).get("content") if choices else None
                if isinstance(delta, list):
                    delta = "".join(part.get("text", "") for part in delta if isinstance(part, dict))
                if isinstance(delta, str) and delta:
                    chunks.append(delta)
                    if on_output:
                        on_output(delta)
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = body.get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise RuntimeError(f"OpenRouter retornou HTTP {exc.code}: {detail or 'verifique a chave ou o limite diário'}") from exc
    except URLError as exc:
        raise RuntimeError("Não foi possível conectar ao OpenRouter; confira sua internet") from exc

    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError("OpenRouter respondeu sem texto; tente novamente")
    return text[-18000:]


def run_provider(provider: str, prompt: str, on_output: Callable[[str], None] | None = None) -> str:
    if provider == "openrouter":
        return run_openrouter(prompt, on_output)
    if provider == "gemini":
        return run_gemini(prompt, on_output)
    if provider == "ollama":
        return run_ollama(prompt, on_output)
    prefix = command_prefix(provider)
    if not prefix:
        raise RuntimeError(f"{PROVIDERS[provider]['label']} não está instalado no PATH")
    with tempfile.TemporaryDirectory(prefix="mesa-ias-") as workdir:
        arguments = build_command(provider, prompt, workdir)[1:]
        if len(prefix) >= 4 and Path(prefix[-1]).suffix.lower() in (".cmd", ".bat"):
            command = prefix[:-1] + [subprocess.list2cmdline([prefix[-1], *arguments])]
        else:
            command = prefix + arguments
        try:
            process = subprocess.Popen(
                command,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                shell=False,
            )
        except OSError as exc:
            raise RuntimeError(f"Não consegui iniciar {PROVIDERS[provider]['label']}: {exc}") from exc
        output_parts: list[str] = []
        error_parts: list[str] = []

        def read_stream(stream: Any, destination: list[str], publish_output: bool = False) -> None:
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while True:
                chunk = stream.read(2048)
                if not chunk:
                    break
                decoded = decoder.decode(chunk)
                if decoded:
                    destination.append(decoded)
                    if publish_output and on_output:
                        on_output(decoded)
            tail = decoder.decode(b"", final=True)
            if tail:
                destination.append(tail)
                if publish_output and on_output:
                    on_output(tail)

        stdout_reader = threading.Thread(target=read_stream, args=(process.stdout, output_parts, True), daemon=True)
        stderr_reader = threading.Thread(target=read_stream, args=(process.stderr, error_parts), daemon=True)
        stdout_reader.start()
        stderr_reader.start()
        try:
            returncode = process.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            stdout_reader.join(timeout=2)
            stderr_reader.join(timeout=2)
            raise RuntimeError("A IA demorou mais de 4 minutos e foi interrompida") from exc
        stdout_reader.join()
        stderr_reader.join()
    output = "".join(output_parts).strip()
    if returncode != 0:
        detail = ("".join(error_parts) or output or "sem detalhes").strip()
        lower_detail = detail.lower()
        if provider == "qwen" and "no auth type is selected" in lower_detail:
            raise RuntimeError(
                "Qwen Code está instalado, mas falta conectar um provedor. "
                "Abra o Qwen Code, digite /auth e escolha um provedor."
            )
        raise RuntimeError(detail[-600:])
    if not output:
        raise RuntimeError("A IA terminou sem retornar texto")
    return output[-18000:]


def publish(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(changes)
            jobs[job_id]["updated"] = time.time()


def update_provider_progress(job_id: str, provider: str, status: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is not None:
            progress = job.setdefault("provider_progress", {})
            progress[provider] = status
            job["updated"] = time.time()


def update_provider_output(job_id: str, provider: str, chunk: str) -> None:
    if not chunk:
        return
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return
        previews = job.setdefault("provider_output", {})
        combined = previews.get(provider, "") + chunk
        combined = re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", combined)
        combined = "".join(char for char in combined if char in "\n\t" or ord(char) >= 32)
        previews[provider] = combined[-2200:]
        job["updated"] = time.time()


def update_provider_seconds(job_id: str, provider: str, seconds: float) -> None:
    """Guarda quanto tempo cada IA levou — é o cronômetro do Painel de Confiança."""
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return
        job.setdefault("provider_seconds", {})[provider] = round(float(seconds), 1)
        job["updated"] = time.time()


def run_parallel(
    providers: list[str],
    prompts: dict[str, str],
    on_progress: Callable[[str, str], None] | None = None,
    on_output: Callable[[str, str], None] | None = None,
    on_seconds: Callable[[str, float], None] | None = None,
    progress_label: str = "Respondendo",
) -> tuple[dict[str, str], dict[str, str], dict[str, float]]:
    """Pergunta a todas as IAs ao mesmo tempo: respostas, erros e tempos."""
    results: dict[str, str] = {}
    errors: dict[str, str] = {}
    seconds: dict[str, float] = {}
    result_lock = threading.Lock()
    workers = []

    def clock(provider: str, started: float) -> float:
        spent = round(time.time() - started, 1)
        with result_lock:
            seconds[provider] = spent
        if on_seconds:
            on_seconds(provider, spent)
        return spent

    def worker(provider: str) -> None:
        if on_progress:
            on_progress(provider, progress_label)
        started = time.time()
        try:
            answer = run_provider(
                provider,
                prompts[provider],
                on_output=lambda chunk: on_output(provider, chunk) if on_output else None,
            )
            with result_lock:
                results[provider] = answer
            with provider_error_lock:
                provider_last_error.pop(provider, None)
            spent = clock(provider, started)
            if on_progress:
                on_progress(provider, f"Concluída em {format_seconds(spent)}")
        except Exception as exc:
            with result_lock:
                errors[provider] = str(exc)
            with provider_error_lock:
                provider_last_error[provider] = str(exc)
            spent = clock(provider, started)
            if on_progress:
                on_progress(provider, f"Não respondeu em {format_seconds(spent)}")

    for provider in providers:
        thread = threading.Thread(target=worker, args=(provider,), daemon=True)
        thread.start()
        workers.append(thread)
    for thread in workers:
        thread.join(TIMEOUT_SECONDS + 10)
    return results, errors, seconds


def orchestrate(job_id: str, message: str, history: list[dict[str, str]],
                selected: list[str], synthesizer: str, mode: str) -> None:
    try:
        publish(
            job_id,
            phase="Respostas independentes",
            activity="Acompanhe as etapas e os trechos das respostas enquanto as IAs trabalham.",
            provider_progress={p: "Na fila" for p in selected},
            provider_output={},
            started=time.time(),
            status="running",
        )
        if "ollama" in selected:
            # Keep the local model warm so it answers without a cold-start pause.
            threading.Thread(target=warm_ollama, daemon=True).start()
        initial_prompts = {
            provider: build_prompt(provider, "first", message, history, {})
            for provider in selected
        }
        first, first_errors, first_seconds = run_parallel(
            selected,
            initial_prompts,
            on_progress=lambda provider, state: update_provider_progress(job_id, provider, state),
            on_output=lambda provider, chunk: update_provider_output(job_id, provider, chunk),
            on_seconds=lambda provider, seconds: update_provider_seconds(job_id, provider, seconds),
        )
        if len(first) < 2:
            raise RuntimeError(
                "Menos de duas IAs responderam. "
                + "; ".join(f"{PROVIDERS[p]['label']}: {e}" for p, e in first_errors.items())
            )

        reviews: dict[str, str] = {}
        review_errors: dict[str, str] = {}
        if mode == "complete":
            publish(
                job_id,
                phase="Revisão cruzada",
                activity="As IAs estão lendo e revisando as respostas disponíveis.",
                provider_progress={p: "Aguardando revisão" for p in first},
                provider_output={},
                status="running",
            )
            review_prompts = {
                provider: build_prompt(provider, "review", message, history, first)
                for provider in first
            }
            reviews, review_errors, _ = run_parallel(
                list(first),
                review_prompts,
                on_progress=lambda provider, state: update_provider_progress(job_id, provider, state),
                on_output=lambda provider, chunk: update_provider_output(job_id, provider, chunk),
                progress_label="Revisando",
            )
            if not reviews:
                reviews = first
                review_errors = {**review_errors, "aviso": "A revisão falhou; usei as respostas iniciais."}

        # Se a IA escolhida para a resposta final não respondeu nesta rodada, não
        # gaste uma chamada fadada a falhar (um CLI leva ~20s só para recusar):
        # entregue a síntese a uma IA que comprovadamente respondeu.
        if synthesizer not in first:
            substitute = next((p for p in selected if p in first), None)
            if substitute:
                review_errors["síntese"] = (
                    f"{PROVIDERS[synthesizer]['label']} não respondeu nesta rodada; "
                    f"a resposta final ficou com {PROVIDERS[substitute]['label']}."
                )
                update_provider_progress(job_id, synthesizer, "Não respondeu; fora da síntese")
                synthesizer = substitute

        synthesis_source = reviews or first
        publish(
            job_id,
            phase="Preparando resposta única",
            activity=(
                f"{PROVIDERS[synthesizer]['label']} está reunindo os pontos úteis em uma resposta só."
                if mode == "complete" else
                f"Modo rápido: {PROVIDERS[synthesizer]['label']} está resumindo as respostas iniciais, sem a rodada de revisão."
            ),
            provider_progress={p: "Contribuição pronta" for p in synthesis_source},
            provider_output={},
            status="running",
        )
        update_provider_progress(job_id, synthesizer, "Preparando resposta final")
        synth_prompt = (
            "Você é a pessoa responsável por entregar a resposta final única desta mesa. "
            "Considere a pergunta original e as respostas disponíveis. Resolva divergências, "
            "corrija erros identificáveis e entregue uma resposta final clara, específica e bem acabada em português "
            "brasileiro. Responda ao que a pessoa realmente pediu, sem texto genérico sobre capacidades e sem repetir "
            "as contribuições uma por uma. Organize com Markdown no formato que melhor serve ao pedido: conversa curta "
            "sem seções forçadas; conteúdo complexo com títulos claros; passos em ordem; comparações em tabela se útil; "
            "pedido criativo como um artefato pronto. Não mencione raciocínio privado nem invente consenso. Se houver "
            "incerteza real, diga isso brevemente. Se perguntarem sobre a Mesa, explique que ela reúne respostas das IAs "
            "selecionadas e que esta versão conversa, mas ainda não edita arquivos do usuário.\n\n"
            f"Pergunta: {message}\n\n"
            + "\n\n".join(
                f"Resposta revisada de {PROVIDERS[p]['label']}:\n{text}"
                for p, text in synthesis_source.items()
            )
        )
        synthesis_started = time.time()
        try:
            final = run_provider(
                synthesizer,
                synth_prompt,
                on_output=lambda chunk: update_provider_output(job_id, synthesizer, chunk),
            )
            final_provider = synthesizer
            update_provider_progress(job_id, synthesizer, "Resposta final pronta")
        except Exception as exc:
            fallback = next((p for p in reviews if p != synthesizer), None)
            if not fallback:
                fallback = next(iter(reviews or first))
            update_provider_progress(job_id, synthesizer, "Falhou; usando alternativa")
            update_provider_progress(job_id, fallback, "Preparando resposta final")
            final = run_provider(
                fallback,
                synth_prompt,
                on_output=lambda chunk: update_provider_output(job_id, fallback, chunk),
            )
            final_provider = fallback
            update_provider_progress(job_id, fallback, "Resposta final pronta")
            review_errors["síntese"] = f"{PROVIDERS[synthesizer]['label']} falhou: {exc}"
        synth_seconds = round(time.time() - synthesis_started, 1)

        publish(
            job_id,
            status="done",
            phase="Concluído",
            final=final,
            final_provider=final_provider,
            provider_seconds=first_seconds,
            provider_failures={p: short_failure_reason(e) for p, e in first_errors.items()},
            synth_seconds=synth_seconds,
            participants=[PROVIDERS[p]["label"] for p in selected],
            unavailable={PROVIDERS[p]["label"]: e for p, e in first_errors.items()},
            notes=[
                {"provider": PROVIDERS[p]["label"], "text": text[:MAX_NOTE_CHARS]}
                for p, text in synthesis_source.items()
            ],
            warnings=review_errors,
        )
    except Exception as exc:
        publish(job_id, status="error", phase="Falhou", error=str(exc))


# -------------------- Teste das IAs (Painel de Confiança) --------------------
# Uma pergunta mínima para cada IA, todas ao mesmo tempo, para saber quem está
# respondendo agora e em quanto tempo. O teste também atualiza a memória de
# falhas (quem falhou fica etiquetado, quem voltou sai da etiqueta), mas não
# toca no histórico nem no conteúdo das conversas.

TEST_PROMPT = "Responda apenas: OK"
TEST_TIMEOUT_SECONDS = 60
MAX_CHECKS = 12

checks: dict[str, dict[str, Any]] = {}
checks_lock = threading.Lock()


def strip_ansi(text: str) -> str:
    """Tira os códigos de cor que alguns CLIs jogam no meio do erro."""
    return re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text or "")


def clean_detail(detail: str, limit: int = 300) -> str:
    return " ".join(strip_ansi(detail).split())[:limit]


def publish_check(check_id: str, **changes: Any) -> None:
    with checks_lock:
        check = checks.get(check_id)
        if check is None:
            return
        check.update(changes)
        check["updated"] = time.time()


def probe_provider(provider: str) -> dict[str, Any]:
    """Uma pergunta trivial: devolve o tempo, a resposta e o motivo do fracasso."""
    started = time.time()
    try:
        text = run_provider(provider, TEST_PROMPT)
    except Exception as exc:
        detail = str(exc)
        with provider_error_lock:
            provider_last_error[provider] = detail
        return {
            "ok": False,
            "seconds": round(time.time() - started, 1),
            "reason": short_failure_reason(detail),
            "detail": clean_detail(detail),
        }
    with provider_error_lock:
        provider_last_error.pop(provider, None)
    return {
        "ok": True,
        "seconds": round(time.time() - started, 1),
        "sample": clean_detail(text, 90),
    }


def run_check(check_id: str, providers: list[str]) -> None:
    results: dict[str, dict[str, Any]] = {}
    results_lock = threading.Lock()

    def worker(provider: str) -> None:
        outcome = probe_provider(provider)
        with results_lock:
            results[provider] = outcome
            snapshot = dict(results)
        publish_check(check_id, results=snapshot)

    threads = [threading.Thread(target=worker, args=(provider,), daemon=True) for provider in providers]
    for thread in threads:
        thread.start()
    deadline = time.time() + TEST_TIMEOUT_SECONDS
    for thread in threads:
        thread.join(max(0.1, deadline - time.time()))
    with results_lock:
        # Quem não voltou dentro do prazo aparece como "demorou demais" — e, se
        # responder depois, o próprio worker corrige o painel.
        for provider in providers:
            if provider not in results:
                results[provider] = {
                    "ok": False,
                    "seconds": TEST_TIMEOUT_SECONDS,
                    "reason": "demorou demais",
                    "detail": f"Sem resposta em {TEST_TIMEOUT_SECONDS} s; a IA pode estar presa numa fila.",
                }
        snapshot = dict(results)
    publish_check(check_id, results=snapshot, status="done", finished=time.time())


def start_check(providers: list[str]) -> dict[str, Any]:
    check_id = uuid.uuid4().hex
    with checks_lock:
        if len(checks) >= MAX_CHECKS:
            oldest = sorted(checks, key=lambda item: checks[item].get("updated", 0))
            for stale in oldest[: len(checks) - MAX_CHECKS + 1]:
                checks.pop(stale, None)
        checks[check_id] = {
            "id": check_id,
            "status": "running",
            "providers": providers,
            "results": {},
            "created": time.time(),
            "updated": time.time(),
        }
    threading.Thread(target=run_check, args=(check_id, providers), daemon=True).start()
    return {"id": check_id, "status": "running", "providers": providers}


def installed_provider_ids() -> list[str]:
    return [item["id"] for item in provider_status() if item["installed"]]


# ------------------------------- Histórico -------------------------------
# As conversas ficam em `historico.json`, nesta pasta. Nada sai do computador:
# o arquivo é escrito localmente e lido de volta quando você abre o Histórico.

def note_text(note: Any) -> str:
    """O texto de uma contribuição, venha ele do formato novo ou do antigo.

    Até a Opção A1 esse texto vinha cortado em 1.400 caracteres e morava no campo
    `summary`. Hoje ele vem completo no campo `text`; `summary` continua sendo
    aceito para as conversas gravadas antes da mudança abrirem normalmente.
    """
    if not isinstance(note, dict):
        return ""
    return str(note.get("text") or note.get("summary") or "")


def _clean_history_entry(raw: Any) -> dict[str, Any] | None:
    """Aceita só o que a Mesa sabe desenhar de volta na tela."""
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role", ""))
    if role not in ("user", "assistant"):
        return None
    entry: dict[str, Any] = {"role": role, "text": str(raw.get("text", ""))[:MAX_NOTE_CHARS]}
    if role == "assistant":
        entry["provider"] = str(raw.get("provider", ""))[:60]
        notes = []
        for note in raw.get("notes") or []:
            if isinstance(note, dict) and len(notes) < 12:
                notes.append({
                    "provider": str(note.get("provider", ""))[:60],
                    "text": note_text(note)[:MAX_NOTE_CHARS],
                })
        entry["notes"] = notes
    return entry


def read_history() -> list[dict[str, Any]]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    items = data.get("conversations") if isinstance(data, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def write_history(items: list[dict[str, Any]]) -> None:
    """Grava num arquivo temporário e troca: um Ctrl+C no meio não corrompe o JSON."""
    temporary = HISTORY_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"version": 1, "conversations": items[:MAX_HISTORY]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    temporary.replace(HISTORY_FILE)


def history_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id", "")),
        "title": str(item.get("title", ""))[:80],
        "created": float(item.get("created", 0) or 0),
        "updated": float(item.get("updated", 0) or 0),
        "count": len(item.get("messages") or []),
    }


def save_conversation(raw: dict[str, Any]) -> dict[str, Any] | None:
    messages = [
        entry for entry in (_clean_history_entry(item) for item in (raw.get("messages") or [])[:200])
        if entry
    ]
    if not messages:
        return None
    conversation_id = str(raw.get("id") or "").strip()[:64]
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", conversation_id):
        conversation_id = uuid.uuid4().hex
    title = str(raw.get("title") or "").strip().replace("\n", " ")[:80]
    if not title:
        first_user = next((entry["text"] for entry in messages if entry["role"] == "user"), "")
        title = first_user.strip().replace("\n", " ")[:80] or "Conversa sem título"
    with history_lock:
        items = read_history()
        previous = next((item for item in items if str(item.get("id")) == conversation_id), None)
        now = time.time()
        record = {
            "id": conversation_id,
            "title": title,
            "created": float(previous.get("created", now)) if previous else now,
            "updated": now,
            "messages": messages,
        }
        # Mais recente primeiro.
        items = [item for item in items if str(item.get("id")) != conversation_id]
        items.insert(0, record)
        write_history(items)
    return history_summary(record)


def delete_conversation(conversation_id: str) -> bool:
    with history_lock:
        items = read_history()
        remaining = [item for item in items if str(item.get("id")) != conversation_id]
        if len(remaining) == len(items):
            return False
        write_history(remaining)
    return True


# --------------------------- Busca no histórico ---------------------------
# A comparação ignora maiúsculas e acentos sem mudar o tamanho do texto (cada
# caractere continua valendo um), então o trecho mostrado cai exatamente onde a
# palavra foi encontrada. "orcamento" acha "orçamento", "PLANO" acha "plano".

def _fold_char(character: str) -> str:
    decomposed = unicodedata.normalize("NFD", character)
    base = decomposed[0] if decomposed else character
    return base if base.isascii() else character


def fold_text(text: str) -> str:
    """Minúsculas e sem acento, um caractere por caractere."""
    if text.isascii():
        return text.lower()
    return "".join(_fold_char(character) for character in text).lower()


def searchable_text(item: dict[str, Any]) -> str:
    parts = [str(item.get("title", ""))]
    for entry in item.get("messages") or []:
        parts.append(str(entry.get("text", "")))
        parts.append(str(entry.get("provider", "")))
        for note in entry.get("notes") or []:
            parts.append(str(note.get("provider", "")))
            parts.append(note_text(note))
    return "\n".join(parts)


def match_excerpt(item: dict[str, Any], wanted: str, width: int = 120) -> str:
    """Um trecho em volta da palavra achada — na resposta final ou numa contribuição."""
    for entry in item.get("messages") or []:
        considerados = [str(entry.get("text", ""))]
        considerados += [note_text(note) for note in entry.get("notes") or []]
        for bruto in considerados:
            text = " ".join(bruto.split())
            position = fold_text(text).find(wanted)
            if position < 0:
                continue
            start = max(0, position - width // 3)
            end = min(len(text), start + width)
            excerpt = text[start:end].strip()
            return ("…" if start > 0 else "") + excerpt + ("…" if end < len(text) else "")
    return ""


def search_history(term: str) -> dict[str, Any]:
    items = read_history()
    wanted = fold_text(term.strip())
    if not wanted:
        return {"conversations": [history_summary(item) for item in items], "total": len(items)}
    found = []
    for item in items:
        if wanted not in fold_text(searchable_text(item)):
            continue
        summary = history_summary(item)
        summary["match"] = match_excerpt(item, wanted)
        found.append(summary)
    return {"conversations": found, "total": len(items), "term": term.strip()}


# ------------------------ Exportar a conversa -----------------------------
# O arquivo é montado aqui, e não no navegador: o mesmo link serve para baixar
# direto, sem depender da tela aberta. Saem dois formatos: Markdown (para editar
# ou colar em qualquer lugar) e uma página .html pronta para imprimir ou enviar.

def provider_label(value: Any) -> str:
    info = PROVIDERS.get(str(value or ""))
    return str(info["label"]) if info else (str(value) if value else "Mesa")


def readable_time(seconds: Any) -> str:
    try:
        return time.strftime("%d/%m/%Y às %H:%M", time.localtime(float(seconds or 0)))
    except (OSError, ValueError, OverflowError, TypeError):
        return ""


def title_slug(item: dict[str, Any]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", fold_text(str(item.get("title") or "conversa"))).strip("-")[:48].strip("-")
    return f"mesa-{base}" if base else "mesa-conversa"


def export_markdown(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Conversa sem título")
    entries = item.get("messages") or []
    lines = [
        f"# {title}",
        "",
        f"*Conversa da Mesa de IAs · {len(entries)} mensagens · {readable_time(item.get('updated'))}*",
        "",
        "---",
        "",
    ]
    for entry in entries:
        text = str(entry.get("text", "")).strip()
        if entry.get("role") == "user":
            lines += ["## Você", "", text, ""]
            continue
        lines += [f"## Resposta da mesa — {provider_label(entry.get('provider'))}", "", text, ""]
        notes = [note for note in (entry.get("notes") or []) if note_text(note).strip()]
        if notes:
            lines += ["### Contribuições das IAs", ""]
            for note in notes:
                lines += [f"**{note.get('provider') or 'IA'}**", "", note_text(note).strip(), ""]
        lines += ["---", ""]
    lines += ["_Gerado pela Mesa de IAs neste computador._", ""]
    return "\n".join(lines)


EXPORT_CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#f6f5f1;color:#20221f;font:15px/1.7 'DM Sans',-apple-system,'Segoe UI',Roboto,sans-serif}
.doc{max-width:740px;margin:0 auto;padding:46px 26px 70px}
header{border-bottom:1px solid #e8e7e1;padding-bottom:18px}
.marca{display:flex;align-items:center;gap:9px;font:700 10.5px/1 'DM Mono',ui-monospace,monospace;letter-spacing:1.3px;text-transform:uppercase;color:#426b50}
.marca i{display:grid;place-items:center;width:24px;height:24px;border-radius:8px;background:#426b50;color:#fff;font-size:15px;font-style:normal}
h1{font-size:26px;line-height:1.28;letter-spacing:-.5px;margin:14px 0 8px}
.meta{font:11.5px/1.5 'DM Mono',ui-monospace,monospace;color:#777a72}
.turn{margin-top:32px}
.rotulo{font:600 10px/1 'DM Mono',ui-monospace,monospace;letter-spacing:1.2px;text-transform:uppercase;color:#8a8d84;margin:0 0 9px}
.ask{background:#eaede4;border:1px solid #e1e5db;border-radius:14px;padding:12px 15px;white-space:pre-wrap}
.answer{background:#fff;border:1px solid #e8e7e1;border-radius:14px;padding:19px 21px;box-shadow:0 8px 30px rgba(36,42,33,.06)}
.answer>.rotulo{color:#426b50}
.notes{margin-top:16px;border-top:1px solid #e8e7e1;padding-top:13px}
.notes>summary{cursor:pointer;color:#526d54;font:600 12.5px 'DM Sans',sans-serif}
.note{margin-top:11px;background:#fafbf8;border:1px solid #eceee9;border-radius:10px;padding:11px 13px}
.note h4{margin:0 0 7px;font:700 11px 'DM Sans',sans-serif;color:#4f634f;letter-spacing:.3px}
.text>*:first-child{margin-top:0}
.text>*:last-child{margin-bottom:0}
.text p{margin:0 0 12px}
.text h3,.text h4,.text h5,.text h6{margin:20px 0 9px;line-height:1.3;letter-spacing:-.2px}
.text h3{font-size:17px}.text h4{font-size:15px}.text h5,.text h6{font-size:13.5px;color:#4f5a4d}
.text ul,.text ol{padding-left:22px;margin:0 0 12px}
.text li{margin:4px 0}
.text li::marker{color:#426b50;font-weight:700}
.text code{background:#f2f3ee;border:1px solid #e6e7e1;border-radius:5px;padding:1px 5px;font:12.5px 'DM Mono',ui-monospace,monospace}
.text pre{background:#23241f;color:#eee7d9;border-radius:12px;padding:14px 16px;overflow:auto}
.text pre code{background:none;border:0;padding:0;color:inherit;font-size:12.5px;line-height:1.6}
.text blockquote{margin:0 0 12px;padding:2px 0 2px 14px;border-left:3px solid #cfd8c9;color:#5b6157}
.text a{color:#3c6b4c}
footer{margin-top:40px;padding-top:16px;border-top:1px solid #e8e7e1;font:11px 'DM Mono',ui-monospace,monospace;color:#94978f}
@media print{body{background:#fff}.answer{box-shadow:none}}
"""


def escape_html(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def inline_markdown(text: str) -> str:
    output = escape_html(text)
    output = re.sub(r"`([^`]+)`", r"<code>\1</code>", output)
    output = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", output)
    output = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", output)
    output = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noopener">\1</a>', output)
    return output


def markdown_to_html(text: Any) -> str:
    """A mesma leitura de Markdown que a tela faz, só que gerando texto .html."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            output.append(f"</{list_tag}>")
            list_tag = None

    for line in lines:
        if line.strip().startswith("```"):
            flush_paragraph()
            close_list()
            if in_code:
                output.append(f"<pre><code>{escape_html(chr(10).join(code_lines))}</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = min(6, len(heading.group(1)) + 2)
            output.append(f"<h{level}>{inline_markdown(heading.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^\s*(?:[-*+]\s+|(\d+)[.)]\s+)(.*)$", line)
        if bullet:
            flush_paragraph()
            tag = "ol" if bullet.group(1) else "ul"
            if list_tag != tag:
                close_list()
                output.append(f"<{tag}>")
                list_tag = tag
            output.append(f"<li>{inline_markdown(bullet.group(2))}</li>")
            continue
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            flush_paragraph()
            close_list()
            output.append(f"<blockquote>{inline_markdown(quote.group(1))}</blockquote>")
            continue
        paragraph.append(line.strip())
    if in_code and code_lines:
        output.append(f"<pre><code>{escape_html(chr(10).join(code_lines))}</code></pre>")
    flush_paragraph()
    close_list()
    return "\n".join(output)


def export_html(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Conversa sem título")
    entries = item.get("messages") or []
    when = escape_html(readable_time(item.get("updated")))
    parts = [
        "<!DOCTYPE html>",
        '<html lang="pt-BR">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{escape_html(title)}</title>",
        f"<style>{EXPORT_CSS}</style>",
        "</head>",
        "<body>",
        '<main class="doc">',
        "<header>",
        '<div class="marca"><i>✳</i> Mesa de IAs</div>',
        f"<h1>{escape_html(title)}</h1>",
        f'<div class="meta">{len(entries)} mensagens · {when}</div>',
        "</header>",
    ]
    for entry in entries:
        if entry.get("role") == "user":
            parts += [
                '<section class="turn">',
                '<p class="rotulo">Você</p>',
                f'<div class="ask">{escape_html(entry.get("text"))}</div>',
                "</section>",
            ]
            continue
        parts += [
            '<section class="turn">',
            f'<p class="rotulo">Resposta da mesa — {escape_html(provider_label(entry.get("provider")))}</p>',
            f'<article class="answer"><div class="text">{markdown_to_html(entry.get("text"))}</div>',
        ]
        notes = [note for note in (entry.get("notes") or []) if note_text(note).strip()]
        if notes:
            parts.append('<details class="notes" open><summary>Contribuições das IAs</summary>')
            for note in notes:
                parts += [
                    '<div class="note">',
                    f"<h4>{escape_html(note.get('provider') or 'IA')}</h4>",
                    f'<div class="text">{markdown_to_html(note_text(note))}</div>',
                    "</div>",
                ]
            parts.append("</details>")
        parts += ["</article>", "</section>"]
    parts += [
        f"<footer>Gerado pela Mesa de IAs neste computador · {when}</footer>",
        "</main>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


class Handler(BaseHTTPRequestHandler):
    server_version = "MesaIAs/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_export(self, conversation_id: str, query: dict[str, list[str]]) -> None:
        item = next((entry for entry in read_history() if str(entry.get("id")) == conversation_id), None)
        if not item:
            self.send_json(404, {"error": "Conversa não encontrada"})
            return
        fmt = (query.get("formato", ["md"])[0] or "md").strip().lower()
        if fmt not in ("md", "html"):
            self.send_json(400, {"error": "Formato de exportação desconhecido"})
            return
        if fmt == "html":
            body = export_html(item).encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            body = export_markdown(item).encode("utf-8")
            content_type = "text/markdown; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{title_slug(item)}.{fmt}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/providers":
            self.send_json(200, {"providers": provider_status()})
            return
        if parsed.path == "/api/historico":
            term = (parse_qs(parsed.query).get("busca", [""])[0] or "").strip()
            self.send_json(200, search_history(term))
            return
        if parsed.path.startswith("/api/historico/"):
            rest = unquote(parsed.path.removeprefix("/api/historico/"))
            if rest.endswith("/exportar"):
                self.send_export(rest[: -len("/exportar")], parse_qs(parsed.query))
                return
            found = next((item for item in read_history() if str(item.get("id")) == rest), None)
            if not found:
                self.send_json(404, {"error": "Conversa não encontrada"})
                return
            self.send_json(200, found)
            return
        if parsed.path.startswith("/api/testar/"):
            check_id = unquote(parsed.path.removeprefix("/api/testar/"))
            with checks_lock:
                check = checks.get(check_id)
            if not check:
                self.send_json(404, {"error": "Teste não encontrado (ele é temporário)"})
                return
            self.send_json(200, check)
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = unquote(parsed.path.removeprefix("/api/jobs/"))
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                self.send_json(404, {"error": "Conversa não encontrada"})
                return
            self.send_json(200, job)
            return
        if parsed.path in ("/", "/index.html"):
            path = STATIC / "index.html"
        elif parsed.path.startswith("/static/"):
            path = (STATIC / parsed.path.removeprefix("/static/")).resolve()
            if STATIC.resolve() not in path.parents:
                self.send_error(403)
                return
        else:
            self.send_error(404)
            return
        if not path.is_file():
            self.send_error(404)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(path.suffix.lower(), "application/octet-stream")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/historico/"):
            self.send_error(404)
            return
        conversation_id = unquote(path.removeprefix("/api/historico/"))
        if delete_conversation(conversation_id):
            self.send_json(200, {"removed": conversation_id})
        else:
            self.send_json(404, {"error": "Conversa não encontrada"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/historico":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 2_000_000:
                    self.send_json(413, {"error": "Conversa muito grande"})
                    return
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    self.send_json(400, {"error": "Pedido inválido"})
                    return
                saved = save_conversation(data)
                if not saved:
                    self.send_json(400, {"error": "Conversa vazia"})
                    return
                self.send_json(200, saved)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": f"Pedido inválido: {exc}"})
            except OSError as exc:
                self.send_json(500, {"error": f"Não consegui gravar o histórico: {exc}"})
            return
        if path == "/api/testar":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    self.send_json(413, {"error": "Pedido muito grande"})
                    return
                data = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(data, dict):
                    self.send_json(400, {"error": "Pedido inválido"})
                    return
                requested = data.get("providers")
                if isinstance(requested, list) and requested:
                    chosen = [str(item) for item in requested if str(item) in PROVIDERS]
                else:
                    chosen = installed_provider_ids()
                if not chosen:
                    self.send_json(400, {"error": "Nenhuma IA instalada para testar. Instale ou ligue pelo menos uma."})
                    return
                self.send_json(202, start_check(chosen))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": f"Pedido inválido: {exc}"})
            return
        if path != "/api/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 100_000:
                self.send_json(413, {"error": "Mensagem muito grande"})
                return
            data = json.loads(self.rfile.read(length))
            message = str(data.get("message", "")).strip()
            selected = list(dict.fromkeys(data.get("providers", [])))
            history = data.get("history", [])
            synthesizer = data.get("synthesizer", "codex")
            installed = {p["id"] for p in provider_status() if p["installed"]}
            if not message:
                self.send_json(400, {"error": "Escreva uma mensagem primeiro"})
                return
            if len(message) > 12_000:
                self.send_json(400, {"error": "Limite de 12.000 caracteres por mensagem"})
                return
            if len(selected) < 2:
                self.send_json(400, {"error": "Selecione pelo menos duas IAs instaladas"})
                return
            if any(p not in PROVIDERS for p in selected):
                self.send_json(400, {"error": "Uma IA selecionada não é reconhecida"})
                return
            unavailable = [p for p in selected if p not in installed]
            if unavailable:
                paused = [p for p in unavailable if p in PAUSED_PROVIDERS]
                if paused:
                    labels = ", ".join(PROVIDERS[p]["label"] for p in paused)
                    self.send_json(400, {"error": f"Temporariamente desativado na Mesa: {labels}"})
                    return
                labels = ", ".join(PROVIDERS[p]["label"] for p in unavailable)
                self.send_json(400, {"error": f"Instale primeiro: {labels}"})
                return
            if synthesizer not in selected:
                synthesizer = selected[0]
            if not isinstance(history, list):
                history = []
            history = [
                {"role": str(item.get("role", "user")), "content": str(item.get("content", ""))[:8000]}
                for item in history[-12:] if isinstance(item, dict)
                and item.get("role") in ("user", "assistant")
            ]
            mode = "fast" if data.get("mode") == "fast" else "complete"
            job_id = uuid.uuid4().hex
            with jobs_lock:
                if len(jobs) >= MAX_JOBS:
                    oldest = sorted(jobs, key=lambda item: jobs[item].get("updated", 0))
                    for old_id in oldest[:len(jobs) - MAX_JOBS + 1]:
                        jobs.pop(old_id, None)
                jobs[job_id] = {
                    "id": job_id,
                    "status": "queued",
                    "phase": "Na fila",
                    "provider_output": {},
                    "mode": mode,
                    "created": time.time(),
                    "updated": time.time(),
                }
            thread = threading.Thread(
                target=orchestrate,
                args=(job_id, message, history, selected, synthesizer, mode),
                daemon=True,
            )
            thread.start()
            self.send_json(202, {"id": job_id})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": f"Pedido inválido: {exc}"})


if __name__ == "__main__":
    print(f"Mesa de IAs aberta em http://{HOST}:{PORT}")
    print("Este servidor aceita conexões apenas deste computador. Pressione Ctrl+C para fechar.")
    # Preload the local model so the first reply is not a cold start.
    threading.Thread(target=warm_ollama, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
