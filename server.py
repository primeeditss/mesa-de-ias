from __future__ import annotations

import json
import os
import codecs
import re
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
from urllib.parse import quote, unquote, urlparse


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
HOST = "127.0.0.1"
PORT = 8765
TIMEOUT_SECONDS = 240
MAX_JOBS = 30

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


def run_parallel(
    providers: list[str],
    prompts: dict[str, str],
    on_progress: Callable[[str, str], None] | None = None,
    on_output: Callable[[str, str], None] | None = None,
    progress_label: str = "Respondendo",
) -> tuple[dict[str, str], dict[str, str]]:
    results: dict[str, str] = {}
    errors: dict[str, str] = {}
    result_lock = threading.Lock()
    workers = []

    def worker(provider: str) -> None:
        if on_progress:
            on_progress(provider, progress_label)
        try:
            answer = run_provider(
                provider,
                prompts[provider],
                on_output=lambda chunk: on_output(provider, chunk) if on_output else None,
            )
            with result_lock:
                results[provider] = answer
            if on_progress:
                on_progress(provider, "Concluída")
        except Exception as exc:
            with result_lock:
                errors[provider] = str(exc)
            if on_progress:
                on_progress(provider, "Não respondeu")

    for provider in providers:
        thread = threading.Thread(target=worker, args=(provider,), daemon=True)
        thread.start()
        workers.append(thread)
    for thread in workers:
        thread.join(TIMEOUT_SECONDS + 10)
    return results, errors


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
        first, first_errors = run_parallel(
            selected,
            initial_prompts,
            on_progress=lambda provider, state: update_provider_progress(job_id, provider, state),
            on_output=lambda provider, chunk: update_provider_output(job_id, provider, chunk),
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
            reviews, review_errors = run_parallel(
                list(first),
                review_prompts,
                on_progress=lambda provider, state: update_provider_progress(job_id, provider, state),
                on_output=lambda provider, chunk: update_provider_output(job_id, provider, chunk),
                progress_label="Revisando",
            )
            if not reviews:
                reviews = first
                review_errors = {**review_errors, "aviso": "A revisão falhou; usei as respostas iniciais."}

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

        publish(
            job_id,
            status="done",
            phase="Concluído",
            final=final,
            final_provider=final_provider,
            participants=[PROVIDERS[p]["label"] for p in selected],
            unavailable={PROVIDERS[p]["label"]: e for p, e in first_errors.items()},
            notes=[
                {"provider": PROVIDERS[p]["label"], "summary": text[:1400]}
                for p, text in synthesis_source.items()
            ],
            warnings=review_errors,
        )
    except Exception as exc:
        publish(job_id, status="error", phase="Falhou", error=str(exc))


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

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/providers":
            self.send_json(200, {"providers": provider_status()})
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

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/chat":
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
