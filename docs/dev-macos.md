# Developing on an Apple Silicon Mac

The reader's target is Linux x86_64. Containerlab needs a Linux kernel, so on a Mac the whole lab runs inside a Linux
VM. Nothing in the repository depends on OrbStack; it is just the VM used by the author.

## VM

1. OrbStack (or Lima, Multipass, UTM): create an **Ubuntu 24.04 arm64** VM with **16 GB of RAM and 6 CPUs**. Infrahub
   alone wants 8 GB.
2. Inside the VM: Docker Engine (user in the `docker` group), Containerlab (`bash -c "$(curl -sL https://get.containerlab.dev)"`),
   uv, git, curl.
3. Clone the repository inside the VM (not on a macOS mount: Docker volumes and Containerlab binds behave better).
4. cEOS: download the **ARM** build (`cEOSarm-lab-<version>.tar.xz`, EFT) from arista.com into `images/`. `install.sh`
   accepts `cEOS64-lab-*`, `cEOS-lab-*` and `cEOSarm-lab-*`.
5. `sh install.sh`.

Reach Infrahub from macOS through the VM address (OrbStack publishes `http://<vm-name>.orb.local:8000`).

## Development loop

- Data (`infrahub/objects`, `infrahub/schema`): edit, then `uv run infrahubctl object load infrahub/objects` (or
  `schema load`). No push needed.
- Rendering (`.infrahub.yml`, `infrahub/queries`, `infrahub/templates`): edit, `uv run pytest tests/test_transforms.yml`
  (offline, fixture in `tests/fixtures/eos_leaf`), `uv run infrahubctl render eos_leaf device=leaf1` against the running
  Infrahub, then commit and push to a development branch, set `INFRAHUB_REPO_REF=<branch>` in `.env` (re-register or
  update the repository's `ref` in Infrahub), and `sh scripts/reimport.sh`. A read-only repository never follows pushes
  on its own.
- Switches: `sh drift.sh --reset` redeploys both leafs from `clab/generated`.

## Limits met with the ARM image

To be filled during the first complete run: boot time, missing features, error messages, and the workaround used for
each. Readers on x86_64 should not mistake them for bugs of this repository.
