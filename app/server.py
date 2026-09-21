#!/usr/bin/env python3
"""
CenterOS dashboard server (Python standard library only).

Serves <root>/dashboard/ statically and adds a tiny workflow + AI API:

  GET  /api/health      -> {"status": "ok"}
  GET  /api/workflows   -> [{"slug": ..., "name": ..., "dashboard": true/false}]
  POST /api/workflows   -> {"slug","name","description","icon"?} creates workflow
                           files + dashboard page + sidebar link
  GET  /api/settings    -> {"openrouter_configured": bool, "key_masked": str,
                            "model": str, "models": [...]}
  POST /api/settings    -> {"api_key"?, "model"?} stores config.json (mode 0600)
  POST /api/chat        -> {"messages": [{role, content}], "model"?} -> {"reply": ...}
  POST /api/run         -> {"workflow": slug, "input": text} runs a workflow via
                           the LLM, appends to workflows/<slug>/LOG.md

AI calls go to OpenRouter (OpenAI-compatible). Needs an API key from
https://openrouter.ai/keys — set it via the Settings page or the
OPENROUTER_API_KEY env var of the installer. The key is stored server-side
in <root>/config.json and never sent to the browser (only a masked hint).

Env: OPENROUTER_BASE_URL (default https://openrouter.ai/api/v1, for tests).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ICON_RE = re.compile(r"^[a-z0-9-]+$")
DEFAULT_ICON = "bi-file-earmark-text"
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
MAX_BODY = 64 * 1024
MAX_INPUT_CHARS = 12000
OPENROUTER_TIMEOUT = 120

CURATED_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-haiku",
    "deepseek/deepseek-chat",
]


class OpenRouterError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CenterOS dashboard server with workflow + AI API.")
    p.add_argument("--root", default="/opt/centeros", help="CenterOS checkout dir (default: /opt/centeros)")
    p.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    p.add_argument("--bind", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    return p.parse_args()


def base_url() -> str:
    return os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")


def config_path(root: Path) -> Path:
    return root / "config.json"


def load_config(root: Path) -> dict:
    try:
        data = json.loads(config_path(root).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_config(root: Path, api_key: str, model: str) -> None:
    path = config_path(root)
    path.write_text(
        json.dumps({"openrouter_api_key": api_key, "openrouter_model": model}, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def masked(key: str) -> str:
    key = key or ""
    if len(key) <= 8:
        return "****" if key else ""
    return f"{key[:4]}…{key[-4:]}"


def active_model(root: Path) -> str:
    return str(load_config(root).get("openrouter_model") or DEFAULT_MODEL)


def active_key(root: Path) -> str:
    return str(load_config(root).get("openrouter_api_key") or "")


def openrouter_chat(api_key: str, model: str, messages: list[dict]) -> str:
    """Call OpenRouter chat completions. Returns assistant text. Raises OpenRouterError."""
    payload = json.dumps({"model": model, "messages": messages}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url()}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/HatchetMan111/CentorOS-Proxmox",
            "X-Title": "CenterOS Dashboard",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OPENROUTER_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:500]
        except OSError:
            detail = ""
        if exc.code == 401:
            raise OpenRouterError("OpenRouter rejected the API key (401). Check Settings.", 502) from exc
        if exc.code == 402:
            raise OpenRouterError("OpenRouter: no credits left (402). Top up at openrouter.ai.", 502) from exc
        if exc.code == 429:
            raise OpenRouterError("OpenRouter rate limit (429). Wait a minute and retry.", 502) from exc
        raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {detail}", 502) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OpenRouterError(f"OpenRouter unreachable/timeout: {exc}", 504) from exc
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(f"Unexpected OpenRouter response: {str(data)[:500]}", 502) from exc


def normalize_icon(icon: str) -> str:
    icon = (icon or "").strip()
    if icon.startswith("bi "):
        icon = icon.split(" ", 1)[1]
    if icon.startswith("bi-"):
        icon = icon[3:]
    if not ICON_RE.fullmatch(icon):
        return DEFAULT_ICON
    return f"bi-{icon}"


def read_title(context_path: Path, slug: str) -> str:
    try:
        first = context_path.read_text(encoding="utf-8").splitlines()[0]
        m = re.match(r"#\s+(.+?)\s+-\s+CONTEXT\s*$", first.strip())
        if m:
            return m.group(1)
    except OSError:
        pass
    return slug


def list_workflows(root: Path) -> list[dict]:
    workflows_dir = root / "workflows"
    out: list[dict] = []
    if not workflows_dir.is_dir():
        return out
    for child in sorted(workflows_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        context = child / "CONTEXT.md"
        if not context.is_file():
            continue
        out.append(
            {
                "slug": child.name,
                "name": read_title(context, child.name),
                "dashboard": (root / "dashboard" / "workflows" / child.name / "index.html").is_file(),
            }
        )
    return out


def scaffold_source(root: Path, slug: str, name: str, description: str) -> None:
    """Create workflows/<slug>/{CONTEXT.md,LOG.md} from templates/workflow/."""
    template_dir = root / "templates" / "workflow"
    target = root / "workflows" / slug
    today = datetime.date.today().isoformat()
    context_tpl = (template_dir / "CONTEXT.md").read_text(encoding="utf-8")
    log_tpl = (template_dir / "LOG.md").read_text(encoding="utf-8")
    context = (
        context_tpl.replace("{{WORKFLOW_NAME}}", slug)
        .replace("{{ONE_LINE_PURPOSE}}", description)
        .replace("{{DATE}}", today)
    )
    log = log_tpl.replace("{{WORKFLOW_NAME}}", slug)
    log += f"\n- **{today}** - `created` - Scaffolded via dashboard workflow API (name: {name}).\n"
    target.mkdir(parents=True, exist_ok=False)
    (target / "CONTEXT.md").write_text(context, encoding="utf-8", newline="\n")
    (target / "LOG.md").write_text(log, encoding="utf-8", newline="\n")


def create_dashboard_page(root: Path, slug: str, name: str, description: str, icon: str) -> tuple[bool, str]:
    """Delegate to the upstream script. Returns (ok, output)."""
    script = root / "dashboard" / "create-dashboard-page.py"
    if not script.is_file():
        return False, f"Missing dashboard script: {script}"
    proc = subprocess.run(
        [sys.executable, str(script), slug, name, description, "--icon", icon],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.strip()


def build_run_messages(context_md: str, user_input: str) -> list[dict]:
    system = (
        "You are CenterOS, an AI operating system executing a user workflow.\n"
        "Follow the workflow definition below. Produce exactly the Outputs it specifies, "
        "as Markdown. If required input details are missing, say what is missing instead of guessing.\n\n"
        "--- WORKFLOW DEFINITION ---\n" + context_md[:8000]
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_input[:MAX_INPUT_CHARS]},
    ]


def append_run_log(root: Path, slug: str, model: str, user_input: str, ok: bool) -> None:
    excerpt = " ".join(user_input.split())[:160]
    line = (
        f"\n- **{datetime.date.today().isoformat()}** - `{'ran-complete' if ok else 'ran-failed'}`"
        f" - via dashboard API (model: {model}). Input: {excerpt}\n"
    )
    try:
        with (root / "workflows" / slug / "LOG.md").open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


class Handler(SimpleHTTPRequestHandler):
    root: Path

    def __init__(self, *args, root: Path, **kwargs):
        self.root = root
        super().__init__(*args, directory=str(root / "dashboard"), **kwargs)

    def log_message(self, fmt, *args):  # noqa: ANN001, ANN202 - keep stdlib signature
        sys.stderr.write("centeros-server: %s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> tuple[dict | None, str | None]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "invalid Content-Length"
        if length <= 0 or length > MAX_BODY:
            return None, "body must be 1..65536 bytes of JSON"
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "invalid JSON body"
        if not isinstance(data, dict):
            return None, "JSON body must be an object"
        return data, None

    def _require_key(self) -> str | None:
        key = active_key(self.root)
        if not key:
            self._json(
                400,
                {
                    "error": "openrouter_api_key_missing",
                    "hint": "Set your OpenRouter API key on the Settings page (Sidebar > Settings) "
                    "or via the OPENROUTER_API_KEY installer variable. Key: https://openrouter.ai/keys",
                },
            )
            return None
        return key

    def do_GET(self) -> None:  # noqa: ANN201
        if self.path == "/api/health":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/api/workflows":
            self._json(200, {"workflows": list_workflows(self.root)})
            return
        if self.path == "/api/settings":
            key = active_key(self.root)
            self._json(
                200,
                {
                    "openrouter_configured": bool(key),
                    "key_masked": masked(key),
                    "model": active_model(self.root),
                    "models": CURATED_MODELS,
                },
            )
            return
        if self.path.startswith("/api/"):
            self._json(404, {"error": "unknown API endpoint"})
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: ANN201
        if self.path == "/api/workflows":
            self._handle_create_workflow()
        elif self.path == "/api/settings":
            self._handle_settings()
        elif self.path == "/api/chat":
            self._handle_chat()
        elif self.path == "/api/run":
            self._handle_run()
        else:
            self._json(404, {"error": "unknown API endpoint"})

    def _handle_create_workflow(self) -> None:
        data, err = self._read_json()
        if err:
            self._json(400, {"error": err})
            return
        assert data is not None
        slug = str(data.get("slug") or "").strip()
        name = str(data.get("name") or "").strip()
        description = str(data.get("description") or "").strip()
        icon = normalize_icon(str(data.get("icon") or ""))

        if not SLUG_RE.fullmatch(slug):
            self._json(400, {"error": "slug must be lowercase kebab-case (a-z, 0-9, hyphens)"})
            return
        if not name:
            self._json(400, {"error": "name is required"})
            return
        if not description:
            self._json(400, {"error": "description is required"})
            return
        if (self.root / "workflows" / slug).exists() or (
            self.root / "dashboard" / "workflows" / slug
        ).exists():
            self._json(409, {"error": f"workflow '{slug}' already exists"})
            return

        ok, output = create_dashboard_page(self.root, slug, name, description, icon)
        if not ok:
            self._json(500, {"error": "dashboard page creation failed", "detail": output})
            return
        try:
            scaffold_source(self.root, slug, name, description)
        except (OSError, ValueError) as exc:
            self._json(500, {"error": "workflow source scaffolding failed", "detail": str(exc)})
            return
        self._json(
            201,
            {
                "slug": slug,
                "name": name,
                "dashboard": f"workflows/{slug}/index.html",
                "detail": output,
            },
        )

    def _handle_settings(self) -> None:
        data, err = self._read_json()
        if err:
            self._json(400, {"error": err})
            return
        assert data is not None
        current = load_config(self.root)
        api_key = str(data.get("api_key") or "").strip() or str(current.get("openrouter_api_key") or "")
        model = str(data.get("model") or "").strip() or str(current.get("openrouter_model") or DEFAULT_MODEL)
        if "api_key" in data and data.get("api_key") and not api_key.startswith("sk-or-"):
            self._json(400, {"error": "OpenRouter keys start with 'sk-or-'. Check for typos."})
            return
        if not model or len(model) > 200:
            self._json(400, {"error": "invalid model"})
            return
        try:
            save_config(self.root, api_key, model)
        except OSError as exc:
            self._json(500, {"error": "could not write config.json", "detail": str(exc)})
            return
        self._json(
            200,
            {"openrouter_configured": bool(api_key), "key_masked": masked(api_key), "model": model},
        )

    def _handle_chat(self) -> None:
        data, err = self._read_json()
        if err:
            self._json(400, {"error": err})
            return
        assert data is not None
        key = self._require_key()
        if key is None:
            return
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            self._json(400, {"error": "messages must be a non-empty list"})
            return
        clean: list[dict] = []
        for m in messages[-20:]:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")
            content = str(m.get("content") or "")[:MAX_INPUT_CHARS]
            if role not in ("system", "user", "assistant") or not content:
                continue
            clean.append({"role": role, "content": content})
        if not clean or all(m["role"] == "system" for m in clean):
            self._json(400, {"error": "messages must contain at least one user/assistant message"})
            return
        model = str(data.get("model") or "").strip() or active_model(self.root)
        try:
            reply = openrouter_chat(key, model, clean)
        except OpenRouterError as exc:
            self._json(exc.status, {"error": str(exc)})
            return
        self._json(200, {"reply": reply, "model": model})

    def _handle_run(self) -> None:
        data, err = self._read_json()
        if err:
            self._json(400, {"error": err})
            return
        assert data is not None
        key = self._require_key()
        if key is None:
            return
        slug = str(data.get("workflow") or data.get("slug") or "").strip()
        user_input = str(data.get("input") or "").strip()
        if not SLUG_RE.fullmatch(slug):
            self._json(400, {"error": "valid workflow slug required"})
            return
        if not user_input:
            self._json(400, {"error": "input is required"})
            return
        context_path = self.root / "workflows" / slug / "CONTEXT.md"
        if not context_path.is_file():
            self._json(404, {"error": f"unknown workflow '{slug}'"})
            return
        try:
            context_md = context_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._json(500, {"error": "could not read workflow", "detail": str(exc)})
            return
        model = str(data.get("model") or "").strip() or active_model(self.root)
        try:
            output = openrouter_chat(key, model, build_run_messages(context_md, user_input))
        except OpenRouterError as exc:
            append_run_log(self.root, slug, model, user_input, ok=False)
            self._json(exc.status, {"error": str(exc)})
            return
        append_run_log(self.root, slug, model, user_input, ok=True)
        self._json(200, {"slug": slug, "model": model, "output": output, "logged": True})


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if not (root / "dashboard" / "index.html").is_file():
        print(f"error: {root}/dashboard/index.html not found — is --root a CenterOS checkout?", file=sys.stderr)
        return 1
    server = ThreadingHTTPServer((args.bind, args.port), partial(Handler, root=root))
    print(f"centeros-server: serving {root / 'dashboard'} on http://{args.bind}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
