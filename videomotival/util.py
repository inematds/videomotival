"""Utilitários compartilhados: JSON atômico, HTTP sem dependências, slug, ffprobe."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "videomotival/1.0 (+local pipeline)"


class PipelineError(RuntimeError):
    pass


def say(message: str) -> None:
    print(message, flush=True)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PipelineError(f"Arquivo obrigatório ausente: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"JSON inválido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PipelineError(f"Esperava um objeto JSON em {path}")
    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def slugify(value: str) -> str:
    import unicodedata

    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:54].rstrip("-") or "video"


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise PipelineError(f"Executável obrigatório não encontrado no PATH: {name}")
    return path


def http_json(
    url: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
    retries: int = 3,
    method: str | None = None,
) -> Any:
    """POST (se body) ou GET com retry em erros transitórios. Devolve JSON decodificado."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read(600).decode("utf-8", errors="replace")
            if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt == retries:
                raise PipelineError(f"HTTP {exc.code} em {url}: {detail}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt == retries:
                break
        time.sleep(2 ** (attempt - 1))
    raise PipelineError(f"Falha após {retries} tentativas em {url}: {last}")


def http_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 300, body: dict[str, Any] | None = None) -> bytes:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"User-Agent": USER_AGENT}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(600).decode("utf-8", errors="replace")
        raise PipelineError(f"HTTP {exc.code} em {url}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PipelineError(f"Sem resposta de {url}: {exc}") from exc


def service_alive(url: str, timeout: int = 4) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except Exception:
        return False


def probe_duration(path: Path) -> float:
    ffprobe = require_binary("ffprobe")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise PipelineError(f"Não consegui ler a duração de {path}") from exc
    if duration <= 0:
        raise PipelineError(f"Duração não positiva em {path}")
    return duration


def run_process(command: list[str], label: str, log: Path | None = None) -> None:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise PipelineError(f"{label}: executável não encontrado ({command[0]})") from exc
    if log is not None:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n$ {' '.join(command)}\n{result.stdout}{result.stderr}")
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-6:]
        raise PipelineError(f"{label} falhou (exit {result.returncode}): " + " | ".join(tail))


def extract_json_object(text: str) -> dict[str, Any]:
    """Extrai o primeiro objeto JSON de uma resposta de LLM (tolera cercas ```json e prosa em volta)."""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if fence:
        text = fence.group(1)
    decoder = json.JSONDecoder()
    positions = [i for i, ch in enumerate(text) if ch == "{"][:40]
    if not positions:
        raise PipelineError("A resposta do modelo não contém um objeto JSON")
    fallback: Any = None
    for start in positions:
        candidate = text[start:]
        for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                data, _ = decoder.raw_decode(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("scenes"):
                return data
            if isinstance(data, dict) and fallback is None:
                fallback = data
    if fallback is None:
        raise PipelineError("JSON do modelo inválido (nenhum objeto decodificável na resposta)")
    data = fallback
    if not isinstance(data, dict):
        raise PipelineError("O modelo devolveu JSON que não é um objeto")
    return data
