# Developing on an Apple Silicon Mac

The reader's target is Linux x86_64. Containerlab needs a Linux kernel, so on a Mac the whole lab runs inside a Linux
VM. Nothing in the repository depends on OrbStack; it is just the VM used by the author.

## VM

1. OrbStack (or Lima, Multipass, UTM): create an **Ubuntu arm64** VM (24.04 or 26.04) with **12 GB of RAM and 4 CPUs**
   (the author's: 4 CPUs, 11.7 GB; the containers take about 7.5 GB at rest).
2. Inside the VM: Docker Engine (user in the `docker` group), Containerlab, uv, git, curl. The OrbStack Ubuntu image
   ships none of them: `sh install.sh --install-prereqs` installs all five, then log out and in again.
3. Clone the repository inside the VM (not on a macOS mount: Docker volumes and Containerlab binds behave better).
4. cEOS: download the **ARM** build (`cEOSarm-lab-<version>.tar.xz`, EFT) from arista.com into `images/`. `install.sh`
   accepts `cEOS64-lab-*`, `cEOS-lab-*` and `cEOSarm-lab-*`.
5. `sh install.sh`.

Reach Infrahub from macOS through the VM address (OrbStack publishes `http://<vm-name>.orb.local:8000`).

Two traps met on the first run:

- **`orb -m <vm> <command>` forwards the macOS environment into the VM.** A `.zshrc` exporting
  `DOCKER_DEFAULT_PLATFORM=linux/amd64` made Docker pull amd64 images on the arm64 VM and emulate the whole Infrahub
  stack. `install.sh` now unsets the variable; when driving the VM from macOS, prefer `ssh <vm>@orb`, which starts a
  clean login shell.
- **Re-cloning the repository loses `.env`, but the Infrahub volumes keep the tokens of the first run.** Every
  `infrahubctl` call then fails with `Invalid token`. `install.sh` checks the token right after Infrahub answers and
  points to the remedy: `sh uninstall.sh --purge && sh install.sh`.

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

None specific to ARM in the end. cEOSarm-lab 4.36.2F boots in a little over a minute, answers SSH, `show vlan`,
`show running-config`, configuration sessions and `write memory` exactly as the lab expects. The only adjustments were
release-specific, not architecture-specific: the default lines 4.36 prints in `show running-config` (now in the template)
and `aaa authorization exec default local`, without which the admin user lands unprivileged over SSH. Readers on x86_64
with another release should expect the same kind of difference, which `preview_config` shows as a diff.
