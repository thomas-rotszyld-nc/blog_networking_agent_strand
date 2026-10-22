#!/bin/sh
# Introduces a manual change on leaf2, the way a hurried engineer would: VLAN 20 renamed to VOIP, and a VLAN 99
# LEGACY that Infrahub does not know. Then prints `show vlan` of both leafs. Idempotent: run it as often as you like.
#
#   sh drift.sh          # drift leaf2
#   sh drift.sh --reset  # redeploy both leafs from the startup-configs Infrahub rendered (clab/generated), wait for SSH
set -e
cd "$(dirname "$0")"
cli() { docker exec "clab-vlan-lab-$1" Cli -p 15 -c "$2"; }
show() { for d in leaf1 leaf2; do printf '\n== %s\n' "$d"; cli "$d" "show vlan"; done; }

if [ "${1:-}" = "--reset" ]; then
  set -a; . ./.env; set +a
  echo "== refreshing clab/generated from Infrahub's current renderings"
  uv run python scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated
  echo "== redeploying the leafs from clab/generated"
  sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure
  uv run python scripts/wait_leafs.py --timeout 300
  show
  exit 0
fi

echo "== drifting leaf2 by hand"
cli leaf2 "configure
vlan 20
   name VOIP
vlan 99
   name LEGACY
end
write"
show
printf '\nleaf2 no longer matches Infrahub. Ask the agent: "Is leaf2 still compliant?" then "Fix it."\n'
