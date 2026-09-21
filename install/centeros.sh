#!/usr/bin/env bash
#
# CenterOS — Proxmox VE Community-Scripts style installer (LXC)
#
# Einzeiler auf dem Proxmox-Host (als root):
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/flatplanet/CenterOS/main/install/centeros.sh)"
#
# Was das Skript tut:
#   1. ermittelt die nächste freie CT-ID (pvesh get /cluster/nextid)
#   2. erstellt einen unprivilegierten Debian-12-LXC namens "centeros"
#      (onboot=1, DHCP auf vmbr0, 1 vCPU / 1 GB RAM / 8 GB Disk per Default)
#   3. installiert im Container: python3, git, curl, ca-certificates
#   4. klont https://github.com/flatplanet/CenterOS nach /opt/centeros (idempotent: git pull bei Re-Run)
#      + Overlay aus HatchetMan111/CentorOS-Proxmox: Beispiel-Workflows,
#        Dashboard-Server (server.py) und "+ Workflow"-Seite
#   5. installiert + aktiviert systemd-Service centeros.service (server.py :8080, bind 0.0.0.0)
#   6. verifiziert: systemctl is-active + HTTP-Check auf localhost:8080, gibt finale URL + CT-IP aus
#
# Debugging: DEBUG=1 bash -x ... für Trace; bei Fehlern wird die komplette
# Fehlermeldungskette (Exit-Code, Befehl, Zeile, Stack, Journal-Auszug) ausgegeben.

set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Variablen (oben, per ENV überschreibbar — Community-Scripts-konform)
# ---------------------------------------------------------------------------
APP="centeros"
APP_NAME="CenterOS"
GH_REPO="flatplanet/CenterOS"          # ohne https://github.com/ Prefix
GH_BRANCH="${GH_BRANCH:-main}"
GITHUB_URL="https://github.com/${GH_REPO}"
RAW_BASE="https://raw.githubusercontent.com/${GH_REPO}/${GH_BRANCH}"
# Overlay: Beispiel-Workflows + Dashboard-Server aus diesem Installer-Repo
OVERLAY_REPO="${OVERLAY_REPO:-HatchetMan111/CentorOS-Proxmox}"
OVERLAY_BRANCH="${OVERLAY_BRANCH:-main}"
OVERLAY_DIR="${OVERLAY_DIR:-/opt/centeros-proxmox}"

CT_HOSTNAME="${CT_HOSTNAME:-centeros}" # LXC-Name (Anforderung: passender Name)
CT_ID="${CT_ID:-}"                     # leer = nächste freie ID automatisch
CT_CPU="${CT_CPU:-1}"                  # vCPU (Spec: 1–2)
CT_RAM="${CT_RAM:-1024}"               # MB (Spec: 1024–2048)
CT_DISK_GB="${CT_DISK_GB:-8}"          # GB rootfs (Spec: 4–8, 8 = sicherer Default)
CT_DISK_STORAGE="${CT_DISK_STORAGE:-${CT_STORAGE:-}}"  # Root-Disk: leer = auto (local-lvm, sonst local)
CT_TEMPLATE_STORAGE="${CT_TEMPLATE_STORAGE:-}"  # Template-Cache (vztmpl): leer = auto (local o. erster vztmpl-Storage)
CT_BRIDGE="${CT_BRIDGE:-vmbr0}"
CT_NET="${CT_NET:-dhcp}"               # "dhcp" oder "static,ip=...,gw=..."
CT_TEMPLATE="${CT_TEMPLATE:-debian-12-standard}"  # pveam-Template-Präfix
CT_UNPRIVILEGED="${CT_UNPRIVILEGED:-1}"
CT_ONBOOT="${CT_ONBOOT:-1}"
CT_PASSWORD="${CT_PASSWORD:-}"         # leer = zufällig generieren (einmalig anzeigen)
CT_TAGS="${CT_TAGS:-centeros}"

INSTALL_DIR="${INSTALL_DIR:-/opt/centeros}"
WEB_PORT="${WEB_PORT:-8080}"
SERVICE_NAME="${SERVICE_NAME:-centeros}"
SERVICE_USER="${SERVICE_USER:-root}"

# ---------------------------------------------------------------------------
# Logging / Fehlerkette
# ---------------------------------------------------------------------------
LOG_PREFIX="[${APP}]"
# Alles Logging geht auf stderr — stdout ist reserviert für Rückgabewerte aus
# $(...)-Aufrufen (ensure_template, next_ctid, pick_*_storage). Sonst landet
# Log-Text in Variablen wie tmpl_storage und pct create scheitert.
info()  { printf '%s INFO: %s\n' "$LOG_PREFIX" "$*" >&2; }
warn()  { printf '%s WARN: %s\n' "$LOG_PREFIX" "$*" >&2; }
error() { printf '%s ERROR: %s\n' "$LOG_PREFIX" "$*" >&2; }

if [[ "${DEBUG:-0}" == "1" ]]; then
  set -x
  info "DEBUG=1 aktiv — bash -x Trace eingeschaltet."
fi

failure() {
  local exit_code=$?
  # Einmal-Guard (Datei statt Variable: feuert sonst doppelt — in Subshell + Parent,
  # z. B. bei tmpl_storage=$(ensure_template ...) — $$ ist in beiden gleich)
  if [[ -f "${FAILURE_MARKER:-}" ]]; then
    exit "$exit_code"
  fi
  [[ -n "${FAILURE_MARKER:-}" ]] && touch "$FAILURE_MARKER"
  local failed_cmd="${BASH_COMMAND:-unbekannt}"
  error "Installation FEHLGESCHLAGEN — komplette Fehlerkette:"
  error "  Exit-Code : ${exit_code}"
  error "  Befehl    : ${failed_cmd}"
  error "  Zeile     : ${BASH_LINENO[0]:-?} (Funktion: ${FUNCNAME[1]:-main})"
  error "  Stacktrace:"
  local i=0 frame
  while frame=$(caller $i 2>/dev/null); do
    error "    #${i} ${frame}"
    i=$((i + 1))
  done
  error "  Relevante Logs (Host, ggf. gekürzt):"
  journalctl --no-pager -p err 2>/dev/null | tail -n 20 >&2 || true
  if [[ -n "${CT_ID_IN_USE:-}" ]]; then
    error "  Container-Logs (CT ${CT_ID_IN_USE}):"
    pct exec "${CT_ID_IN_USE}" -- journalctl -u "${SERVICE_NAME}" --no-pager 2>/dev/null | tail -n 40 >&2 || true
    pct exec "${CT_ID_IN_USE}" -- systemctl status "${SERVICE_NAME}" --no-pager 2>/dev/null >&2 || true
  fi
  error "  Repro: DEBUG=1 bash -x install/${APP}.sh  (vollständiger Trace)"
  exit "$exit_code"
}
trap failure ERR

check_host() {
  if [[ "${EUID}" -ne 0 ]]; then
    error "Bitte als root auf dem Proxmox-Host ausführen."
    exit 1
  fi
  for bin in pct pvesh pveam; do
    if ! command -v "$bin" >/dev/null 2>&1; then
      error "Befehl '$bin' nicht gefunden — bist du sicher, dass das ein Proxmox-VE-Host ist?"
      error "stdout/stderr: $(command -v pct || echo 'pct fehlt'); pveversion: $(pveversion 2>&1 || echo 'pveversion fehlt')"
      exit 1
    fi
  done
  info "Proxmox-Host erkannt: $(pveversion | head -n1)"
}

next_ctid() {
  if [[ -n "$CT_ID" ]]; then
    if pct status "$CT_ID" >/dev/null 2>&1 || qm status "$CT_ID" >/dev/null 2>&1; then
      error "CT_ID=${CT_ID} ist bereits belegt (pct/qm status erfolgreich). Freie ID wählen oder CT_ID leer lassen."
      exit 1
    fi
    echo "$CT_ID"
  else
    # Immer die nächste freie ID nehmen (Anforderung)
    pvesh get /cluster/nextid
  fi
}

# Templates (vztmpl) brauchen File-Storage (z. B. local) — NIEMALS local-lvm.
# Die Root-Disk dagegen bevorzugt local-lvm. Darum zwei getrennte Storages.
pick_template_storage() {
  if [[ -n "$CT_TEMPLATE_STORAGE" ]]; then
    echo "$CT_TEMPLATE_STORAGE"
    return
  fi
  local list s
  list=$(pvesm status --content vztmpl 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}' || true)
  for s in $list; do
    if [[ "$s" == "local" ]]; then
      echo "local"
      return
    fi
  done
  s=$(echo "$list" | head -n1)
  if [[ -z "$s" ]]; then
    error "Kein Storage mit Content-Typ 'vztmpl' gefunden. pvesm status:"
    pvesm status >&2 || true
    exit 1
  fi
  echo "$s"
}

pick_disk_storage() {
  if [[ -n "$CT_DISK_STORAGE" ]]; then
    echo "$CT_DISK_STORAGE"
    return
  fi
  if pvesm status --storage local-lvm >/dev/null 2>&1; then
    echo "local-lvm"
    return
  fi
  local s
  s=$(pvesm status --content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}' || true)
  echo "${s:-local}"
}

ensure_template() {
  local prefix="$1" storage tmpl tstorage
  tstorage=$(pick_template_storage)
  # Template-Cache aktualisieren (idempotent, Fehler tolerieren bei Offline-Mirror)
  pveam update >/dev/null 2>&1 || warn "pveam update fehlgeschlagen — nutze vorhandenen Cache."
  tmpl=$(pveam available --section system 2>/dev/null | grep -E "$prefix" | awk '{print $2}' | sort -V | tail -n1 || true)
  if [[ -z "$tmpl" ]]; then
    # Fallback: bereits heruntergeladene Templates auf dem Template-Storage
    tmpl=$(pveam list "$tstorage" 2>/dev/null | grep -E "$prefix" | awk '{print $1}' | sort -V | tail -n1 || true)
  fi
  if [[ -z "$tmpl" ]]; then
    error "Kein LXC-Template für Präfix '$prefix' gefunden. Verfügbare System-Templates:"
    pveam available --section system 2>&1 | head -n 20 >&2 || true
    exit 1
  fi
  storage="$tstorage"
  if ! pveam list "$storage" 2>/dev/null | grep -qF "$tmpl"; then
    info "Lade Template ${tmpl} nach ${storage} ..."
    pveam download "$storage" "$tmpl"
  else
    info "Template ${tmpl} bereits in ${storage} vorhanden."
  fi
  # pct create braucht das Format STORAGE:vztmpl/DATEI (wie `pveam list` es zeigt)
  printf '%s:vztmpl/%s' "$storage" "$tmpl"
}

create_container() {
  local ctid="$1" tmpl_storage="$2" storage password netconf
  CT_ID_IN_USE="$ctid"
  storage=$(pick_disk_storage)
  if [[ -z "$CT_PASSWORD" ]]; then
    password=$(openssl rand -base64 12 | tr -d '/+=' | head -c 16)
    PASSWORD_GENERATED=1
  else
    password="$CT_PASSWORD"
    PASSWORD_GENERATED=0
  fi
  if [[ "$CT_NET" == "dhcp" ]]; then
    netconf="name=eth0,bridge=${CT_BRIDGE},ip=dhcp"
  else
    netconf="name=eth0,bridge=${CT_BRIDGE},${CT_NET}"
  fi
  info "Erstelle LXC CT ${ctid} (hostname=${CT_HOSTNAME}, cpu=${CT_CPU}, ram=${CT_RAM}MB, disk=${CT_DISK_GB}G, storage=${storage}, template=${tmpl_storage}) ..."
  pct create "$ctid" "$tmpl_storage" \
    --hostname "$CT_HOSTNAME" \
    --cores "$CT_CPU" \
    --memory "$CT_RAM" \
    --swap 512 \
    --rootfs "${storage}:${CT_DISK_GB}" \
    --net0 "$netconf" \
    --unprivileged "$CT_UNPRIVILEGED" \
    --features nesting=1 \
    --onboot "$CT_ONBOOT" \
    --tags "$CT_TAGS" \
    --password "$password" \
    --start 0
  # onboot explizit sicherstellen (reboot-sicher, Anforderung)
  pct set "$ctid" --onboot "$CT_ONBOOT"
  info "Container CT ${ctid} erstellt."
  if [[ "$PASSWORD_GENERATED" == "1" ]]; then
    info "Zufälliges Root-Passwort (einmalig): ${password}"
  fi
  info "Starte CT ${ctid} ..."
  pct start "$ctid"
  # Warten bis pct exec funktioniert (Container-Init)
  local tries=0
  until pct exec "$ctid" -- true 2>/dev/null; do
    tries=$((tries + 1))
    if ((tries > 30)); then
      error "CT ${ctid} reagiert nach 60s nicht auf 'pct exec'. pct status:"
      pct status "$ctid" >&2 || true
      exit 1
    fi
    sleep 2
  done
  info "CT ${ctid} läuft."
}

# Setup INSIDE the container — idempotent, eigener Error-Kontext
container_setup() {
  local ctid="$1"
  info "Installiere Abhängigkeiten + App in CT ${ctid} (idempotent) ..."
  pct exec "$ctid" -- bash -s <<EOF
set -Eeuo pipefail
trap 'ec=\$?; echo "[centeros-guest] ERROR: Exit=\$ec Befehl=\$BASH_COMMAND Zeile=\${BASH_LINENO[0]}" >&2; exit \$ec' ERR
export DEBIAN_FRONTEND=noninteractive
echo "[centeros-guest] INFO: apt update + Basis-Pakete ..."
apt-get update
apt-get install -y --no-install-recommends python3 git curl ca-certificates procps iproute2
echo "[centeros-guest] INFO: App-Checkout ${GITHUB_URL} -> ${INSTALL_DIR} ..."
if [[ -d "${INSTALL_DIR}/.git" ]]; then
  git -C "${INSTALL_DIR}" fetch --all
  git -C "${INSTALL_DIR}" checkout "${GH_BRANCH}"
  git -C "${INSTALL_DIR}" pull --ff-only || git -C "${INSTALL_DIR}" reset --hard "origin/${GH_BRANCH}"
else
  rm -rf "${INSTALL_DIR}"
  git clone --depth 1 --branch "${GH_BRANCH}" "${GITHUB_URL}.git" "${INSTALL_DIR}"
fi
if [[ ! -f "${INSTALL_DIR}/dashboard/index.html" ]]; then
  echo "[centeros-guest] ERROR: ${INSTALL_DIR}/dashboard/index.html fehlt — Branch/Repo prüfen." >&2
  ls -la "${INSTALL_DIR}" >&2 || true
  exit 1
fi
echo "[centeros-guest] INFO: Overlay-Checkout https://github.com/${OVERLAY_REPO} -> ${OVERLAY_DIR} ..."
if [[ -d "${OVERLAY_DIR}/.git" ]]; then
  git -C "${OVERLAY_DIR}" fetch --all
  git -C "${OVERLAY_DIR}" checkout "${OVERLAY_BRANCH}"
  git -C "${OVERLAY_DIR}" pull --ff-only || git -C "${OVERLAY_DIR}" reset --hard "origin/${OVERLAY_BRANCH}"
else
  rm -rf "${OVERLAY_DIR}"
  git clone --depth 1 --branch "${OVERLAY_BRANCH}" "https://github.com/${OVERLAY_REPO}.git" "${OVERLAY_DIR}"
fi
echo "[centeros-guest] INFO: Beispiel-Workflows + Server deployen ..."
cp -f "${OVERLAY_DIR}/app/server.py" "${INSTALL_DIR}/server.py"
chmod +x "${INSTALL_DIR}/server.py"
for d in "${OVERLAY_DIR}"/app/workflows/*/; do
  slug=$(basename "$d")
  if [[ ! -e "${INSTALL_DIR}/workflows/${slug}" ]]; then
    cp -r "$d" "${INSTALL_DIR}/workflows/${slug}"
    echo "[centeros-guest] INFO: Beispiel-Workflow installiert: ${slug}"
  else
    echo "[centeros-guest] INFO: Workflow existiert bereits, übersprungen: ${slug}"
  fi
done
python3 "${OVERLAY_DIR}/app/patch-dashboard.py" --root "${INSTALL_DIR}" --overlay "${OVERLAY_DIR}/app"
echo "[centeros-guest] INFO: Dashboard-Seiten für Beispiel-Workflows erzeugen ..."
python3 "${INSTALL_DIR}/dashboard/create-dashboard-page.py" meeting-summary "Meeting Summary" "Turns transcripts into summaries and action items." --icon bi-mic --force
python3 "${INSTALL_DIR}/dashboard/create-dashboard-page.py" research-brief "Research Brief" "Turns a topic into a source-grounded research brief." --icon bi-search --force
python3 "${INSTALL_DIR}/dashboard/create-dashboard-page.py" content-planner "Content Planner" "Turns one topic idea into a one-week content plan." --icon bi-calendar3 --force
echo "[centeros-guest] INFO: systemd-Unit ${SERVICE_NAME}.service schreiben ..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<UNIT
[Unit]
Description=${APP_NAME} Dashboard (Proxmox LXC)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/server.py --root ${INSTALL_DIR} --port ${WEB_PORT} --bind 0.0.0.0
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"
echo "[centeros-guest] INFO: Guest-Setup fertig."
EOF
  info "Guest-Setup in CT ${ctid} abgeschlossen."
}

verify_installation() {
  local ctid="$1" ip svc_state http_code
  info "Verifiziere Installation in CT ${ctid} ..."
  svc_state=$(pct exec "$ctid" -- systemctl is-active "$SERVICE_NAME" 2>&1)
  echo "  systemctl is-active ${SERVICE_NAME}: ${svc_state}"
  if [[ "$svc_state" != "active" ]]; then
    error "Service ${SERVICE_NAME} ist nicht active. Status:"
    pct exec "$ctid" -- systemctl status "$SERVICE_NAME" --no-pager >&2 || true
    pct exec "$ctid" -- journalctl -u "$SERVICE_NAME" --no-pager -n 50 >&2 || true
    exit 1
  fi
  http_code=$(pct exec "$ctid" -- curl -s -o /dev/null -w '%{http_code}' "http://localhost:${WEB_PORT}/" 2>&1)
  echo "  HTTP-Check http://localhost:${WEB_PORT}/ -> ${http_code}"
  if [[ "$http_code" != "200" ]]; then
    error "Web UI antwortet nicht mit 200 (got: ${http_code}). curl -v:"
    pct exec "$ctid" -- curl -v "http://localhost:${WEB_PORT}/" >&2 || true
    exit 1
  fi
  api_body=$(pct exec "$ctid" -- curl -s "http://localhost:${WEB_PORT}/api/workflows" 2>&1)
  echo "  API-Check http://localhost:${WEB_PORT}/api/workflows -> ${api_body}"
  if ! printf '%s' "$api_body" | grep -q "meeting-summary"; then
    error "Workflow-API liefert keine Beispiel-Workflows. server.py-Logs:"
    pct exec "$ctid" -- journalctl -u "$SERVICE_NAME" --no-pager -n 30 >&2 || true
    exit 1
  fi
  ip=$(pct exec "$ctid" -- hostname -I 2>/dev/null | awk '{print $1}')
  echo ""
  echo "=================================================================="
  echo " ${APP_NAME} erfolgreich installiert!"
  echo "  Container : CT ${ctid} (hostname: ${CT_HOSTNAME}, onboot=1)"
  echo "  Web UI    : http://${ip:-<CT-IP>}:${WEB_PORT}"
  echo "  Workflows : 3 Beispiele vorinstalliert (meeting-summary, research-brief, content-planner)"
  echo "  +Workflow : Sidebar-Eintrag '+ Workflow' im Dashboard für eigene Workflows"
  echo "  Service   : systemctl status ${SERVICE_NAME} (in CT ${ctid})"
  echo "  Update    : pct exec ${ctid} -- bash -c 'git -C ${INSTALL_DIR} pull --ff-only && systemctl restart ${SERVICE_NAME}'"
  echo "  Entfernen : pct stop ${ctid} && pct destroy ${ctid}"
  echo "=================================================================="
}

main() {
  FAILURE_MARKER="/tmp/.centeros-install-failed-$$"
  rm -f "$FAILURE_MARKER"
  check_host
  local ctid tmpl_storage
  ctid=$(next_ctid)
  info "Nutze CT-ID: ${ctid} (nächste freie ID)"
  info "Hostname   : ${CT_HOSTNAME}"
  tmpl_storage=$(ensure_template "$CT_TEMPLATE")
  create_container "$ctid" "$tmpl_storage"
  container_setup "$ctid"
  verify_installation "$ctid"
  rm -f "$FAILURE_MARKER"
}

main "$@"
