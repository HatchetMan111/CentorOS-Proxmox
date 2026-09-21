#!/usr/bin/env python3
"""
CenterOS dashboard server (Python standard library only).

Serves <root>/dashboard/ statically and adds a tiny workflow API:

  GET  /api/health      -> {"status": "ok"}
  GET  /api/workflows   -> [{"slug": ..., "name": ..., "dashboard": true/false}]
  POST /api/workflows   -> {"slug","name","description","icon"?} creates:
                           - workflows/<slug>/{CONTEXT.md,LOG.md} (from templates/workflow/)
                           - dashboard/workflows/<slug>/index.html + sidebar link
                             (via dashboard/create-dashboard-page.py, no duplicated logic)

No auth — intended for a local Proxmox LXC on a trusted LAN, like the
static python http.server it replaces.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ICON_RE = re.compile(r"^[a-z0-9-]+$")
DEFAULT_ICON = "bi-file-earmark-text"
MAX_BODY = 64 * 1024


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CenterOS dashboard server with workflow API.")
    p.add_argument("--root", default="/opt/centeros", help="CenterOS checkout dir (default: /opt/centeros)")
    p.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    p.add_argument("--bind", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    return p.parse_args()


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

    def do_GET(self) -> None:  # noqa: ANN201
        if self.path == "/api/health":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/api/workflows":
            self._json(200, {"workflows": list_workflows(self.root)})
            return
        if self.path.startswith("/api/"):
            self._json(404, {"error": "unknown API endpoint"})
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: ANN201
        if self.path != "/api/workflows":
            self._json(404, {"error": "unknown API endpoint"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "invalid Content-Length"})
            return
        if length <= 0 or length > MAX_BODY:
            self._json(400, {"error": "body must be 1..65536 bytes of JSON"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "invalid JSON body"})
            return

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
