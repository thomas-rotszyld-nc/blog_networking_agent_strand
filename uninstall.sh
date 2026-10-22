#!/bin/sh
# Stops the lab: destroys the Containerlab topology and stops Infrahub. `--purge` also deletes Infrahub's data.
# Keeps: the cEOS image, .env, clab/generated, netmiko/.
set -e
cd "$(dirname "$0")"
echo "== destroying the Containerlab topology"
sudo containerlab destroy -t clab/vlan-lab.clab.yml --cleanup 2>/dev/null || echo "  (no topology deployed)"
if [ -f infrahub/docker-compose.yml ]; then
  echo "== stopping Infrahub"
  if [ "${1:-}" = "--purge" ]; then
    docker compose -p vlan-lab -f infrahub/docker-compose.yml down -v
  else
    docker compose -p vlan-lab -f infrahub/docker-compose.yml down
  fi
fi
echo "kept: ceos:lab image, .env, clab/generated/, netmiko/  (re-run sh install.sh to start again)"
