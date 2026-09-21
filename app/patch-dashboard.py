#!/usr/bin/env python3
"""
Idempotently wire the CenterOS-Proxmox overlay into a CenterOS checkout:

1. Copy app/dashboard/pages/add-workflow.html -> <root>/dashboard/pages/.
2. Insert a "+ Workflow" sidebar link after the WORKFLOW_LINKS_END marker
   in <root>/dashboard/index.html (marker-guarded, never duplicated,
   placed outside the region managed by create-dashboard-page.py).

Usage: patch-dashboard.py --root /opt/centeros --overlay /opt/centeros-proxmox/app
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MARKER = "<!-- ADD_WORKFLOW_LINK -->"
END_MARKER = "<!-- WORKFLOW_LINKS_END -->"

ADD_LINK = """
        <!-- ADD_WORKFLOW_LINK -->
        <a class="nav-item" href="pages/add-workflow.html" target="dashboard-frame">
          <span class="nav-icon" aria-hidden="true">
            <i class="bi bi-plus-circle"></i>
          </span>
          <span>+ Workflow</span>
        </a>"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wire the + Workflow overlay into CenterOS.")
    p.add_argument("--root", required=True, help="CenterOS checkout dir")
    p.add_argument("--overlay", required=True, help="Overlay app dir (contains dashboard/pages/)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    overlay = Path(args.overlay)
    try:
        src = overlay / "dashboard" / "pages" / "add-workflow.html"
        index = root / "dashboard" / "index.html"
        if not src.is_file():
            print(f"error: missing overlay page: {src}", file=sys.stderr)
            return 1
        if not index.is_file():
            print(f"error: missing dashboard shell: {index}", file=sys.stderr)
            return 1

        target = root / "dashboard" / "pages" / "add-workflow.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        print(f"installed page: {target.relative_to(root)}")

        html = index.read_text(encoding="utf-8")
        if MARKER in html:
            print("sidebar link already present: dashboard/index.html")
            return 0
        if END_MARKER not in html:
            print(f"error: {END_MARKER} marker not found in dashboard/index.html", file=sys.stderr)
            return 1
        html = html.replace(END_MARKER, END_MARKER + ADD_LINK, 1)
        index.write_text(html, encoding="utf-8", newline="\n")
        print("added + Workflow sidebar link: dashboard/index.html")
        return 0
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
