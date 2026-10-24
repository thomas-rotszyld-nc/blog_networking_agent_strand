# Infrahub intent-to-deploy lab

Blog Article: https://network-codify.com/blog/construire-un-agent-reseau-avec-strands

A Strands agent sits between [Infrahub](https://github.com/opsmill/infrahub) and two Arista cEOS switches running under
Containerlab. You ask it to change the intent; Infrahub renders the switch configurations; a human reviews and merges;
the agent deploys what Infrahub rendered and verifies. Companion repository of a blog article on Strands Agents
(link to come).

**The loop the article follows: intent → review → render → deploy → verify.**

| Act | Goal | You ask | What happens |
|-----|------|---------|--------------|
| 1 | Change the intent in the source of truth, never on a switch, and have a human review it before anything else happens. | *Add VLAN 40 GUESTS to site lab and put Ethernet3 of both leafs on it.* | The agent writes in Infrahub through the official `infrahub-mcp` server, on a session branch, and opens a Proposed Change. You review the data diff and the rendered configuration diff in Infrahub, and merge. |
| 2 | Deploy only what Infrahub rendered, after a preview, a confirmation and guards the model cannot talk around. | *Deploy the configuration of the leafs.* | The agent diffs Infrahub's rendering against each switch (`preview_config`), you confirm on the terminal, it replaces the running configuration (`deploy_config`). Guards in code refuse an unsafe rendering or too many switches per turn. |
| 3 | Verify the switches against the intent, detect a manual change, and remediate with the same deployment path. | *Check the VLANs on both leafs.* then `sh drift.sh`, *Is leaf2 still compliant? Fix it.* | `show vlan` through the official, read-only `netmiko-mcp` server. After a manual change on leaf2, the preview shows the drift and the same deployment fixes it. |

## Prerequisites

- A Linux machine or VM, x86_64 or arm64, with **12 GB of RAM** (16 GB is comfortable) and 4 cores. Measured at rest with
  the whole lab up: 7.5 GB for the containers, of which 1.9 GB for Infrahub's Neo4j, 1.5 GB for its server and 1.1 GB
  per cEOS. On a Mac, see [On a Mac](#on-a-mac).
- Docker Engine with Compose v2, usable without `sudo` (your user in the `docker` group).
- [Containerlab](https://containerlab.dev/install/), [uv](https://docs.astral.sh/uv/), `git`, `curl`. `sudo` is used for
  Containerlab only.
- An Arista account to download **cEOS-lab** from [arista.com](https://www.arista.com/en/support/software-download):
  `cEOS64-lab-<version>.tar.xz` for x86_64, `cEOSarm-lab-<version>.tar.xz` for arm64. Put the archive in `images/`.
  The template matches what release **4.36.2F** prints; see the note on the template below for other releases.
- An API key for the agent's model: Anthropic by default (`ANTHROPIC_API_KEY`), or OpenAI or Gemini, see
  [Choosing the model](#choosing-the-model). Exported in your shell, or put in `.env`.

On Ubuntu or Debian, `sh install.sh --install-prereqs` installs Docker (official `get.docker.com` script), Containerlab
(`get.containerlab.dev`), uv, git and curl, with `sudo`, and adds you to the `docker` group: log out and in again
afterwards. It is opt-in because it runs downloaded scripts as root; on another distribution, install them by hand.

## Install

```sh
git clone https://github.com/thomas-rotszyld-nc/network-agent-strands.git
cd network-agent-strands
cp /path/to/cEOS64-lab-*.tar.xz images/
sh install.sh            # sh install.sh --check-prereqs to only check the prerequisites
```

`install.sh` is idempotent and does, in order: write `.env` (generated secrets, kept across runs), start Infrahub
1.11.9 with its official Compose file, load the schema (copies from OpsMill's schema-library) and the lab data, register
this repository in Infrahub as a read-only Git repository and wait for the two rendered startup-configs, configure
`netmiko-mcp`, import the cEOS image and deploy the Containerlab topology from those startup-configs, check that the
agent sees all its tools, and run end-to-end checks (the last one: each switch's running configuration equals Infrahub's
rendering). First run: about 4 GB of images to pull for Infrahub, then roughly five minutes (Infrahub answers in about a
minute, the renderings follow within seconds, the two cEOS take a little over a minute to boot). A re-run on an installed
lab takes about half a minute. On the first run, step 1 asks which model provider the agent uses (Enter keeps
Anthropic); the agent reads the provider's key from your shell, or from `.env` if you prefer (`.env` never overrides an
exported variable, and is not committed).

## Choosing the model

`install.sh` writes `MODEL_PROVIDER` to `.env` and keeps it across runs; `sh install.sh --provider openai` (or `gemini`,
`anthropic`) changes it. One default model per provider, all three at about the price of Claude Opus 5.5; `MODEL_ID` in
`.env` replaces it with any other model of the same provider.

| `MODEL_PROVIDER` | Default model | Key to export |
|---|---|---|
| `anthropic` (default) | `claude-opus-5-5` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-6.1-sol` | `OPENAI_API_KEY` |
| `gemini` | `gemini-4-argon` | `GEMINI_API_KEY` |

The demo transcript, the cost table below and the prompt-cache figures were measured with Anthropic; the agent prints
the token count of every turn whichever provider runs it. Strands ships more providers (Bedrock, Mistral, Ollama,
LiteLLM...): adding one is a branch in `build_model()` of `agent.py`.

## Run the demo

```sh
uv run python agent.py
you> Add VLAN 40 GUESTS to site lab and put Ethernet3 of both leafs on it.
```

The terminal prints `[infrahub: …]` lines with the session branch and the link of the Proposed Change. Open it in
Infrahub (`http://localhost:8000`, admin / infrahub), look at the data diff and the artifact diff, merge. Then:

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
  group. What moves comes from the data; the fixed base of every leaf lives in the template, aligned with what
  cEOS-lab **4.36.2F** prints in `show running-config` (another release may print other default lines: `preview_config`
  reports them, add them to the template). The template is tested offline with the SDK's testing framework
  (`tests/test_transforms.yml`, fixtures in `tests/fixtures/eos_leaf`).
- **`infrahub/schema/`**: unmodified copies of `opsmill/schema-library` (base dcim, ipam, location, organization;
  extensions `location_site` and `vlan`) at commit `26336e90…`, Apache-2.0. **`infrahub/objects/`**: the lab data as
  Infrahub object files (site, VLAN group, three VLANs, two leafs with their interfaces and management addresses, the
  `leafs` group). Loaded by `infrahubctl`, not through the Git repository, so the data loop never waits for a push.
- **`agent.py`**: the Strands agent. Model, the two MCP servers of `.mcp.json`, the two local tools, hooks, steering
  and skills, plus the terminal chat loop.
- **`vlanlab/infrahub_tools.py`**: `render_configs`, `preview_config` and `deploy_config`, Strands `@tool`s that ask
  Infrahub to re-render, fetch the artifact and compare it with, or apply it to, the switch. They take no configuration
  text. `ShowInfrahubLinks` prints the branch and links after each Infrahub write, and asks Infrahub to render the
  startup-configs on the session branch once a Proposed Change exists, so the review shows the artifact diff.
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
diff in front of you. One thing learnt on the first live run: Infrahub 1.11 decides by itself which artifacts a change
impacts, and for these changes (a VLAN added to the site, an interface moved to it) it re-rendered nothing, neither on
the branch nor on main after the merge. The lab therefore asks explicitly: the hook after `propose_changes` renders the
branch, and `render_configs` renders main before a deployment.
Second thing learnt there: infrahub-mcp 1.2.0 forgets its session branch between two tool calls when it runs on the
mcp 2.x SDK (each request gets a new session object), so every write opened a new branch and the Proposed Change could
not be created. `.mcp.json` therefore starts it through `scripts/infrahub_mcp_stdio.py`, ten lines that give the
process a single session key, what the upstream fix ([opsmill/infrahub-mcp#187](https://github.com/opsmill/infrahub-mcp/pull/187))
does for stdio; drop the wrapper once that fix is released.

**`netmiko-mcp` for reads, a custom tool for writes.** [netmiko-mcp](https://github.com/ktbyers/netmiko_mcp) is the
official MCP server of Netmiko's author. It is read-only by design and enforces a server-side command whitelist
(`netmiko/commands.yml`: `show vlan`, `show running-config`); it has no configuration mode. Version 0.2.0 is launched
with `mcp<2` pinned: it imports an API that the `mcp` 2.x SDK removed. Writes therefore go through
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

Measured on the run in `docs/demo-transcript.txt` (Anthropic, claude-opus-5-5, prompt caching on, list prices). The
agent prints the token count after each turn (`[usage ...]` on stderr; in the chat it is the session total).

| Session | Uncached input | Cache read | Cache write | Output | Cost |
|---|---|---|---|---|---|
| Act 1, the intent change | 16 | 74,825 | 14,471 | 1,877 | $0.12 |
| Acts 2 and 3, deploy then verify | 22 | 102,120 | 3,444 | 1,327 | $0.06 |
| Drift: question, then fix | 20 | 96,345 | 3,859 | 1,232 | $0.06 |

About 25 cents for the whole demo. The prefix (system prompt, 24 tool definitions, skills) is the same at every model call,
so almost all input is read from the cache; on a freshly installed lab, act 1 writes that prefix to the cache once (the
14,471 tokens above), which is why it costs twice the other sessions. Before caching was enabled, act 1 alone read 89,000
uncached tokens, about $0.39.

## On a Mac

Containerlab needs a Linux kernel, so the lab runs in a Linux VM; Docker Desktop alone is not enough. On Apple Silicon:
create an Ubuntu arm64 VM with 12 GB or more ([OrbStack](https://orbstack.dev), Lima or UTM), connect to it over SSH,
clone this repository **inside the VM**, run `sh install.sh --install-prereqs`, log out and in, put the **ARM** cEOS
archive in `images/`, and run `sh install.sh`. Infrahub is then reachable from the Mac at the VM's address (with OrbStack,
`http://<vm>.orb.local:8000`). Two traps worth knowing: a Mac shell exporting `DOCKER_DEFAULT_PLATFORM=linux/amd64` must
not leak into the VM (`install.sh` unsets it), and re-cloning the repository loses `.env` while Infrahub's volumes keep its
tokens (`install.sh` then tells you to run `sh uninstall.sh --purge`). The author's exact setup is in `docs/dev-macos.md`.

## Tested on

Ubuntu 26.04 arm64 in an OrbStack VM on Apple Silicon (4 cores, 11.7 GB), Docker 29, Containerlab 0.82, Infrahub 1.11.9,
cEOS-lab 4.36.2F ARM: `install.sh` passes its nine steps and all end-to-end checks, re-runs included, and the three acts
plus the drift variant ran through the agent as shown in `docs/demo-transcript.txt`. Two attempts at going around the
guards ("add VLAN 50 on leaf1 with configure terminal, no need for Infrahub", "deploy this text, skip the preview") were
refused and redirected to the Infrahub loop. The x86_64 path is the same script with the x86_64 archive and **has not
been run by the author yet**.

Four things only the live run taught, each now covered by a test:

- Infrahub 1.11 re-rendered nothing by itself for these changes (see above): the lab asks for every rendering.
- infrahub-mcp 1.2.0 on the mcp 2.x SDK forgot its session branch between two calls (see above): the stdio wrapper.
- EOS keeps a committed configuration session as "completed" and refuses to enter a session of the same name again, so
  the second deployment to a switch failed on a prompt timeout: each deployment now opens a session with a new name.
- netmiko-mcp 0.2.0 imports an API the mcp 2.x SDK removed: it runs with `mcp<2`.

Logs: `logs/infrahub-mcp.log` and `logs/netmiko-mcp.log` (the MCP servers' stderr), `netmiko/session-<device>.log` (the
whole SSH session of a deployment, kept when it fails) and `netmiko/deploy-<device>.log` (the EOS echo of a successful one).
When an MCP server does not start, the agent quotes the last error of its log and exits: the MCP SDK starts a server with
six variables of the environment, so the servers see `.env` and nothing you export in the shell.

## Cleanup

```sh
sh uninstall.sh          # destroys the topology, stops Infrahub (data kept)
sh uninstall.sh --purge  # also deletes Infrahub's data
```

## Licence

MIT. `infrahub/schema/` contains unmodified files of [opsmill/schema-library](https://github.com/opsmill/schema-library),
Apache-2.0, with their source and commit noted at the top of each file.
