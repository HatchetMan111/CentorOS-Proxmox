# CenterOS auf Proxmox VE — Einzeiler-Installation (Community-Scripts-Stil)

Installiert [CenterOS](https://github.com/flatplanet/CenterOS) (statisches Dashboard + Python-stdlib,
keine Cloud nötig) als **unprivilegierten Debian-12-LXC** mit systemd-Service auf Port **8080**.

## Installation (auf dem Proxmox-Host als root)

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/flatplanet/CenterOS/main/install/centeros.sh)"
```

> Datei gehört in deinem Fork nach `install/centeros.sh` (dieses Bundle: `install/centeros.sh`,
> `systemd/centeros.service`). Einzeiler ggf. auf deinen Fork (`USER/REPO`) anpassen.

### Defaults (oben im Skript, per ENV überschreibbar)

| Variable | Default | Bedeutung |
|---|---|---|
| `CT_HOSTNAME` | `centeros` | LXC-Name |
| `CT_ID` | _(leer)_ | leer = **nächste freie ID** via `pvesh get /cluster/nextid` |
| `CT_CPU` / `CT_RAM` | `1` / `1024` | 1 vCPU, 1 GB RAM |
| `CT_DISK_GB` | `8` | rootfs (Spec 4–8 GB, 8 = sicherer Default) |
| `CT_DISK_STORAGE` | _(auto)_ | Root-Disk: `local-lvm`, sonst erster `rootdir`-Storage |
| `CT_TEMPLATE_STORAGE` | _(auto)_ | Template-Cache (`vztmpl`): `local`, sonst erster `vztmpl`-Storage — **nie `local-lvm`** |
| `CT_BRIDGE` / `CT_NET` | `vmbr0` / `dhcp` | Netzwerk |
| `WEB_PORT` | `8080` | Web UI, bind `0.0.0.0` |
| `INSTALL_DIR` | `/opt/centeros` | Git-Checkout im Container |
| `DEBUG` | `0` | `DEBUG=1` = `bash -x` Trace |

Beispiel mit eigenem Port / ID / Hostname:

```bash
CT_ID=150 CT_HOSTNAME=centeros WEB_PORT=8090 bash -c "$(wget -qLO - https://raw.githubusercontent.com/flatplanet/CenterOS/main/install/centeros.sh)"
```

## Workflows

Drei Beispiel-Workflows sind vorinstalliert (jeweils `workflows/<slug>/CONTEXT.md` + `LOG.md`,
Dashboard-Seite in der Sidebar verlinkt):

| Workflow | Zweck |
|---|---|
| `meeting-summary` | Transkript → Zusammenfassung, Action Items, Follow-up-Mail |
| `research-brief` | Thema → quellenbasiertes Research-Briefing |
| `content-planner` | Themenidee → 1-Wochen-Content-Plan |

**Eigene Workflows hinzufügen** — drei Wege:

1. **Web UI (empfohlen):** Sidebar → `+ Workflow` → Formular ausfüllen. Erstellt Workflow-Dateien +
   Dashboard-Seite + Sidebar-Link sofort, ohne Neustart.
2. **Im Container (CLI):**
   ```bash
   pct exec <CTID> -- python3 /opt/centeros/dashboard/create-dashboard-page.py mein-workflow "Mein Workflow" "Was er tut." --icon bi-lightbulb
   ```
   Dazu `workflows/mein-workflow/CONTEXT.md` + `LOG.md` nach `templates/workflow/`-Schema anlegen.
3. **API:**
   ```bash
   curl -X POST http://<CT-IP>:8080/api/workflows -H 'Content-Type: application/json' \
     -d '{"slug":"mein-workflow","name":"Mein Workflow","description":"Was er tut.","icon":"bi-lightbulb"}'
   ```

Eigene Beispiel-Workflows für alle Neuinstallationen: in diesem Repo unter `app/workflows/<slug>/`
ablegen — der Installer kopiert fehlende Workflows idempotent nach `/opt/centeros/workflows/`
(bestehende werden nie überschrieben).

## Was das Skript tut

1. Prüft Proxmox-Host (`pct`, `pvesh`, `pveam`, root).
2. Nimmt die **nächste freie CT-ID**, lädt ggf. das Debian-12-Template (`pveam download`).
3. Erstellt LXC `centeros` (unprivilegiert, `onboot: 1`, DHCP auf `vmbr0`).
4. Im Container (idempotent): `apt install python3 git curl`, `git clone/pull` nach `/opt/centeros`,
   schreibt `/etc/systemd/system/centeros.service`, `systemctl enable --now`.
5. Verifiziert: `systemctl is-active centeros` + `curl http://localhost:8080/` → gibt finale URL + CT-IP aus.

## Erwartete Ausgabe (Erfolg)

```text
[centeros] INFO: Proxmox-Host erkannt: pve-manager/8.x ...
[centeros] INFO: Nutze CT-ID: 100 (nächste freie ID)
[centeros] INFO: Erstelle LXC CT 100 (hostname=centeros, cpu=1, ram=1024MB, disk=8G, ...) ...
[centeros] INFO: Guest-Setup in CT 100 abgeschlossen.
[centeros] INFO: Verifiziere Installation in CT 100 ...
  systemctl is-active centeros: active
  HTTP-Check http://localhost:8080/ -> 200

==================================================================
 CenterOS erfolgreich installiert!
  Container : CT 100 (hostname: centeros, onboot=1)
  Web UI    : http://192.168.1.100:8080
  Service   : systemctl status centeros (in CT 100)
  Update    : pct exec 100 -- bash -c 'git -C /opt/centeros pull --ff-only && systemctl restart centeros'
  Entfernen : pct stop 100 && pct destroy 100
==================================================================
```

Web UI danach: `http://[LXC-IP]:8080` (bind `0.0.0.0`).

## Update / Deinstall

```bash
# Update (im Container, idempotent)
CTID=100  # anpassen
pct exec $CTID -- bash -c 'git -C /opt/centeros pull --ff-only && systemctl restart centeros'
pct exec $CTID -- systemctl status centeros --no-pager
curl -s -o /dev/null -w '%{http_code}\n' http://$(pct exec $CTID -- hostname -I | awk '{print $1}'):8080/

# Reboot-Test (reboot-sicher: onboot=1 + Restart=always)
pct reboot $CTID
sleep 15
pct exec $CTID -- systemctl is-active centeros
curl -s -o /dev/null -w '%{http_code}\n' http://$(pct exec $CTID -- hostname -I | awk '{print $1}'):8080/

# Deinstallieren
pct stop $CTID && pct destroy $CTID
```

## Debugging

- Voller Trace: `DEBUG=1 bash -x install/centeros.sh` bzw. `DEBUG=1 bash -c "$(wget ...)"`.
- Bei Fehlern gibt das Skript die **komplette Kette** aus: Exit-Code, fehlgeschlagener Befehl,
  Zeile/Funktion, `caller`-Stack, `journalctl`-Auszug vom Host + `systemctl status`/`journalctl -u centeros`
  aus dem Container — niemals nur die letzte Zeile.
- Syntax-Check: `bash -n install/centeros.sh`; Lint: `shellcheck install/centeros.sh`.
