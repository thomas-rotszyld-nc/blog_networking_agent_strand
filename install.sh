#!/bin/sh
# One-shot installation of the lab: Infrahub (schema, data, this repository registered read-only, rendered
# startup-configs), netmiko-mcp, two cEOS leafs under Containerlab booting from those startup-configs, and the agent.
# Idempotent: safe to run again.
#
#   sh install.sh                   # everything, with checks at the end
#   sh install.sh --check-prereqs   # only step 0
#   sh install.sh --install-prereqs # Ubuntu/Debian only: install Docker, Containerlab, uv, git and curl (sudo), then exit
#
# Requires: Docker + Compose v2 usable without sudo, containerlab, uv, git, curl, an Arista cEOS-lab archive in images/,
# 16 GB of RAM. `sudo` is used for containerlab only. Run from the project directory.
set -e
cd "$(dirname "$0")"
unset DOCKER_DEFAULT_PLATFORM   # the lab runs native; a shell exporting linux/amd64 (common on Macs) would make Docker emulate everything
REPO_URL_DEFAULT=https://github.com/thomas-rotszyld-nc/blog_networking_agent_strand
INFRAHUB_COMPOSE_URL=https://infrahub.opsmill.io/1.11.9
INFRAHUB_ADDR=http://localhost:8000
step() { printf '\n== %s\n' "$*"; }
fail() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--install-prereqs" ]; then
  # Opt-in, because it runs the official install scripts of Docker and Containerlab with sudo.
  [ -r /etc/os-release ] && . /etc/os-release   # a missing file would abort a POSIX sh under set -e if sourced directly
  case " ${ID:-} ${ID_LIKE:-} " in
    *ubuntu*|*debian*) ;;
    *) fail "--install-prereqs only knows Ubuntu and Debian; install Docker, Containerlab, uv, git and curl by hand (see the [KO] lines of: sh install.sh --check-prereqs)" ;;
  esac
  step "installing the prerequisites (${PRETTY_NAME:-Debian family}, sudo)"
  export DEBIAN_FRONTEND=noninteractive
  sudo apt-get update -qq && sudo apt-get install -y -qq git curl ca-certificates
  if command -v docker >/dev/null 2>&1; then echo "  docker already installed"; else
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh && sudo sh /tmp/get-docker.sh
  fi
  sudo usermod -aG docker "$(id -un)"
  if command -v containerlab >/dev/null 2>&1; then echo "  containerlab already installed"; else
    curl -sL https://get.containerlab.dev | sudo bash
  fi
  if command -v uv >/dev/null 2>&1; then echo "  uv already installed"; else
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  printf '\nPrerequisites installed. Log out and in again (docker group), check that ~/.local/bin is in your PATH (uv),\nput the cEOS archive in images/, then: sh install.sh\n'
  exit 0
fi

step "0/9 prerequisites"
MISSING=0
need() { if command -v "$1" >/dev/null 2>&1; then echo "  [ok] $1"; else echo "  [KO] $1 missing: $2"; MISSING=1; fi; }
need docker "install Docker Engine (https://docs.docker.com/engine/install/)"
need containerlab 'install Containerlab: bash -c "$(curl -sL https://get.containerlab.dev)"'
need uv "install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
need git "install git"
need curl "install curl"
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then echo "  [ok] docker usable without sudo"; else echo "  [KO] docker needs sudo: add your user to the docker group (sudo usermod -aG docker \$USER) and log in again"; MISSING=1; fi
  if docker compose version >/dev/null 2>&1; then echo "  [ok] docker compose v2"; else echo "  [KO] docker compose v2 missing"; MISSING=1; fi
fi
ARCHIVES=$(ls images/cEOS64-lab-*.tar* images/cEOS-lab-*.tar* images/cEOSarm-lab-*.tar* 2>/dev/null || true)
ARCHIVE=""
if [ -z "$ARCHIVES" ]; then
  echo "  [KO] no cEOS archive in images/: download cEOS64-lab-<version>.tar.xz from https://www.arista.com/en/support/software-download (free account, section cEOS-lab) and put it in images/"
  MISSING=1
else
  ARCHIVE=$(echo "$ARCHIVES" | sort | tail -1)
  N=$(echo "$ARCHIVES" | wc -l | tr -d ' ')
  [ "$N" -gt 1 ] && echo "  [..] several archives in images/, using the last one: $ARCHIVE" || echo "  [ok] cEOS archive: $ARCHIVE"
fi
MEM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || true)
if [ -n "$MEM_KB" ] && [ "$MEM_KB" -lt 15000000 ]; then echo "  [..] less than 16 GB of RAM: Infrahub alone wants 8 GB, expect swapping"; fi
[ "$MISSING" -eq 0 ] || fail "at least one prerequisite is missing: see the [KO] lines above (Ubuntu/Debian: sh install.sh --install-prereqs installs the tools)"
[ "${1:-}" = "--check-prereqs" ] && { echo "prerequisites ok"; exit 0; }

step "1/9 .env (tokens and secrets kept across runs)"
getenv() { grep "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true; }
uuid() { uv run python -c "import uuid; print(uuid.uuid4())"; }
ADMIN_TOKEN=$(getenv INFRAHUB_INITIAL_ADMIN_TOKEN); [ -n "$ADMIN_TOKEN" ] || { ADMIN_TOKEN=$(uuid); echo "  generated the Infrahub admin token"; }
AGENT_TOKEN=$(getenv INFRAHUB_INITIAL_AGENT_TOKEN); [ -n "$AGENT_TOKEN" ] || AGENT_TOKEN=$(uuid)
SECRET_KEY=$(getenv INFRAHUB_SECURITY_SECRET_KEY); [ -n "$SECRET_KEY" ] || SECRET_KEY=$(uv run python -c "import secrets; print(secrets.token_urlsafe(48))")
REPO_URL=$(getenv INFRAHUB_REPO_URL); [ -n "$REPO_URL" ] || REPO_URL=$REPO_URL_DEFAULT
REPO_REF=$(getenv INFRAHUB_REPO_REF); [ -n "$REPO_REF" ] || REPO_REF=main
ANTHROPIC_KEY=$(getenv ANTHROPIC_API_KEY)
cat > .env <<ENV
# Written by install.sh; not committed. Re-runs keep these values.
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
INFRAHUB_ADDRESS=$INFRAHUB_ADDR
INFRAHUB_API_TOKEN=$ADMIN_TOKEN
INFRAHUB_INITIAL_ADMIN_TOKEN=$ADMIN_TOKEN
INFRAHUB_INITIAL_AGENT_TOKEN=$AGENT_TOKEN
INFRAHUB_SECURITY_SECRET_KEY=$SECRET_KEY
INFRAHUB_REPO_URL=$REPO_URL
INFRAHUB_REPO_REF=$REPO_REF
ENV
mkdir -p infrahub
cat > infrahub/.env <<ENV
# Written by install.sh; not committed. The only variables the Infrahub containers receive: the lab .env holds
# INFRAHUB_ADDRESS and others that the compose file would pass through to the servers.
INFRAHUB_INITIAL_ADMIN_TOKEN=$ADMIN_TOKEN
INFRAHUB_INITIAL_AGENT_TOKEN=$AGENT_TOKEN
INFRAHUB_SECURITY_SECRET_KEY=$SECRET_KEY
ENV
echo "  .env written (repository $REPO_URL @ $REPO_REF)"

step "2/9 Infrahub 1.11.9 (first start: several minutes)"
[ -f infrahub/docker-compose.yml ] || curl -sfL "$INFRAHUB_COMPOSE_URL" -o infrahub/docker-compose.yml
docker compose -p vlan-lab -f infrahub/docker-compose.yml --env-file infrahub/.env up -d
i=0
until curl -sf "$INFRAHUB_ADDR/api/config" >/dev/null 2>&1; do
  i=$((i + 1)); [ $i -gt 90 ] && fail "Infrahub did not answer after 15 minutes: docker compose -p vlan-lab -f infrahub/docker-compose.yml logs infrahub-server"
  sleep 10
done
echo "  Infrahub answers at $INFRAHUB_ADDR"
set -a; . ./.env; set +a   # only now: the lab variables are for infrahubctl, the agent and the MCP servers
uv sync -q
uv run infrahubctl info >/dev/null 2>&1 || fail "Infrahub refuses the token of .env. Its database was initialised by an earlier run with another .env (the data volumes outlive the file): either restore that .env, or start Infrahub again from scratch with: sh uninstall.sh --purge && sh install.sh"
echo "  token accepted"

step "3/9 schema (schema-library copies in infrahub/schema)"
uv run infrahubctl schema load infrahub/schema --wait 60

step "4/9 data (infrahub/objects)"
uv run infrahubctl object load infrahub/objects

step "5/9 this repository, registered read-only, and the rendered startup-configs"
if uv run infrahubctl repository list 2>/dev/null | grep -q "blog-lab"; then
  echo "  repository blog-lab already registered"
else
  uv run infrahubctl repository add blog-lab "$REPO_URL" --read-only --ref "$REPO_REF"
  echo "  repository blog-lab registered ($REPO_URL @ $REPO_REF)"
fi
uv run python scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated --timeout 600

step "6/9 netmiko-mcp (read-only, allowed commands: show vlan, show running-config)"
# netmiko-mcp 0.2.0 targets mcp 1.x (mcp.server.fastmcp); mcp<2 pins the same environment .mcp.json launches with uvx
uvx --from netmiko-mcp==0.2.0 --with 'mcp<2' python -c "import netmiko_mcp.server" && echo "  netmiko-mcp 0.2.0 environment ready"
NETMIKO_DIR=$PWD/netmiko
cat > netmiko/netmiko-mcp.yml <<YML
inventory_type: netmiko_tools
inventory_file: $NETMIKO_DIR/.netmiko.yml
command_file: $NETMIKO_DIR/commands.yml
audit_log_file: $NETMIKO_DIR/audit.log
YML
cat > netmiko/.netmiko.yml <<YML
# Lab inventory, Netmiko Tools format; shared by netmiko-mcp and the agent's own tools (vlanlab/eos.py).
leaf1:
  device_type: arista_eos
  host: 172.20.20.11
  username: admin
  password: admin
leaf2:
  device_type: arista_eos
  host: 172.20.20.12
  username: admin
  password: admin
leafs:
  - leaf1
  - leaf2
YML
cat > netmiko/commands.yml <<YML
# What the model may send through netmiko-mcp. Everything else is refused by the server.
allowed_commands:
  - "show vlan*"
  - "show running-config*"
denied_commands: []
YML
echo "  netmiko/ configured"

step "7/9 Containerlab: two cEOS leafs booting from clab/generated"
docker image inspect ceos:lab >/dev/null 2>&1 || { echo "  importing $ARCHIVE as ceos:lab"; docker import "$ARCHIVE" ceos:lab >/dev/null; }
sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure
uv run python scripts/wait_leafs.py --timeout 300

step "8/9 the agent"
# the MCP servers chat on stderr while starting; kept in a file, shown only if the check fails
uv run python agent.py --list-tools > /tmp/vlan-lab-tools.txt 2> /tmp/vlan-lab-agent.err || { tail -40 /tmp/vlan-lab-agent.err; fail "the agent could not start (see above)"; }
for t in render_configs preview_config deploy_config send_show_command get_nodes node_upsert propose_changes; do
  grep -qx "$t" /tmp/vlan-lab-tools.txt || { tail -40 /tmp/vlan-lab-agent.err; fail "tool $t not listed by the agent (see uv run python agent.py --list-tools)"; }
done
echo "  $(wc -l < /tmp/vlan-lab-tools.txt | tr -d ' ') tools available"

step "9/9 checks"
KO=0
check() { if [ "$2" = "0" ]; then echo "  [ok] $1"; else echo "  [KO] $1"; KO=1; fi; }
# every check runs under `|| rc=1` so that `set -e` lets all of them print before the final verdict
rc=0; uv run python - <<'PYCHECK' || rc=1
import sys
from vlanlab.infrahub_api import client
vlans = client().filters(kind="IpamVLAN")
print(f"  {len(vlans)} VLANs in Infrahub")
sys.exit(0 if len(vlans) >= 3 else 1)   # at least the three of the seed: the demo adds VLAN 40, re-runs must pass
PYCHECK
check "at least the three seeded VLANs in Infrahub" $rc
rc=0; { [ -s clab/generated/leaf1.cfg ] && [ -s clab/generated/leaf2.cfg ]; } || rc=1
check "two rendered startup-configs" $rc
for d in leaf1 leaf2; do
  rc=0; uv run python -c "
from vlanlab.eos import load_inventory, running_config
import sys
out = running_config(load_inventory()['$d'])
sys.exit(0 if all(n in out for n in ('USERS', 'VOICE', 'IOT')) else 1)" || rc=1
  check "$d running-config has the three VLANs" $rc
  rc=0; uv run python -c "
from vlanlab.infrahub_tools import preview_config
import sys
out = preview_config(device='$d'); print('    ' + out.splitlines()[0])
sys.exit(0 if 'no difference' in out else 1)" || rc=1
  check "$d: rendered == running" $rc
done
[ "$KO" -eq 0 ] || fail "at least one check failed: see the [KO] lines above"

printf '\nLab ready.\n  Infrahub: %s (admin / infrahub)\n  Agent:    uv run python agent.py\n' "$INFRAHUB_ADDR"
[ -n "${ANTHROPIC_API_KEY:-}" ] || printf '  Before running the agent: export ANTHROPIC_API_KEY=... in your shell (or put it in .env).\n'
