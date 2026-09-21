#!/usr/bin/env python3
"""
Idempotently wire the CenterOS-Proxmox overlay into a CenterOS checkout:

1. Copy overlay pages (add-workflow, chat, run-workflow, settings) into
   <root>/dashboard/pages/.
2. Insert sidebar links after the WORKFLOW_LINKS_END marker in
   <root>/dashboard/index.html (marker-guarded, never duplicated, placed
   outside the region managed by create-dashboard-page.py).

Usage: patch-dashboard.py --root /opt/centeros --overlay /opt/centeros-proxmox/app
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

END_MARKER = "<!-- WORKFLOW_LINKS_END -->"
FAVICON_MARKER = "<!-- FAVICON_LINK -->"
FAVICON_LINK = f'{FAVICON_MARKER}\n  <link rel="icon" href="/favicon.svg" type="image/svg+xml">'

PAGES = ("add-workflow.html", "chat.html", "run-workflow.html", "settings.html")

# (marker, href, icon, label)
LINKS = (
    ("<!-- AI_LINK_CHAT -->", "pages/chat.html", "bi-chat-dots", "Chat"),
    ("<!-- AI_LINK_RUN -->", "pages/run-workflow.html", "bi-play-circle", "Run"),
    ("<!-- ADD_WORKFLOW_LINK -->", "pages/add-workflow.html", "bi-plus-circle", "+ Workflow"),
    ("<!-- AI_LINK_SETTINGS -->", "pages/settings.html", "bi-gear", "Settings"),
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wire the CenterOS-Proxmox overlay into CenterOS.")
    p.add_argument("--root", required=True, help="CenterOS checkout dir")
    p.add_argument("--overlay", required=True, help="Overlay app dir (contains dashboard/pages/)")
    return p.parse_args()


def build_link(marker: str, href: str, icon: str, label: str) -> str:
    return f"""
        {marker}
        <a class="nav-item" href="{href}" target="dashboard-frame">
          <span class="nav-icon" aria-hidden="true">
            <i class="bi {icon}"></i>
          </span>
          <span>{label}</span>
        </a>"""


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    overlay = Path(args.overlay)
    try:
        index = root / "dashboard" / "index.html"
        if not index.is_file():
            print(f"error: missing dashboard shell: {index}", file=sys.stderr)
            return 1

        for page in PAGES:
            src = overlay / "dashboard" / "pages" / page
            if not src.is_file():
                print(f"error: missing overlay page: {src}", file=sys.stderr)
                return 1
            target = root / "dashboard" / "pages" / page
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            print(f"installed page: {target.relative_to(root)}")

        html = index.read_text(encoding="utf-8")
        if END_MARKER not in html:
            print(f"error: {END_MARKER} marker not found in dashboard/index.html", file=sys.stderr)
            return 1
        changed = False
        if FAVICON_MARKER in html:
            print("favicon link already present: dashboard/index.html")
        elif "</head>" in html:
            html = html.replace("</head>", "  " + FAVICON_LINK + "\n</head>", 1)
            print("added favicon link: dashboard/index.html")
            changed = True
        else:
            print("error: no </head> found in dashboard/index.html", file=sys.stderr)
            return 1
        for marker, href, icon, label in LINKS:
            if marker in html:
                print(f"sidebar link already present: {label}")
                continue
            html = html.replace(END_MARKER, END_MARKER + build_link(marker, href, icon, label), 1)
            print(f"added sidebar link: {label}")
            changed = True
        if changed:
            index.write_text(html, encoding="utf-8", newline="\n")
            print("updated: dashboard/index.html")
        else:
            print("sidebar already current: dashboard/index.html")
        return 0
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
