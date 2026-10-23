# Infrahub intent-to-deploy lab

A Strands agent sits between [Infrahub](https://github.com/opsmill/infrahub) and two Arista cEOS switches running under
Containerlab. You ask it to change the intent; Infrahub renders the switch configurations; a human reviews and merges;
the agent deploys what Infrahub rendered and verifies. Companion repository of a blog article on Strands Agents
(link to come).

**The loop the article follows: intent → review → render → deploy → verify.**

| Act | You ask | What happens |
|-----|---------|--------------|
| 1 | *Add VLAN 40 GUESTS to site lab and put Ethernet3 of both leafs on it.* | The agent writes in Infrahub through the official `infrahub-mcp` server, on a session branch, and opens a Proposed Change. You review the data diff and the rendered configuration diff in Infrahub, and merge. |
| 2 | *Deploy the configuration of the leafs.* | The agent diffs Infrahub's rendering against each switch (`preview_config`), you confirm on the terminal, it replaces the running configuration (`deploy_config`). Guards in code refuse an unsafe rendering or too many switches per turn. |
| 3 | *Check the VLANs on both leafs.* then `sh drift.sh`, *Is leaf2 still compliant? Fix it.* | `show vlan` through the official, read-only `netmiko-mcp` server. After a manual change on leaf2, the preview shows the drift and the same deployment fixes it. |

## Prerequisites

- Linux x86_64 (Ubuntu 22.04 or 24.04), **16 GB of RAM** and 6 cores: the Infrahub Compose stack wants 8 GB on its own,
  plus two cEOS containers.
- Docker Engine with Compose v2, usable without `sudo` (your user in the `docker` group).
- [Containerlab](https://containerlab.dev/install/), [uv](https://docs.astral.sh/uv/), `git`, `curl`.
- An Arista account to download **cEOS-lab** (`cEOS64-lab-<version>.tar.xz`) from
  [arista.com](https://www.arista.com/en/support/software-download). Put the archive in `images/`.
- An `ANTHROPIC_API_KEY` for the agent.

On Ubuntu or Debian, `sh install.sh --install-prereqs` installs Docker (official `get.docker.com` script), Containerlab
(`get.containerlab.dev`), uv, git and curl, with `sudo`, and adds you to the `docker` group: log out and in again
afterwards. It is opt-in because it runs downloaded scripts as root; on another distribution, install them by hand.

## Install

```sh
git clone https://github.com/thomas-rotszyld-nc/blog_networking_agent_strand.git
cd blog_networking_agent_strand
cp /path/to/cEOS64-lab-*.tar.xz images/
sh install.sh            # sh install.sh --check-prereqs to only check the prerequisites
```

`install.sh` is idempotent and does, in order: write `.env` (generated secrets, kept across runs), start Infrahub
1.11.9 with its official Compose file, load the schema (copies from OpsMill's schema-library) and the lab data, register
this repository in Infrahub as a read-only Git repository and wait for the two rendered startup-configs, configure
`netmiko-mcp`, import the cEOS image and deploy the Containerlab topology from those startup-configs, check that the
agent sees all its tools, and run end-to-end checks (the last one: each switch's running configuration equals Infrahub's
rendering). First run: several minutes for Infrahub, one to two for cEOS (exact durations to be measured, see the
tested-on note below). Then put your key in `.env` (`ANTHROPIC_API_KEY=...`).

## Run the demo

```sh
uv run python agent.py
you> Add VLAN 40 GUESTS to site lab and put Ethernet3 of both leafs on it.
```

The terminal prints `[infrahub: …]` lines with the session branch and the link of the Proposed Change. Open it in
Infrahub (`http://localhost:8000`, admin / infrahub), look at the data diff and the artifact diff, merge. Infrahub
re-renders the two startup-configs after the merge; `uv run python scripts/wait_artifacts.py leaf1 leaf2 --until-changed`
waits for them (otherwise the agent may see "no difference" for a moment). Then:

```text
you> Deploy the configuration of the leafs.
you> Check the VLANs on both leafs.
```

Drift and remediation:

```sh
sh drift.sh              # renames VLAN 20 to VOIP and adds VLAN 99 LEGACY on leaf2, by hand
uv run python agent.py "Is leaf2 still compliant?"
uv run python agent.py "Fix leaf2."
sh drift.sh --reset      # redeploys both leafs from Infrahub's renderings
```

## How it works, in reading order

- **`.infrahub.yml`, `infrahub/queries/leaf_config.gql`, `infrahub/templates/eos_leaf.j2`**: what Infrahub reads when
  it clones this repository. One GraphQL query (a device, its site's VLANs, its interfaces and their access VLAN), one
  Jinja2 template rendering the complete EOS startup-config of a leaf, one artifact definition targeting the `leafs`
  group. What moves comes from the data; the fixed base of every leaf lives in the template. The template is tested
  offline with the SDK's testing framework (`tests/test_transforms.yml`, fixtures in `tests/fixtures/eos_leaf`).
- **`infrahub/schema/`**: unmodified copies of `opsmill/schema-library` (base dcim, ipam, location, organization;
  extensions `location_site` and `vlan`) at commit `26336e90…`, Apache-2.0. **`infrahub/objects/`**: the lab data as
  Infrahub object files (site, VLAN group, three VLANs, two leafs with their interfaces and management addresses, the
  `leafs` group). Loaded by `infrahubctl`, not through the Git repository, so the data loop never waits for a push.
- **`agent.py`**: the Strands agent. Model, the two MCP servers of `.mcp.json`, the two local tools, hooks, steering
  and skills, plus the terminal chat loop.
- **`vlanlab/infrahub_tools.py`**: `preview_config` and `deploy_config`, Strands `@tool`s that fetch the artifact from
  Infrahub and compare it with, or apply it to, the switch. They take no configuration text. `ShowInfrahubLinks`
  prints the branch and links after each Infrahub write.
- **`vlanlab/guards.py`**: `DeployGuard`, a steering handler that refuses a missing or unsafe rendering (wrong hostname,
  no management block with the known address, no admin user) and caps deployments at two switches per turn; the reason
  goes back to the model. `ConfirmDeploy`, a hook that runs after the steering and asks you on the terminal, diff shown.
- **`vlanlab/eos.py`**: Netmiko. Inventory shared with `netmiko-mcp`, `show running-config`, and the all-or-nothing
  replacement through an EOS configuration session (`rollback clean-config`, paste, `commit`, `write memory`; the
  session is aborted if EOS rejects a single line).
- **`vlanlab/infrahub_api.py`**: reading artifacts with the Infrahub SDK, waiting for them to be ready, and asking a
  read-only repository to import its last commit.
- **`skills/`**: `infrahub-change`, `deploy-config`, `vlan-check`, the procedures the agent follows.
- **`clab/vlan-lab.clab.yml`**: the topology. Two cEOS leafs, three links between them so that Ethernet1 to Ethernet3
  exist, an IPv4-only management network (172.20.20.11 and .12), each leaf booting from the startup-config Infrahub
  rendered into `clab/generated/`. **`scripts/`**: `wait_artifacts.py` (wait for and download the renderings),
  `wait_leafs.py` (wait for SSH on the leafs), `reimport.sh` (re-import the repository after a push).

## Why these choices

**Infrahub writes go through a branch and a Proposed Change.** `infrahub-mcp` creates a session branch on the agent's
first write and never touches the default branch; `propose_changes` opens the review. The branch is the safety net, so
the agent asks for no confirmation before writing to Infrahub: you review in Infrahub, with the rendered configuration
diff in front of you.

**`netmiko-mcp` for reads, a custom tool for writes.** [netmiko-mcp](https://github.com/ktbyers/netmiko_mcp) is the
official MCP server of Netmiko's author. It is read-only by design and enforces a server-side command whitelist
(`netmiko/commands.yml`: `show vlan`, `show running-config`); it has no configuration mode. Writes therefore go through
`deploy_config`, a Strands tool of this repository, where the agent's own guards apply, and which deploys Infrahub's
rendering and nothing else.

**One template for the whole configuration.** Infrahub's model is to generate the configuration, not to patch lines on
a device. The agent never composes configuration text; if something must change on a switch, the intent changes in
Infrahub first.

## Forking

Infrahub clones this repository from GitHub. If you fork it, set `INFRAHUB_REPO_URL` (and `INFRAHUB_REPO_REF`) in `.env`
before `sh install.sh`. A read-only repository does not follow pushes: after pushing a template change, run
`sh scripts/reimport.sh` to re-import and re-render. Test a template change offline first with
`uv run pytest tests/test_transforms.yml`, or against your running Infrahub with `uv run infrahubctl render eos_leaf device=leaf1`.

## Cost of a demo session

To be measured on the first complete run (tokens and price from the Anthropic console) and written here.

## Tested on

Developed on an arm64 Linux VM (OrbStack, Apple Silicon) with the ARM build of cEOS-lab; see `docs/dev-macos.md`.
The x86_64 Linux path above is the documented target and **has not yet been run by the author**. This note goes away
once it has.

## Cleanup

```sh
sh uninstall.sh          # destroys the topology, stops Infrahub (data kept)
sh uninstall.sh --purge  # also deletes Infrahub's data
```

## Licence

MIT. `infrahub/schema/` contains unmodified files of [opsmill/schema-library](https://github.com/opsmill/schema-library),
Apache-2.0, with their source and commit noted at the top of each file.
