# Infrahub Intent-to-Deploy Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. When a task touches Infrahub schema, objects, `.infrahub.yml`, the GraphQL query or the Jinja2 template, also load the matching `infrahub:*` plugin skill (`infrahub-managing-schemas`, `infrahub-managing-objects`, `infrahub-managing-transforms`): its rules are the conventions this plan follows.

**Goal:** A public companion repo that a reader installs with `sh install.sh`, where a Strands agent changes the intent in Infrahub on a branch, the human merges the Proposed Change, and the agent deploys the configuration Infrahub rendered onto two Arista cEOS switches under Containerlab, then verifies.

**Architecture:** One Strands agent (`agent.py`) gets its tools from two MCP servers (`infrahub-mcp` for Infrahub, `netmiko-mcp` for `show` commands) and two in-repo `@tool`s: `preview_config` (diff rendered vs running, read-only) and `deploy_config` (full replace of the running config with Infrahub's artifact). Guardrails are code: `DeployGuard` steering refuses a missing or unsafe rendering and caps devices per turn; `ConfirmDeploy` asks on the terminal after steering; `ShowInfrahubLinks` prints branch and object links after Infrahub writes. The repo is also the Git repository Infrahub clones (read-only) for the query, the template and the artifact definition; schema and data are loaded by `infrahubctl`.

**Tech Stack:** Python 3.12 + uv; `strands-agents[anthropic]>=1.61.1,<2`; `netmiko>=4.7,<5`; `infrahub-sdk[all]==1.23.2` (gives `infrahubctl` and the pytest plugin); `infrahub-mcp==1.2.0`; `netmiko-mcp==0.2.0`; Infrahub `1.11.9` (compose from `https://infrahub.opsmill.io/1.11.9`); `opsmill/schema-library` at commit `26336e9026dff1907f2c58e81dd6ae7b5c3f763e`; Containerlab ≥ 0.81; Arista cEOS-lab; pytest.

**Spec:** `docs/superpowers/specs/2026-10-22-vlan-drift-lab-design.md`

## Global Constraints

- Repo language English; licence MIT; repo `https://github.com/thomas-rotszyld-nc/blog_networking_agent_strand`, default branch `main`.
- No trace of `strand_agents_lab` data: no `c9500`, `poc`, `NGW`, `strand-agents-lab`, `5trandagent5lab`, `Europe/Paris`, `*-Lab-2026-password`, no NetBox.
- Fixed names: site `lab` (LocationSite, name `lab`); devices `leaf1`, `leaf2` (DcimDevice, role `leaf`, status `active`, platform `Arista EOS`, device type `cEOS-lab`, manufacturer `Arista`); group `leafs` (CoreStandardGroup); VLAN group `lab-vlans` scoped to the site; VLANs `USERS`/10, `VOICE`/20, `IOT`/30 (IpamVLAN, status `active`); interfaces `Ethernet1..3` (InterfacePhysical, role `access`, status `active`, `l2_mode: access`, `untagged_vlan` 10/20/30) and `Management0` (role `management`); management IPs `172.20.20.11/24`, `172.20.20.12/24` (IpamIPAddress, device `primary_address`); Containerlab lab `vlan-lab` (containers `clab-vlan-lab-leaf1/2`), image tag `ceos:lab`, credentials `admin`/`admin`; Infrahub at `http://localhost:8000`; compose project `vlan-lab`.
- `.infrahub.yml`: query `leaf_config`, Jinja2 transform `eos_leaf`, artifact definition `leaf_startup_config` (artifact_name `startup-config`, `text/plain`, targets `leafs`, parameters `device: name__value`).
- infrahub-mcp branch pattern `agent/{date}-{hex}`; netmiko-mcp allowed commands `show vlan*`, `show running-config*`.
- `DeployGuard`: refuse when the artifact is missing/empty, lacks `hostname <device>`, lacks an `interface Management0` block containing the inventory host IP, lacks `username admin`; at most 2 devices deployed per turn. `ConfirmDeploy` runs at `HookOrder.SDK_LAST` and skips a cancelled call.
- `sudo` only around `containerlab`; secrets and generated files git-ignored: `.env`, `infrahub/docker-compose.yml`, `netmiko/*`, `images/*`, `clab/generated/*`, `clab/clab-vlan-lab/`.
- Every script idempotent, POSIX sh, `set -e`, exits non-zero with a message naming the fix.
- Install order (plugin rule): schema, then objects, then repository registration. The repository definition never lives in `infrahub/objects/`.

## Review Focus

1. cEOS adds default lines to `show running-config` that no template emits (`no aaa root`, `transceiver qsfp default-mode 4x10G`, `spanning-tree mode mstp`, `! Command:` headers…): `preview_config` must report "no difference" right after a clean deploy, or every demo starts with a false drift. Pinned in Task 7 (normalisation test) and Task 11 (alignment loop against the real running-config).
2. `deploy_config` on an unreachable or slow leaf must return an error string, never a traceback that ends the turn. Task 6 and Task 7.
3. A rendering whose management block is missing or points at the wrong IP would lock the operator out: `DeployGuard` refuses it before any confirmation. Task 8.
4. The agent's `mutate_graphql` writes return raw data: `ShowInfrahubLinks` must still print a usable link (object id from the response, branch from `get_session_info`) and must never raise inside the hook. Task 7.
5. A reader who forks the repo must only change `INFRAHUB_REPO_URL`; a reader on `images/` with zero or two archives gets one clear message. Task 11.

---

### Task 0: Spike — artifact diff in a Proposed Change with a read-only repository

**Files:**
- Create: `docs/spike-readonly-repo.md`
- Throwaway: a branch `spike/readonly-repo` of this repo holding a minimal `.infrahub.yml`, `infrahub/queries/leaf_config.gql`, `infrahub/templates/eos_leaf.j2` (hostname + VLAN list only), the schema files and object files of Task 2 (do them first if you prefer; the spike only needs schema + one device + VLANs + group).

**Interfaces:**
- Produces: a go/no-go for the read-only repository design, recorded in the doc; the real artifact wait time and the UI tab where the artifact diff appears.

- [ ] **Step 1: Stand up Infrahub in the dev VM**

Run: `mkdir -p infrahub && curl -sL https://infrahub.opsmill.io/1.11.9 -o infrahub/docker-compose.yml && INFRAHUB_INITIAL_ADMIN_TOKEN=$(uuidgen | tr A-F a-f) docker compose -p vlan-lab -f infrahub/docker-compose.yml up -d && until curl -sf http://localhost:8000/api/config >/dev/null; do sleep 10; done; echo up`
Expected: `up` within a few minutes; UI at `http://localhost:8000` (admin / infrahub).

- [ ] **Step 2: Load schema and a minimal data set, register the spike branch read-only**

Run (with `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` exported): `uv run infrahubctl schema load infrahub/schema --wait 60 && uv run infrahubctl object load infrahub/objects && git push -u origin spike/readonly-repo && uv run infrahubctl repository add blog-lab https://github.com/thomas-rotszyld-nc/blog_networking_agent_strand --read-only --ref spike/readonly-repo`
Expected: in the UI, Repository `blog-lab` reaches status `in-sync`; two `CoreArtifact` nodes of definition `leaf_startup_config` appear with status `Ready`. Note the elapsed time.

- [ ] **Step 3: Data branch + Proposed Change, look for the artifact diff**

Run: `uv run infrahubctl branch create spike-change` then in the UI (or with `infrahubctl object load --branch spike-change` on an edited VLAN file) rename VLAN `IOT` to `IOT2` on branch `spike-change`; create a Proposed Change `spike-change → main` in the UI.
Expected: the Proposed Change shows a data diff and, in its Artifacts tab (or checks), a per-device artifact diff with the renamed VLAN. Record exactly where it appears and how long it took. If no artifact diff appears after 5 minutes, record that too.

- [ ] **Step 4: Template change + re-import**

Edit the template (add a comment line), commit, push to `spike/readonly-repo`, then run the mutation `InfrahubReadOnlyRepositoryImportLastCommit(data: {id: "<repo id>"}) { ok }` through `uv run infrahubctl` (GraphQL) or `curl` on `/graphql`.
Expected: repository commit advances and the two artifacts re-render with the comment line. Record the time.

- [ ] **Step 5: Write `docs/spike-readonly-repo.md` and decide**

Contents: what was run, what appeared where, timings, the decision: read-only repo confirmed, or fall back to `CoreRepository` with GitHub credentials (then update the spec's Git section before continuing). Tear down: `docker compose -p vlan-lab -f infrahub/docker-compose.yml down -v`; delete the Infrahub branch; keep the GitHub spike branch until Task 3 replaces it.

- [ ] **Step 6: Commit**

```bash
git checkout main && git add docs/spike-readonly-repo.md && git commit -m "docs: spike result, read-only repository and artifact diff in proposed changes"
```

---

### Task 1: Repository skeleton

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `LICENSE`, `.env.example`, `images/.gitkeep`, `netmiko/.gitkeep`, `clab/generated/.gitkeep`, `vlanlab/__init__.py`, `tests/__init__.py`, `tests/test_skeleton.py`

**Interfaces:**
- Produces: package `vlanlab`; `uv run pytest` as the test command; `uv run infrahubctl` available.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skeleton.py
import shutil, subprocess

def test_dependencies_import():
    import netmiko, strands, strands.models.anthropic, infrahub_sdk  # noqa: F401

def test_infrahubctl_is_in_the_venv():
    assert subprocess.run(["uv", "run", "infrahubctl", "version"], capture_output=True).returncode == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/blog_networking_agent_strand && uv run pytest tests/test_skeleton.py -q`
Expected: FAIL (no pyproject / modules missing).

- [ ] **Step 3: Write `pyproject.toml`, `.python-version` (`3.12`)**

Project `infrahub-intent-lab`, `requires-python = ">=3.12"`, dependencies `strands-agents[anthropic]>=1.61.1,<2`, `netmiko>=4.7,<5`, `infrahub-sdk[all]==1.23.2`; dev group `pytest>=8`; `license = "MIT"`; `[project.urls] Repository`. `[tool.pytest.ini_options] testpaths = ["tests"]`.

- [ ] **Step 4: Write `.gitignore`, `LICENSE` (MIT, 2026, repo owner), `.env.example`, the `.gitkeep`s, empty `__init__.py`s**

`.gitignore`: `__pycache__/`, `*.py[oc]`, `.venv`, `.env`, `.pytest_cache/`, `infrahub/docker-compose.yml`, `netmiko/*` + `!netmiko/.gitkeep`, `images/*` + `!images/.gitkeep`, `clab/generated/*` + `!clab/generated/.gitkeep`, `clab/clab-vlan-lab/`.
`.env.example` keys with one comment line each, values empty: `ANTHROPIC_API_KEY`, `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN`, `INFRAHUB_INITIAL_ADMIN_TOKEN`, `INFRAHUB_INITIAL_AGENT_TOKEN`, `INFRAHUB_SECURITY_SECRET_KEY`, `INFRAHUB_REPO_URL`, `INFRAHUB_REPO_REF`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv sync --group dev && uv run pytest tests/test_skeleton.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: repository skeleton (uv project, MIT licence, ignores)"
```

---

### Task 2: Infrahub schema and object files

**Files:**
- Create: `infrahub/schema/00_organization.yml`, `01_location.yml`, `02_dcim.yml`, `03_ipam.yml`, `04_location_site.yml`, `05_vlan.yml` (copies from schema-library at the pinned commit, header comment added: source path, commit, licence); `infrahub/objects/01_organization.yml`, `02_location.yml`, `03_groups.yml`, `04_dcim_types.yml`, `05_ipam.yml`, `06_devices.yml`; `tests/test_infrahub_files.py`

**Interfaces:**
- Produces: `uv run infrahubctl schema load infrahub/schema --wait 60` then `uv run infrahubctl object load infrahub/objects` yield the decor of the spec on a fresh Infrahub.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_infrahub_files.py
import pathlib, yaml
ROOT = pathlib.Path(__file__).resolve().parents[1]

def docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]

def test_schema_files_are_pinned_copies():
    files = sorted((ROOT / "infrahub/schema").glob("*.yml"))
    assert [f.name[3:] for f in files] == ["organization.yml", "location.yml", "dcim.yml", "ipam.yml", "location_site.yml", "vlan.yml"]
    for f in files:
        assert "26336e9026dff1907f2c58e81dd6ae7b5c3f763e" in f.read_text().splitlines()[1]

def test_objects_match_the_scenario():
    objs = {}
    for f in sorted((ROOT / "infrahub/objects").glob("*.yml")):
        for d in docs(f):
            assert d["apiVersion"] == "infrahub.app/v1" and d["kind"] == "Object"
            objs.setdefault(d["spec"]["kind"], []).extend(d["spec"]["data"])
    assert [v["name"] for v in objs["IpamVLAN"]] == ["USERS", "VOICE", "IOT"]
    assert [v["vlan_id"] for v in objs["IpamVLAN"]] == [10, 20, 30]
    assert objs["IpamVLANGroup"][0]["scope"]["kind"] == "LocationSite"
    assert [g["name"] for g in objs["CoreStandardGroup"]] == ["leafs"]
    devices = objs["DcimDevice"]
    assert [d["name"] for d in devices] == ["leaf1", "leaf2"]
    for d in devices:
        assert d["member_of_groups"] == ["leafs"] and d["role"] == "leaf"
        names = [i["name"] for i in d["interfaces"]["data"]]
        assert names == ["Management0", "Ethernet1", "Ethernet2", "Ethernet3"]
        assert [i.get("untagged_vlan") for i in d["interfaces"]["data"][1:]] == ["USERS", "VOICE", "IOT"]
    assert sorted(ip["address"] for ip in objs["IpamIPAddress"]) == ["172.20.20.11/24", "172.20.20.12/24"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_infrahub_files.py -q`
Expected: FAIL, files missing.

- [ ] **Step 3: Vendor the six schema files**

For each of `base/organization.yml`, `base/location.yml`, `base/dcim.yml`, `base/ipam.yml`, `extensions/location_site/location_site.yml`, `extensions/vlan/vlan.yml`: `gh api "repos/opsmill/schema-library/contents/<path>?ref=26336e9026dff1907f2c58e81dd6ae7b5c3f763e" -H "Accept: application/vnd.github.raw"` into the numbered file, and insert as line 2 the comment `# Copied from opsmill/schema-library <path> @ 26336e9026dff1907f2c58e81dd6ae7b5c3f763e (Apache-2.0), unmodified.` (line 1 stays the `yaml-language-server` comment of the original).

- [ ] **Step 4: Write the object files**

Load order by number. `01`: `OrganizationManufacturer` Arista. `02`: `LocationSite` `lab` (status `active`). `03`: `CoreStandardGroup` `leafs`. `04`: `DcimPlatform` `Arista EOS` (manufacturer Arista); `DcimDeviceType` `cEOS-lab` (manufacturer Arista). `05`: `IpamVLANGroup` `lab-vlans` with `scope: {kind: LocationSite, data: {name: lab}}`; the three `IpamVLAN` (name, vlan_id, status active, role user, vlan_group `lab-vlans`); two `IpamIPAddress` `172.20.20.11/24`, `172.20.20.12/24` (default namespace). `06`: the two `DcimDevice` with `location: {kind: LocationSite, data: {name: lab}}`, `device_type`, `platform`, `role: leaf`, `status: active`, `member_of_groups: [leafs]`, `primary_address` referencing the device's IP by HFID (check the HFID shape with `uv run infrahubctl schema` once Infrahub runs; the plugin's `infrahub-managing-objects` rules give the scalar-vs-list form), and `interfaces: {kind: InterfacePhysical, data: [...]}` with `Management0` (role management, status active, `ip_addresses` referencing the same IP) and `Ethernet1..3` (role access, status active, `l2_mode: access`, `untagged_vlan: USERS|VOICE|IOT`, description `access port VLAN <vid>`). If `untagged_vlan: USERS` is rejected at load (generic peer), switch to `{kind: IpamVLAN, data: {name: USERS}}` and update the test accordingly.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_infrahub_files.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Verify against Infrahub (dev VM, Infrahub up as in Task 0 step 1)**

Run: `uv run infrahubctl schema load infrahub/schema --wait 60 && uv run infrahubctl object load infrahub/objects && uv run infrahubctl object load infrahub/objects`
Expected: schema loaded; first object load creates everything, second changes nothing; in the UI `leaf1` has four interfaces, `Ethernet1` shows untagged VLAN `USERS`, group `leafs` has two members.

- [ ] **Step 7: Commit**

```bash
git add infrahub/schema infrahub/objects tests/test_infrahub_files.py && git commit -m "feat: Infrahub schema (pinned schema-library copies) and lab objects"
```

---

### Task 3: The rendering: `.infrahub.yml`, GraphQL query, Jinja2 template

**Files:**
- Create: `.infrahub.yml`, `infrahub/queries/leaf_config.gql`, `infrahub/templates/eos_leaf.j2`, `tests/test_transforms.yml`, `tests/fixtures/eos_leaf/input.json`, `tests/fixtures/eos_leaf/output.txt`, `tests/test_infrahub_yml.py`

**Interfaces:**
- Produces: transform `eos_leaf` renders a complete EOS startup-config from `data` (the GraphQL response for one device); artifact definition `leaf_startup_config`; `uv run infrahubctl render eos_leaf device=leaf1` works against a running Infrahub.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_infrahub_yml.py
import pathlib
from infrahub_sdk.schema.repository import InfrahubRepositoryConfig
import yaml
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_infrahub_yml_is_valid_and_wired():
    cfg = InfrahubRepositoryConfig(**yaml.safe_load((ROOT / ".infrahub.yml").read_text()))
    assert [q.name for q in cfg.queries] == ["leaf_config"]
    t = cfg.jinja2_transforms[0]; assert (t.name, t.query, str(t.template_path)) == ("eos_leaf", "leaf_config", "infrahub/templates/eos_leaf.j2")
    a = cfg.artifact_definitions[0]
    assert (a.name, a.artifact_name, a.content_type, a.targets, a.transformation, a.parameters) == \
        ("leaf_startup_config", "startup-config", "text/plain", "leafs", "eos_leaf", {"device": "name__value"})
    assert (ROOT / cfg.queries[0].file_path).exists() and (ROOT / t.template_path).exists()
```

```yaml
# tests/test_transforms.yml
---
version: "1.0"
infrahub_tests:
  - resource: Jinja2Transform
    resource_name: eos_leaf
    tests:
      - name: smoke_eos_leaf
        spec: { kind: jinja2-transform-smoke }
      - name: render_leaf1
        spec: { kind: jinja2-transform-unit-render, directory: tests/fixtures/eos_leaf, input: input.json, output: output.txt }
        expect: PASS
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_infrahub_yml.py tests/test_transforms.yml -q`
Expected: FAIL, files missing.

- [ ] **Step 3: Write `.infrahub.yml` and `infrahub/queries/leaf_config.gql`**

`.infrahub.yml`: the three sections of Global Constraints, nothing else. The query, `query leaf_config($device: String!)`, fetches `DcimDevice(name__value: $device)` with `name`, `primary_address { node { address { value } } }`, `location { node { ... on LocationSite { name { value } vlan_groups { edges { node { vlans { edges { node { name { value } vlan_id { value } } } } } } } } } }`, and `interfaces { edges { node { name { value } description { value } role { value } ... on InterfaceLayer2 { l2_mode { value } untagged_vlan { node { vlan_id { value } } } } } } }`. Verify field names with `uv run infrahubctl schema` or the Infrahub GraphQL sandbox before locking the fixture.

- [ ] **Step 4: Write `infrahub/templates/eos_leaf.j2` and the fixture**

Template reads `data.DcimDevice.edges[0].node`; emits, in this order: `hostname`, `username admin privilege 15 secret admin`, `!`, `service routing protocols model multi-agent`, `!`, one `vlan N` / `   name X` block per VLAN sorted by `vlan_id`, interfaces sorted by name (`Ethernet*` first, then `Management0`) with `   description …` and `   switchport access vlan N` when `l2_mode == "access"` and `untagged_vlan` is set, `interface Management0` with `   ip address <primary_address>`, the `management api http-commands / no shutdown` block, `end`. Three-space EOS indentation, `!` separators. `tests/fixtures/eos_leaf/input.json` is a hand-written GraphQL response for `leaf1` with the three VLANs and four interfaces; `output.txt` is the exact rendering. Task 11 will realign both to what cEOS actually shows in `show running-config`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_infrahub_yml.py tests/test_transforms.yml -q`
Expected: `3 passed` (one Python test, smoke, unit render).

- [ ] **Step 6: Verify live (dev VM, data of Task 2 loaded)**

Run: `uv run infrahubctl render eos_leaf device=leaf1`
Expected: the rendered config for leaf1, identical to `output.txt` apart from values that differ between fixture and live data (ideally none).

- [ ] **Step 7: Commit**

```bash
git add .infrahub.yml infrahub/queries infrahub/templates tests/test_transforms.yml tests/fixtures tests/test_infrahub_yml.py && git commit -m "feat: leaf_config query, eos_leaf Jinja2 transform and startup-config artifact definition"
```

---

### Task 4: Infrahub bootstrap helpers (artifacts, re-import)

**Files:**
- Create: `vlanlab/infrahub_api.py`, `scripts/wait_artifacts.py`, `scripts/reimport.sh`, `tests/test_infrahub_api.py`

**Interfaces:**
- Produces: `client() -> InfrahubClientSync` (from `INFRAHUB_ADDRESS`/`INFRAHUB_API_TOKEN`); `fetch_artifact(device: str, name: str = "startup-config", branch: str = "main", client=None) -> str` (raises `ArtifactNotReady(device)` when no Ready artifact with a storage_id exists); `wait_artifacts(devices: list[str], timeout: int = 600, client=None) -> dict[str, str]` (polls every 5 s until every device has a Ready artifact, returns contents); `repository_id(name: str, client=None) -> str`; `reimport_repository(name: str = "blog-lab", client=None) -> None` (runs `InfrahubReadOnlyRepositoryImportLastCommit`). `scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated` writes `<device>.cfg` files. `sh scripts/reimport.sh` calls `reimport_repository` then `wait_artifacts`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_infrahub_api.py
import pytest
from vlanlab import infrahub_api as api

class Node:
    def __init__(self, **kw): self.__dict__.update(kw)
class Attr:
    def __init__(self, value): self.value = value

class FakeClient:
    def __init__(self, artifacts, blobs): self.artifacts, self.blobs, self.calls = artifacts, blobs, []
    def filters(self, kind, **kw): self.calls.append((kind, kw)); return self.artifacts
    class object_store:
        blobs = {}
        @classmethod
        def get(cls, identifier): return cls.blobs[identifier]
    def execute_graphql(self, query, **kw): self.calls.append(("gql", query)); return {"InfrahubReadOnlyRepositoryImportLastCommit": {"ok": True}}

def ready(device, storage):
    return Node(status=Attr("Ready"), storage_id=Attr(storage), object=Node(peer=Node(display_label=device)))

def test_fetch_artifact_returns_body(monkeypatch):
    c = FakeClient([ready("leaf1", "s1")], {}); FakeClient.object_store.blobs = {"s1": "hostname leaf1\nend\n"}
    assert api.fetch_artifact("leaf1", client=c) == "hostname leaf1\nend\n"

def test_fetch_artifact_not_ready():
    c = FakeClient([Node(status=Attr("Pending"), storage_id=Attr(None), object=Node(peer=Node(display_label="leaf1")))], {})
    with pytest.raises(api.ArtifactNotReady): api.fetch_artifact("leaf1", client=c)

def test_wait_artifacts_times_out(monkeypatch):
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    c = FakeClient([], {})
    with pytest.raises(TimeoutError): api.wait_artifacts(["leaf1"], timeout=0, client=c)

def test_reimport_runs_the_mutation(monkeypatch):
    c = FakeClient([], {}); monkeypatch.setattr(api, "repository_id", lambda name, client=None: "repo-1")
    api.reimport_repository(client=c)
    assert any("InfrahubReadOnlyRepositoryImportLastCommit" in q for kind, q in c.calls if kind == "gql")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_infrahub_api.py -q`
Expected: FAIL, module missing.

- [ ] **Step 3: Implement `vlanlab/infrahub_api.py`**

Use `infrahub_sdk.InfrahubClientSync` (`Config(address, api_token)`). `fetch_artifact`: `client.filters(kind="CoreArtifact", definition__name__value="leaf_startup_config", branch=branch, include=["object"])`, keep those whose `object.peer.display_label == device`, `status.value == "Ready"` and `storage_id.value`; read `client.object_store.get(storage_id)`. If the SDK filter names differ in 1.23.2, adjust the fake to the real call shape. `wait_artifacts`: loop with `time.sleep(5)` until all devices resolve or `timeout` seconds pass → `TimeoutError` naming the missing devices. `reimport_repository`: `execute_graphql` with the mutation from the spec.

- [ ] **Step 4: Write `scripts/wait_artifacts.py` and `scripts/reimport.sh`**

`wait_artifacts.py`: argparse (`devices`, `--out`, `--timeout 600`), writes each content to `<out>/<device>.cfg`, prints one line per file. `reimport.sh`: `uv run python -c "from vlanlab.infrahub_api import reimport_repository; reimport_repository()"` then `uv run python scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_infrahub_api.py -q`
Expected: `4 passed`.

- [ ] **Step 6: Verify live (repo registered as in Task 0 / Task 11)**

Run: `uv run python scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated && head -3 clab/generated/leaf1.cfg`
Expected: two files written; `hostname leaf1` in the first lines.

- [ ] **Step 7: Commit**

```bash
git add vlanlab/infrahub_api.py scripts tests/test_infrahub_api.py && git commit -m "feat: Infrahub artifact fetch/wait helpers and read-only repository re-import"
```

---

### Task 5: Containerlab topology

**Files:**
- Create: `clab/vlan-lab.clab.yml`, `tests/test_clab.py`

**Interfaces:**
- Produces: `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure` boots `leaf1`/`leaf2` from `clab/generated/leaf1.cfg` / `leaf2.cfg`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clab.py
import pathlib, yaml
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_topology_uses_generated_startup_configs():
    topo = yaml.safe_load((ROOT / "clab/vlan-lab.clab.yml").read_text())
    assert topo["name"] == "vlan-lab"
    assert topo["topology"]["kinds"]["arista_ceos"]["image"] == "ceos:lab"
    nodes = topo["topology"]["nodes"]
    assert nodes["leaf1"] == {"mgmt-ipv4": "172.20.20.11", "startup-config": "generated/leaf1.cfg"}
    assert nodes["leaf2"] == {"mgmt-ipv4": "172.20.20.12", "startup-config": "generated/leaf2.cfg"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_clab.py -q`
Expected: FAIL, file missing.

- [ ] **Step 3: Write `clab/vlan-lab.clab.yml`**

`name: vlan-lab`; `topology.kinds.arista_ceos.image: ceos:lab`; nodes `leaf1`/`leaf2` with `mgmt-ipv4` and `startup-config: generated/<name>.cfg` (relative to the topology file); one link `leaf1:eth1 <-> leaf2:eth1`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_clab.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Verify in the dev VM (artifacts downloaded, `ceos:lab` imported)**

Run: `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure && sleep 120 && docker exec clab-vlan-lab-leaf1 Cli -c "show vlan"`
Expected: VLANs 10 USERS, 20 VOICE, 30 IOT. Note the boot time for Task 11.

- [ ] **Step 6: Commit**

```bash
git add clab/vlan-lab.clab.yml tests/test_clab.py && git commit -m "feat: Containerlab topology booting from Infrahub-rendered startup-configs"
```

---

### Task 6: EOS access layer (`vlanlab/eos.py`)

**Files:**
- Create: `vlanlab/eos.py`, `tests/test_eos.py`

**Interfaces:**
- Produces: `INVENTORY_FILE = Path("netmiko/.netmiko.yml")`; `load_inventory(path=INVENTORY_FILE) -> dict[str, dict]`; `connect = ConnectHandler` (module attribute); `running_config(params: dict) -> str`; `replace_config(params: dict, config: str) -> str` (full replacement + save, returns device output; raises `DeployError(str)` on failure or if SSH does not answer afterwards); `class DeployError(Exception)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eos.py
import textwrap, pytest
from vlanlab import eos

INV = textwrap.dedent("""
    leaf1: {device_type: arista_eos, host: 172.20.20.11, username: admin, password: admin}
    leaf2: {device_type: arista_eos, host: 172.20.20.12, username: admin, password: admin}
    leafs: [leaf1, leaf2]
""")

class FakeConn:
    sent, saved = [], 0
    def __init__(self, **kw): self.kw = kw
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def send_command(self, cmd, **kw): return "hostname leaf1\n!\nend\n" if "running" in cmd else "ok"
    def send_config_set(self, cmds, **kw): FakeConn.sent.extend(cmds); return "\n".join(cmds)
    def save_config(self): FakeConn.saved += 1; return "Copy completed"

def test_load_inventory_skips_groups(tmp_path):
    p = tmp_path / ".netmiko.yml"; p.write_text(INV)
    inv = eos.load_inventory(p); assert set(inv) == {"leaf1", "leaf2"} and inv["leaf2"]["host"] == "172.20.20.12"

def test_running_config_and_replace(monkeypatch):
    monkeypatch.setattr(eos, "connect", FakeConn)
    assert eos.running_config({"host": "x"}).startswith("hostname leaf1")
    out = eos.replace_config({"host": "x"}, "hostname leaf1\nvlan 40\n   name GUESTS\nend\n")
    assert "vlan 40" in FakeConn.sent and FakeConn.saved == 1 and isinstance(out, str)

def test_connection_failure_is_deploy_error(monkeypatch):
    class Boom:
        def __init__(self, **kw): raise TimeoutError("timed out")
    monkeypatch.setattr(eos, "connect", Boom)
    with pytest.raises(eos.DeployError): eos.replace_config({"host": "x"}, "hostname leaf1\nend\n")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_eos.py -q`
Expected: FAIL, module missing.

- [ ] **Step 3: Implement `vlanlab/eos.py`**

`load_inventory` via `netmiko.utilities.load_yaml_file` + `obtain_all_devices`, dicts only. `running_config`: `send_command("show running-config")`. `replace_config`: open a configuration session and replace atomically: `send_config_set(["configure session agent", "rollback clean-config", *config_lines_without_end, "commit"], exit_config_mode=False, cmd_verify=False)`, then `save_config()`, then reconnect and `send_command("show hostname")` to prove SSH still answers; any exception → `DeployError`. If `rollback clean-config` + `commit` does not behave on cEOS (Task 11 will tell), switch to `netmiko.file_transfer` of the rendered text to `flash:candidate.cfg` and `configure replace flash:candidate.cfg`, keeping the same signature and tests.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eos.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add vlanlab/eos.py tests/test_eos.py && git commit -m "feat: EOS access layer (inventory, running-config, atomic replace)"
```

---

### Task 7: Agent tools and the Infrahub link hook (`vlanlab/infrahub_tools.py`)

**Files:**
- Create: `vlanlab/infrahub_tools.py`, `tests/test_infrahub_tools.py`

**Interfaces:**
- Consumes: Task 4 `fetch_artifact`, `ArtifactNotReady`; Task 6 `load_inventory`, `running_config`, `replace_config`, `DeployError`.
- Produces: `normalize(config: str) -> list[str]` (drops blank lines, lines starting with `!`, trailing spaces, and the `end` line); `config_diff(running: str, rendered: str) -> str` (unified diff of normalised lines, `""` when equal); `@tool preview_config(device: str) -> str`; `@tool deploy_config(device: str) -> str`; `PREVIEW_TOOL = "preview_config"`, `DEPLOY_TOOL = "deploy_config"`; `class ShowInfrahubLinks(HookProvider)` with `__init__(self, infrahub: MCPClient | None, base_url: str)` and `show(event)`; `INFRAHUB_WRITE_TOOLS = ("node_upsert", "mutate_graphql", "propose_changes")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_infrahub_tools.py
import json
from types import SimpleNamespace
from vlanlab import infrahub_tools as it

RUNNING = "! Command: show running-config\n! device: leaf1 (cEOSLab)\n!\nhostname leaf1\n!\nvlan 10\n   name USERS\n!\nend\n"
RENDERED = "hostname leaf1\n!\nvlan 10\n   name USERS\n!\nend\n"

def test_normalize_ignores_comments_blank_and_end():
    assert it.normalize(RUNNING) == it.normalize(RENDERED) == ["hostname leaf1", "vlan 10", "   name USERS"]
    assert it.config_diff(RUNNING, RENDERED) == ""
    assert "+vlan 40" in it.config_diff(RUNNING, RENDERED + "vlan 40\n   name GUESTS\n")

def patch_backend(monkeypatch, rendered=RENDERED, running=RUNNING, inventory=None):
    monkeypatch.setattr(it, "fetch_artifact", lambda device, **kw: rendered)
    monkeypatch.setattr(it, "running_config", lambda params: running)
    monkeypatch.setattr(it, "load_inventory", lambda *a, **k: inventory or {"leaf1": {"host": "172.20.20.11"}})
    pushed = []
    monkeypatch.setattr(it, "replace_config", lambda params, cfg: pushed.append(cfg) or "done")
    return pushed

def test_preview_no_difference_and_difference(monkeypatch):
    patch_backend(monkeypatch)
    assert it.preview_config(device="leaf1") == "leaf1: no difference between the rendered and the running configuration."
    patch_backend(monkeypatch, rendered=RENDERED + "vlan 40\n   name GUESTS\n")
    assert "+vlan 40" in it.preview_config(device="leaf1")

def test_preview_unknown_device_and_missing_artifact(monkeypatch):
    patch_backend(monkeypatch)
    assert it.preview_config(device="spine1").startswith("Error:")
    monkeypatch.setattr(it, "fetch_artifact", lambda device, **kw: (_ for _ in ()).throw(it.ArtifactNotReady("leaf1")))
    assert it.preview_config(device="leaf1").startswith("Error:") and "artifact" in it.preview_config(device="leaf1").lower()

def test_deploy_pushes_rendered_and_reports(monkeypatch):
    pushed = patch_backend(monkeypatch, rendered=RENDERED + "vlan 40\n   name GUESTS\n")
    out = it.deploy_config(device="leaf1")
    assert pushed and "GUESTS" in pushed[0] and out.startswith("leaf1:")

def test_deploy_errors_are_strings(monkeypatch):
    patch_backend(monkeypatch)
    monkeypatch.setattr(it, "replace_config", lambda params, cfg: (_ for _ in ()).throw(it.DeployError("ssh lost")))
    assert it.deploy_config(device="leaf1").startswith("Error:")

def event(name, result, inputs=None):
    return SimpleNamespace(tool_use={"name": name, "input": inputs or {}}, cancel_message=None, exception=None,
                           result={"status": "success", "content": [{"text": json.dumps(result)}]})

def test_show_links(capsys):
    hook = it.ShowInfrahubLinks(infrahub=None, base_url="http://localhost:8000")
    hook.session_branch = lambda: "agent/20261022-ab12"
    hook.show(event("node_upsert", {"id": "u1", "display_label": "GUESTS", "branch": "agent/20261022-ab12"}, {"kind": "IpamVLAN"}))
    hook.show(event("propose_changes", {"id": "pc1", "source_branch": "agent/20261022-ab12"}))
    hook.show(event("mutate_graphql", {"IpamVLANCreate": {"ok": True, "object": {"id": "u2"}}}))
    hook.show(event("get_nodes", {"nodes": []}))
    out = capsys.readouterr().out
    assert "http://localhost:8000/objects/IpamVLAN/u1?branch=agent/20261022-ab12" in out
    assert "http://localhost:8000/proposed-changes/pc1" in out
    assert "u2" in out and "agent/20261022-ab12" in out and out.count("[infrahub:") == 3

def test_show_links_never_raises(capsys):
    hook = it.ShowInfrahubLinks(infrahub=None, base_url="http://x")
    hook.show(SimpleNamespace(tool_use={"name": "node_upsert", "input": {}}, cancel_message=None, exception=None, result={"status": "error", "content": [{"text": "boom"}]}))
    hook.show(event("mutate_graphql", "not a dict"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_infrahub_tools.py -q`
Expected: FAIL, module missing.

- [ ] **Step 3: Implement `vlanlab/infrahub_tools.py`**

Import `fetch_artifact`, `ArtifactNotReady` from `vlanlab.infrahub_api` and `load_inventory`, `running_config`, `replace_config`, `DeployError` from `vlanlab.eos` as module names (the tests monkeypatch them here). `normalize` and `config_diff` with `difflib.unified_diff(..., fromfile="running", tofile="rendered", lineterm="")`. `preview_config` docstring tells the model it is read-only and shows the diff between Infrahub's rendered config and the switch; `deploy_config` docstring says it replaces the whole running configuration with Infrahub's artifact for that device, that the user confirms on the terminal, and that it takes no configuration text. Both resolve the device from the inventory (unknown → `Error: unknown device … Known devices: …`), fetch the artifact (`ArtifactNotReady` → `Error: no ready artifact for <device> in Infrahub; …`), never raise. `deploy_config` returns `f"{device}: configuration replaced and saved. {output}"`. `ShowInfrahubLinks.show`: ignore tools not in `INFRAHUB_WRITE_TOOLS`, cancelled or error results; parse the first JSON content block; `node_upsert` → `/objects/<input kind>/<id>?branch=<branch>`; `propose_changes` → `/proposed-changes/<id>`; `mutate_graphql` → collect every `object.id` found in the response and print them with the branch from `self.session_branch()` (which calls `self.infrahub.call_tool_sync(..., "get_session_info", {})` and returns `session_branch`, `"?"` on any failure). Everything inside one `try/except Exception` that prints nothing on failure.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_infrahub_tools.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add vlanlab/infrahub_tools.py tests/test_infrahub_tools.py && git commit -m "feat: preview_config/deploy_config tools and Infrahub link hook"
```

---

### Task 8: Guards (`vlanlab/guards.py`)

**Files:**
- Create: `vlanlab/guards.py`, `tests/test_guards.py`

**Interfaces:**
- Consumes: `DEPLOY_TOOL`, `fetch_artifact`, `ArtifactNotReady`, `load_inventory`, `config_diff` (all imported as module names for patching).
- Produces: `class DeployGuard(SteeringHandler)` (`name = "deploy-guard"`, `__init__(self, max_devices: int = 2)`, `check(self, tool_use: dict) -> str | None` pure given injected `rendered: str | None` through `self.render = fetch_artifact` and `self.inventory = load_inventory`, `start_turn`, `turn_calls`, `steer_before_tool`); `class ConfirmDeploy(HookProvider)` (`__init__(self, ask=input)`, `confirm(event)`, registered at `HookOrder.SDK_LAST`; prints the device and the diff from `self.preview(device)` = `preview_config`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_guards.py
from types import SimpleNamespace
from vlanlab import guards

GOOD = "hostname leaf1\n!\nusername admin privilege 15 secret admin\n!\ninterface Management0\n   ip address 172.20.20.11/24\n!\nend\n"
INV = {"leaf1": {"host": "172.20.20.11"}, "leaf2": {"host": "172.20.20.12"}}

def guard(rendered=GOOD, done=()):
    g = guards.DeployGuard(max_devices=2)
    g.render = lambda device, **kw: rendered if rendered is not None else (_ for _ in ()).throw(guards.ArtifactNotReady(device))
    g.inventory = lambda: INV
    g.turn_calls = lambda: [{"tool_name": "deploy_config", "status": "success", "tool_args": {"device": d}} for d in done]
    return g

def use(device="leaf1", name="deploy_config"):
    return {"name": name, "input": {"device": device}}

def test_allows_a_sane_rendering():
    assert guard().check(use()) is None

def test_refuses_unsafe_or_missing_renderings():
    assert "artifact" in guard(rendered=None).check(use()).lower()
    assert "hostname" in guard(rendered=GOOD.replace("hostname leaf1", "hostname leaf9")).check(use())
    assert "Management0" in guard(rendered=GOOD.replace("172.20.20.11/24", "10.0.0.1/24")).check(use())
    assert "admin" in guard(rendered=GOOD.replace("username admin privilege 15 secret admin\n", "")).check(use())
    assert guard().check(use(device="spine1"))

def test_caps_devices_per_turn():
    assert guard(done=("leaf1",)).check(use("leaf2")) is None
    assert guard(done=("leaf1", "leaf2")).check(use("leaf1"))          # third deploy in the turn
    assert guard(done=("leaf1",)).check(use("leaf1")) is None           # same device again counts once

def test_ignores_other_tools():
    assert guard(rendered=None).check(use(name="preview_config")) is None

def test_confirm_deploy(capsys):
    hook = guards.ConfirmDeploy(ask=lambda p: "y"); hook.preview = lambda d: "+vlan 40"
    e = SimpleNamespace(tool_use=use(), cancel_tool=False); hook.confirm(e); assert e.cancel_tool is False
    out = capsys.readouterr().out; assert "leaf1" in out and "+vlan 40" in out
    e = SimpleNamespace(tool_use=use(), cancel_tool=False); guards.ConfirmDeploy(ask=lambda p: "n").confirm(e); assert isinstance(e.cancel_tool, str)
    e = SimpleNamespace(tool_use=use(), cancel_tool="Tool call cancelled."); guards.ConfirmDeploy(ask=lambda p: (_ for _ in ()).throw(AssertionError())).confirm(e)
    def eof(p): raise EOFError
    e = SimpleNamespace(tool_use=use(), cancel_tool=False); h = guards.ConfirmDeploy(ask=eof); h.preview = lambda d: ""; h.confirm(e); assert isinstance(e.cancel_tool, str)

def test_hook_order_is_after_steering():
    from strands.hooks import HookOrder
    calls = []
    class Reg:
        def add_callback(self, et, cb, order=HookOrder.DEFAULT): calls.append(order)
    guards.ConfirmDeploy().register_hooks(Reg()); assert calls == [HookOrder.SDK_LAST]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_guards.py -q`
Expected: FAIL, module missing.

- [ ] **Step 3: Implement `vlanlab/guards.py`**

`DeployGuard.check`: not `DEPLOY_TOOL` → `None`; device not in inventory → reason; `self.render(device)` (`ArtifactNotReady` or empty → `"No ready artifact for <device> in Infrahub: nothing to deploy. Report it; do not retry."`); rendered must contain the line `hostname <device>`, a `username admin` line, and an `interface Management0` block whose next lines contain `ip address <inventory host>/`; then count distinct devices among successful `deploy_config` calls of the turn plus this one, refuse above `max_devices` with the `LimitDeletes` wording style. `steer_before_tool` prints `[guard: …]` and returns `Guide`; `start_turn`/`turn_calls` as in `strand_agents_lab`'s `LimitDeletes`; everything defensive (steering is fail-open). `ConfirmDeploy.confirm`: skip other tools and already-cancelled calls; print `"\n  DEPLOY {device}: replace the running configuration with Infrahub's rendering"` then the preview diff (indented), `ask("  Confirm? [y/N] ")`; not `y` or `EOFError` → `event.cancel_tool = "Deployment refused by the user. Do not retry it; tell the user it was not done."`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_guards.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add vlanlab/guards.py tests/test_guards.py && git commit -m "feat: DeployGuard steering and ConfirmDeploy hook"
```

---

### Task 9: Skills

**Files:**
- Create: `skills/infrahub-change/SKILL.md`, `skills/deploy-config/SKILL.md`, `skills/vlan-check/SKILL.md`, `tests/test_skills.py`

**Interfaces:**
- Produces: three skills loadable by `AgentSkills(skills=["skills"], strict=True)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skills.py
import pathlib, re
ROOT = pathlib.Path(__file__).resolve().parents[1]

def fm(p):
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S); assert m, p
    return dict(l.split(": ", 1) for l in m.group(1).splitlines())

def test_skills_frontmatter_and_tools():
    change, deploy, check = (ROOT / f"skills/{n}/SKILL.md" for n in ("infrahub-change", "deploy-config", "vlan-check"))
    assert fm(change)["name"] == "infrahub-change" and fm(deploy)["name"] == "deploy-config" and fm(check)["name"] == "vlan-check"
    t = change.read_text(); assert all(k in t for k in ("mutate_graphql", "get_session_info", "propose_changes", "IpamVLANCreate", "untagged_vlan"))
    t = deploy.read_text(); assert all(k in t for k in ("preview_config", "deploy_config")) and "no difference" in t
    t = check.read_text(); assert "send_show_command" in t and "show vlan" in t

def test_agent_skills_plugin_loads_them():
    from strands import AgentSkills
    AgentSkills(skills=[str(ROOT / "skills")], strict=True)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_skills.py -q`
Expected: FAIL, files missing.

- [ ] **Step 3: Write the three skills**

`infrahub-change` (use when the user asks to add, change or remove intent: VLANs, interface assignments): read the schema of the kinds involved with `get_schema` if unsure; create or change nodes with `mutate_graphql` when a relationship is involved (example mutation `IpamVLANCreate(data: {name: {value: "GUESTS"}, vlan_id: {value: 40}, status: {value: "active"}, vlan_group: {hfid: ["lab-vlans"]}}) { ok object { id } }` and `InterfacePhysicalUpdate(data: {hfid: ["leaf1", "Ethernet3"], untagged_vlan: {hfid: ["GUESTS"]}}) { ok object { id } }`, checking the HFID shapes with `get_schema`), `node_upsert` for scalar-only changes; after the first write call `get_session_info` and tell the user the branch; verify with `get_nodes` on that branch; finish with `propose_changes` (title, description) and give the user the link; never write to the default branch; stop there, the human merges.
`deploy-config` (use when asked to deploy, apply, push, or re-align a switch): for each device, `preview_config`; if "no difference", say so and skip; else show the diff and call `deploy_config` once; report; never send configuration by any other means; after deploying, offer `vlan-check`.
`vlan-check` (use when asked to check, verify or audit VLANs): `send_show_command` with `show vlan` and `use_textfsm: true` per device (`list_devices` first if needed); table per device; compare with Infrahub's VLANs (`get_nodes` kind `IpamVLAN`) when asked for compliance.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_skills.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add skills tests/test_skills.py && git commit -m "feat: infrahub-change, deploy-config and vlan-check skills"
```

---

### Task 10: The agent and `.mcp.json`

**Files:**
- Create: `agent.py`, `.mcp.json`, `tests/test_agent.py`

**Interfaces:**
- Produces: `build_agent() -> Agent`; `uv run python agent.py [question]`; `uv run python agent.py --list-tools`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent.py
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_mcp_json():
    cfg = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert set(cfg) == {"infrahub", "netmiko"}
    assert "infrahub-mcp==1.2.0" in " ".join(cfg["infrahub"]["args"]) and "agent/{date}-{hex}" in " ".join(cfg["infrahub"]["args"])
    assert "netmiko-mcp==0.2.0" in " ".join(cfg["netmiko"]["args"]) and "netmiko/netmiko-mcp.yml" in " ".join(cfg["netmiko"]["args"])

def test_build_agent_wiring(monkeypatch):
    import agent
    monkeypatch.setattr(agent.MCPClient, "load_servers", classmethod(lambda cls, cfg: []))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test"); monkeypatch.setenv("INFRAHUB_ADDRESS", "http://localhost:8000")
    a = agent.build_agent()
    assert {"preview_config", "deploy_config"} <= set(a.tool_names)
    assert "deploy-guard" in a._plugin_registry._plugins
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_agent.py -q`
Expected: FAIL, files missing.

- [ ] **Step 3: Write `.mcp.json`**

```json
{"mcpServers": {
  "infrahub": {"command": "sh", "args": ["-c", "set -a; . ./.env; INFRAHUB_MCP_BRANCH_PATTERN='agent/{date}-{hex}' exec uvx infrahub-mcp==1.2.0"]},
  "netmiko":  {"command": "sh", "args": ["-c", "NETMIKO_MCP_CONFIG=netmiko/netmiko-mcp.yml exec uvx --from netmiko-mcp==0.2.0 netmiko-mcp"]}
}}
```

- [ ] **Step 4: Write `agent.py`**

Docstring: what it is, the three ways to run it. `SYSTEM_PROMPT`: network automation assistant; Infrahub is the source of truth and generates the switch configurations; changes of intent go to Infrahub through its tools, always on the session branch, and end with a proposed change the human merges; switches are read with the netmiko tools and written only with `deploy_config`, which deploys Infrahub's rendering and nothing else; never send configuration lines yourself; use the skills; be concise; answer in the user's language. `build_agent()`: `servers = MCPClient.load_servers(".mcp.json")`; `infrahub = next((s for s in servers if "infrahub" in getattr(s, "name", "")), servers[0] if servers else None)` (or match by tool list later; the hook only needs `call_tool_sync`); `AnthropicModel(model_id="claude-opus-5-5", max_tokens=16000)`; `Agent(model, tools=[*servers, preview_config, deploy_config], system_prompt, callback_handler=chat_handler, context_manager="auto", hooks=[ShowInfrahubLinks(infrahub, os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000").rstrip("/")), ConfirmDeploy()], plugins=[AgentSkills(skills=["skills"], strict=True), DeployGuard()])`. `chat_handler`, `chat`, `main` ported from `strand_agents_lab/netbox_agent.py`; `--list-tools` prints `agent.tool_names` one per line then `cleanup()`; the streamed tool line reads `[tool: <name>]`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_agent.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add agent.py .mcp.json tests/test_agent.py && git commit -m "feat: the agent, two MCP servers plus preview/deploy tools, guards and skills wired"
```

---

### Task 11: `install.sh`, `uninstall.sh`, and the running-config alignment

**Files:**
- Create: `install.sh`, `uninstall.sh`, `tests/test_install_sh.py`
- Modify: `infrahub/templates/eos_leaf.j2`, `tests/fixtures/eos_leaf/output.txt` (alignment), `vlanlab/infrahub_tools.py` `normalize` if cEOS headers need more rules

**Interfaces:**
- Produces: `sh install.sh [--check-prereqs]`; `sh uninstall.sh [--purge]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_install_sh.py
import pathlib, re, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_install_sh_static():
    s = (ROOT / "install.sh").read_text()
    assert s.startswith("#!/bin/sh") and "set -e" in s
    for pin in ("infrahub.opsmill.io/1.11.9", "netmiko-mcp==0.2.0", "ceos:lab", "clab/vlan-lab.clab.yml", "infrahubctl schema load", "infrahubctl object load", "repository add", "--read-only"):
        assert pin in s, pin
    assert re.search(r"sudo containerlab", s) and not re.search(r"sudo (uv|docker|curl)", s)
    for f in ("install.sh", "uninstall.sh"):
        assert subprocess.run(["sh", "-n", str(ROOT / f)]).returncode == 0

def test_install_sh_reports_all_missing_prereqs():
    r = subprocess.run(["sh", str(ROOT / "install.sh"), "--check-prereqs"], cwd=ROOT, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "images/" in out and "containerlab" in out
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_install_sh.py -q`
Expected: FAIL, script missing.

- [ ] **Step 3: Write `install.sh`**

POSIX sh, `set -e`, `cd "$(dirname "$0")"`, `step()` helper, `--check-prereqs` runs step 0 only. Steps printed `== N/9 …`:
0. Prerequisites, all checked before exiting: `docker info` without sudo, `docker compose version`, `containerlab version` (print the official install line), `uv`, `git`, `curl`, exactly one archive among `images/cEOS64-lab-*.tar*`, `images/cEOS-lab-*.tar*`, `images/cEOSarm-lab-*.tar*` (none → Arista download URL and location; several → lexically last, say so), RAM ≥ 16 GB (warning only). Any gap → exit 1 after the list.
1. `.env`: keep or generate `INFRAHUB_INITIAL_ADMIN_TOKEN` (uuid), `INFRAHUB_INITIAL_AGENT_TOKEN` (uuid), `INFRAHUB_SECURITY_SECRET_KEY` (≥ 32 chars); set `INFRAHUB_API_TOKEN=$INFRAHUB_INITIAL_ADMIN_TOKEN`, `INFRAHUB_ADDRESS=http://localhost:8000`; keep or default `INFRAHUB_REPO_URL=https://github.com/thomas-rotszyld-nc/blog_networking_agent_strand`, `INFRAHUB_REPO_REF=main`; keep `ANTHROPIC_API_KEY` or write it empty with a comment.
2. Infrahub: `curl -sL https://infrahub.opsmill.io/1.11.9 -o infrahub/docker-compose.yml` if missing; `docker compose -p vlan-lab -f infrahub/docker-compose.yml --env-file .env up -d`; wait for `GET /api/config` (15 minutes max).
3. Schema: `uv sync` then `uv run infrahubctl schema load infrahub/schema --wait 60`.
4. Objects: `uv run infrahubctl object load infrahub/objects`.
5. Repository: if `uv run infrahubctl repository list` lacks `blog-lab`, `uv run infrahubctl repository add blog-lab "$INFRAHUB_REPO_URL" --read-only --ref "$INFRAHUB_REPO_REF"`; then `uv run python scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated --timeout 600`.
6. netmiko-mcp: `uv tool install --quiet netmiko-mcp==0.2.0`; write `netmiko/netmiko-mcp.yml` (`inventory_type: netmiko_tools`, absolute `inventory_file`, `command_file`, `audit_log_file` under `$PWD/netmiko/`), `netmiko/.netmiko.yml` (leaf1, leaf2, `arista_eos`, hosts, admin/admin, group `leafs`), `netmiko/commands.yml` (`allowed_commands: ["show vlan*", "show running-config*"]`, `denied_commands: []`).
7. Containerlab: `docker image inspect ceos:lab` or `docker import "$ARCHIVE" ceos:lab`; `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure`; wait until `uv run python -c` with `vlanlab.eos.running_config` answers for both leafs (10 s retry, 5 minutes max).
8. Agent: `uv run python agent.py --list-tools` must list `preview_config`, `deploy_config`, `send_show_command`, `get_nodes`, `node_upsert`.
9. Checks `[ok]`/`[KO]`: three `IpamVLAN` on Infrahub; two artifacts Ready; `show vlan` on each leaf contains `USERS`, `VOICE`, `IOT`; `preview_config` returns "no difference" for both leafs. Final summary: Infrahub URL and admin credentials, `uv run python agent.py`, reminder for `ANTHROPIC_API_KEY`.

- [ ] **Step 4: Write `uninstall.sh`**

`sudo containerlab destroy -t clab/vlan-lab.clab.yml --cleanup` (ignore failure), `docker compose -p vlan-lab -f infrahub/docker-compose.yml down` (`--purge` adds `-v`), keep images, `.env`, `clab/generated`; print what was kept.

- [ ] **Step 5: Run the static tests**

Run: `uv run pytest tests/test_install_sh.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Run the real thing in the dev VM, then align the template with the running-config**

Run: `sh uninstall.sh --purge; sh install.sh`
Expected: steps 0 to 8 `ok`. If check 9 "no difference" fails: `docker exec clab-vlan-lab-leaf1 Cli -c "show running-config" > /tmp/running.txt`, compare with `clab/generated/leaf1.cfg` through `vlanlab.infrahub_tools.config_diff`, and for every line cEOS adds by default either add it to the template (so Infrahub's intent includes it) or, for pure cosmetics (`! Command:` headers, `! device:` lines, `! boot system`), extend `normalize`. Re-run `uv run pytest tests/test_transforms.yml` after each template change (fixture `output.txt` updated), push the template to GitHub, `sh scripts/reimport.sh`, `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure`, until `preview_config` reports "no difference" for both leafs. Then run `sh install.sh` a second time: nothing recreated, all `[ok]`. Record first-run duration and cEOS boot time.

- [ ] **Step 7: Commit**

```bash
git add install.sh uninstall.sh tests/test_install_sh.py infrahub/templates tests/fixtures vlanlab/infrahub_tools.py && git commit -m "feat: one-shot install.sh/uninstall.sh; template aligned with cEOS running-config"
```

---

### Task 12: `drift.sh`

**Files:**
- Create: `drift.sh`, `tests/test_drift_sh.py`

**Interfaces:**
- Produces: `sh drift.sh` renames VLAN 20 to `VOIP` and adds VLAN 99 `LEGACY` on leaf2, prints `show vlan` of both leafs; `sh drift.sh --reset` redeploys Containerlab from `clab/generated` and waits for SSH.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift_sh.py
import pathlib, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_drift_sh_encodes_the_drift():
    s = (ROOT / "drift.sh").read_text()
    assert subprocess.run(["sh", "-n", str(ROOT / "drift.sh")]).returncode == 0
    assert "clab-vlan-lab-leaf2" in s and "name VOIP" in s and "vlan 99" in s and "name LEGACY" in s
    assert "--reset" in s and "--reconfigure" in s
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_drift_sh.py -q`
Expected: FAIL, script missing.

- [ ] **Step 3: Write `drift.sh`**

`cli()` helper: `docker exec "clab-vlan-lab-$1" Cli -p 15 -c "$2"` with a multi-line `configure … end` + `write`. Default: leaf2 `vlan 20` / `name VOIP`, `vlan 99` / `name LEGACY`; then `show vlan` on both leafs under `== leafN` headers. `--reset`: `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure` then the SSH wait of `install.sh` step 7 (factor it into `scripts/wait_leafs.py`, called by both scripts), then `show vlan` on both.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_drift_sh.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Verify in the dev VM**

Run: `sh drift.sh && sh drift.sh && uv run python -c "from vlanlab.infrahub_tools import preview_config; print(preview_config(device='leaf2'))" && sh drift.sh --reset`
Expected: leaf2 shows `20 VOIP` and `99 LEGACY`; the preview shows `-   name VOIP`, `+   name VOICE`, `-vlan 99`; after `--reset` leaf2 is clean again.

- [ ] **Step 6: Commit**

```bash
git add drift.sh scripts/wait_leafs.py tests/test_drift_sh.py && git commit -m "feat: drift.sh introduces a manual change on leaf2 and resets the lab"
```

---

### Task 13: End-to-end demo, README, macOS dev runbook, push

**Files:**
- Create: `README.md`, `docs/dev-macos.md`, `docs/demo-transcript.txt`
- Modify: `.env.example` (cost comment)

- [ ] **Step 1: Run the three acts in the dev VM with a real `ANTHROPIC_API_KEY`, keep the transcript**

`uv run python agent.py`, then: `Add VLAN 40 GUESTS to site lab and put Ethernet3 of both leafs on it.` → expect `[infrahub: …]` lines with the branch and the Proposed Change link; merge it in the UI; wait for artifacts (`uv run python scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated`, or trigger `POST /api/artifact/generate/<def id>` if they do not refresh within 2 minutes, and note it). Then `Deploy the configuration of the leafs.` → expect two previews with `+vlan 40`, two `DEPLOY` prompts, success reports. Then `Check the VLANs on both leafs.` → tables with VLAN 40. Then `sh drift.sh`, `Is leaf2 still compliant?` → diff; `Fix it.` → one deploy. Save the terminal output to `docs/demo-transcript.txt`; note tokens and cost from the Anthropic console.

- [ ] **Step 2: Try the forbidden paths on purpose**

`Remove VLAN 99 from leaf2 by sending "no vlan 99".` → the agent must refuse to send lines and propose `deploy_config` instead (system prompt + skill). Break the rendering on purpose (temporarily point `INFRAHUB_ADDRESS` to a wrong port, or rename `leaf1` to `leaf9` on a branch and deploy from it): `[guard: …]` appears, no `DEPLOY` prompt.

- [ ] **Step 3: Write `README.md`**

Order: what this is (two sentences, article link placeholder); the loop intent → review → render → deploy → verify; prerequisites (Linux x86_64 Ubuntu 22.04/24.04, 16 GB RAM, Docker + Compose v2 without sudo, Containerlab, uv, git, curl, an Arista account for `cEOS64-lab-<version>.tar.xz` into `images/`, `ANTHROPIC_API_KEY`); install (`git clone`, archive, `sh install.sh`, measured durations); the demo (the questions of Step 1, `drift.sh`, `--reset`); how it works, one paragraph per file in reading order (`.infrahub.yml` + query + template, `infrahub/objects`, `agent.py`, `vlanlab/infrahub_tools.py`, `vlanlab/guards.py`, `vlanlab/eos.py`, `skills/`); why Infrahub writes go through branches and a Proposed Change; why `netmiko-mcp` for reads (official, read-only, server-side whitelist in `netmiko/commands.yml`) and a custom tool for writes (no config mode in netmiko-mcp; the tool deploys Infrahub's rendering only); forking (`INFRAHUB_REPO_URL`, and that a read-only repository needs `sh scripts/reimport.sh` after a push); cost of a demo session; tested-on statement (arm64 under OrbStack with the cEOS ARM build; x86_64 is the documented target and has not been run by the author yet); cleanup; licence and attribution (schema-library Apache-2.0 copies).

- [ ] **Step 4: Write `docs/dev-macos.md`**

OrbStack Linux arm64 VM (16 GB, 6 CPUs), install Docker, Containerlab, uv, git; clone the repo in the VM; `cEOSarm-lab-*.tar.xz` in `images/`; `install.sh`; reach Infrahub from macOS through the VM address; the dev loop (edit template → `uv run pytest tests/test_transforms.yml` → push to a dev branch → `INFRAHUB_REPO_REF=<branch>` → `sh scripts/reimport.sh` → `sudo containerlab deploy --reconfigure`); every ARM-image limit met in Tasks 5 to 13 with its workaround.

- [ ] **Step 5: Full test suite and trace check**

Run: `uv run pytest -q && sh -n install.sh && sh -n drift.sh && sh -n uninstall.sh && sh -n scripts/reimport.sh && grep -rIl --exclude-dir=.git --exclude-dir=.venv --exclude-dir=docs -e c9500 -e NGW -e 5trandagent5lab -e Europe/Paris -e netbox . || true`
Expected: all tests pass; the grep prints nothing.

- [ ] **Step 6: Commit and push**

```bash
git add README.md docs .env.example && git commit -m "docs: README, macOS dev runbook, demo transcript" && git push -u origin main
```
