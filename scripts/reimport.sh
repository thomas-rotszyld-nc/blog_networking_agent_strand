#!/bin/sh
# After a push to the branch Infrahub follows: make the read-only repository import the last commit, then wait for
# the re-rendered startup-configs and refresh clab/generated. Run from the project directory, .env present.
set -e
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
echo "== re-importing the repository in Infrahub"
uv run python -c "from vlanlab.infrahub_api import reimport_repository; reimport_repository()"
echo "== waiting for the rendered startup-configs"
uv run python scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated
