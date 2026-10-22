# VLAN Drift Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public companion repo that a reader installs with `sh install.sh` and that lets a Strands agent audit, then fix, VLAN drift between NetBox and two Arista cEOS switches running under Containerlab.

**Architecture:** One Strands agent (`agent.py`) gets its tools from two MCP servers (`netbox-mcp-rw` for NetBox, the official `netmiko-mcp` for `show` commands) and one in-repo `@tool` (`configure_vlans`, Netmiko config push). Guardrails are code: a steering handler whitelists `vlan N` / `name X` and caps VLANs per turn; a hook asks the user to confirm every device or NetBox write; a hook prints a link to every NetBox object written. Everything else is installation: NetBox by Compose and seeded over REST, the switches by Containerlab from a startup-config kept in the repo, drift introduced by a separate script.

**Tech Stack:** Python 3.12 + uv, `strands-agents[anthropic]` 1.61.1, `netmiko` 4.7, `netmiko-mcp` 0.2.0 (PyPI), `netbox-mcp-rw` at commit `96705f8ff24b96e98f6d82e6f4fde399e5ac57d9`, NetBox `v4.4.10-3.4.2` (Docker Compose), Containerlab ≥ 0.81, Arista cEOS-lab, pytest.

**Spec:** `docs/superpowers/specs/2026-10-22-vlan-drift-lab-design.md`

## Global Constraints

- Repo language is English (code, comments, README, skills, system prompt). Licence MIT.
- Nothing from `strand_agents_lab` data may appear: no `c9500`, `poc`, `NGW`, `strand-agents-lab`, `5trandagent5lab`, `Europe/Paris`, `*-Lab-2026-password`, users `bidder`/`drivers`/`evaluators`.
- Pinned versions: `strands-agents[anthropic]>=1.61.1,<2`, `netmiko>=4.7,<5`, `netmiko-mcp==0.2.0`, netbox-mcp-rw commit `96705f8ff24b96e98f6d82e6f4fde399e5ac57d9`, NetBox image `netboxcommunity/netbox:v4.4.10-3.4.2`.
- Fixed values: site slug `lab`; devices `leaf1`/`leaf2`; management IPs `172.20.20.11`/`172.20.20.12` on Containerlab's default `clab` network `172.20.20.0/24`; VLANs `10 USERS`, `20 VOICE`, `30 IOT`; access ports `Ethernet1..3` untagged on 10, 20, 30; cEOS credentials `admin`/`admin`; cEOS image tag `ceos:lab`; Containerlab lab name `vlan-lab` (containers `clab-vlan-lab-leaf1`, `clab-vlan-lab-leaf2`); NetBox port `8091` (override `NETBOX_PORT`); Compose project `vlan-lab`, network subnet `172.30.30.0/24`.
- Drift: leaf1 lacks VLAN 30; leaf2 has VLAN 20 named `VOIP`; leaf2 has VLAN 99 `LEGACY`.
- Guard limits: only `vlan <1-4094>` and `name <[A-Za-z0-9_-]{1,32}>`; at most 5 distinct VLAN ids configured per turn; no deletion ever.
- The confirmation hooks run after steering (`HookOrder.SDK_LAST`) and skip a call already cancelled.
- `sudo` only around `containerlab` commands; everything else runs as the user.
- Secrets and generated files are git-ignored: `.env`, `netmiko/*` (except `.gitkeep`), `images/*` (except `.gitkeep`), `netbox-mcp-rw/`, `clab/clab-vlan-lab/`.
- Every script is idempotent and exits non-zero on the first failure with a message naming the fix.

## Review Focus

1. The model sends `VLAN 30` or `vlan  30 ` (case, spacing): the guard must normalise before matching, not refuse a correct intent. Test in Task 7.
2. A leaf is unreachable (SSH timeout, refused auth): `configure_vlans` returns an error string the model can report, never a traceback that ends the turn. Test in Task 6.
3. Two `configure_vlans` calls in one turn whose VLAN ids add up past 5 are refused on the second call, and the count resets on the next turn. Test in Task 7.
4. The chat runs without a terminal (piped stdin, one-shot mode in CI): every confirmation hook refuses instead of hanging or raising. Test in Task 7 and Task 5.
5. `images/` holds zero or several cEOS archives: `install.sh` stops with the download instructions, or picks one deterministically and says which. Verified in Task 10.

---

### Task 1: Repository skeleton

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.python-version`, `LICENSE`, `.env.example`, `images/.gitkeep`, `netmiko/.gitkeep`, `vlanlab/__init__.py`, `tests/__init__.py`, `tests/test_skeleton.py`

**Interfaces:**
- Produces: the package name `vlanlab` every later module lives in; `uv run pytest` as the test command.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skeleton.py
def test_dependencies_import():
    import netmiko, strands, strands.models.anthropic  # noqa: F401
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/blog_networking_agent_strand && uv run pytest tests/test_skeleton.py -q`
Expected: fails (no pyproject, or `ModuleNotFoundError: netmiko`).

- [ ] **Step 3: Write `pyproject.toml`**

Project `vlan-drift-lab`, `requires-python = ">=3.12"`, dependencies `strands-agents[anthropic]>=1.61.1,<2` and `netmiko>=4.7,<5`, dev dependency group `pytest>=8`, `license = "MIT"`, `[project.urls] Repository = "https://github.com/thomas-rotszyld-nc/blog_networking_agent_strand"`. `.python-version` is `3.12`.

- [ ] **Step 4: Write `.gitignore`, `LICENSE` (MIT, year 2026, the repo owner's name), `.env.example`, the two `.gitkeep`, the two empty `__init__.py`**

`.gitignore` covers: `__pycache__/`, `*.py[oc]`, `.venv`, `.env`, `netbox-mcp-rw/`, `netmiko/*` + `!netmiko/.gitkeep`, `images/*` + `!images/.gitkeep`, `clab/clab-vlan-lab/`, `.pytest_cache/`.
`.env.example` lists, with a one-line comment each and empty values: `ANTHROPIC_API_KEY`, `NETBOX_URL`, `NETBOX_TOKEN`, `NETBOX_RW_TOKEN`, `NETBOX_SUPERUSER_TOKEN`, `NETBOX_SECRET_KEY`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv sync --group dev && uv run pytest tests/test_skeleton.py -q`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: repository skeleton (uv project, MIT licence, ignores)"
```

---

### Task 2: NetBox by Compose

**Files:**
- Create: `docker-compose.yml`, `netbox/netbox.env`, `netbox/bootstrap_token.sh`, `tests/test_compose.py`

**Interfaces:**
- Consumes: `.env` variables `NETBOX_SUPERUSER_TOKEN`, `NETBOX_SECRET_KEY`, `NETBOX_PORT` (written by Task 10's `install.sh`; for manual runs the developer exports them).
- Produces: NetBox at `http://localhost:${NETBOX_PORT:-8091}/`, admin `admin`/`admin`, superuser API token `NETBOX_SUPERUSER_TOKEN`; `sh netbox/bootstrap_token.sh` creates that token if the image did not.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compose.py
import re, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_compose_has_no_lab_traces_and_pins_the_image():
    text = (ROOT / "docker-compose.yml").read_text() + (ROOT / "netbox/netbox.env").read_text()
    assert "netboxcommunity/netbox:v4.4.10-3.4.2" in text
    assert "172.30.30.0/24" in text
    assert "name: vlan-lab" in text
    for trace in ("strand", "poc", "5trandagent5lab", "europe/paris"):
        assert trace not in text.lower()

def test_secrets_come_from_env_not_files():
    env = (ROOT / "netbox/netbox.env").read_text()
    assert not re.search(r"^SUPERUSER_API_TOKEN=\S", env, re.M)
    assert not re.search(r"^SECRET_KEY=\S", env, re.M)
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "SUPERUSER_API_TOKEN: ${NETBOX_SUPERUSER_TOKEN}" in compose
    assert "SECRET_KEY: ${NETBOX_SECRET_KEY}" in compose
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compose.py -q`
Expected: FAIL, files missing.

- [ ] **Step 3: Write `docker-compose.yml`**

Same service graph as `strand_agents_lab/docker-compose.yml` (Postgres 16, two Redis, `netbox`, `netbox-worker`, healthchecks, volumes), with: `name: vlan-lab`; a top-level `networks: default: ipam: config: [subnet: 172.30.30.0/24]`; `environment:` on `netbox` and `netbox-worker` adding `SUPERUSER_API_TOKEN: ${NETBOX_SUPERUSER_TOKEN}` and `SECRET_KEY: ${NETBOX_SECRET_KEY}` on top of `env_file: netbox/netbox.env`; port `"${NETBOX_PORT:-8091}:8080"`. Header comment: what it is, `sh install.sh`, `docker compose down [-v]`.

- [ ] **Step 4: Write `netbox/netbox.env` and `netbox/bootstrap_token.sh`**

`netbox.env`: the DB/Redis values of the existing file, `ALLOWED_HOSTS=*`, `SKIP_SUPERUSER=false`, `SUPERUSER_NAME=admin`, `SUPERUSER_EMAIL=admin@lab.local`, `SUPERUSER_PASSWORD=admin`, `TIME_ZONE=UTC`; no `SECRET_KEY`, no `SUPERUSER_API_TOKEN` lines.
`bootstrap_token.sh`: the existing script, reading the token from `.env` (`NETBOX_SUPERUSER_TOKEN`) instead of `netbox.env`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_compose.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Verify the stack boots (in the dev VM, Docker available)**

Run:
```bash
export NETBOX_SUPERUSER_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(20))') NETBOX_SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')
docker compose up -d && until curl -sf http://localhost:8091/login/ >/dev/null; do sleep 5; done && sh netbox/bootstrap_token.sh && curl -s -H "Authorization: Token $NETBOX_SUPERUSER_TOKEN" http://localhost:8091/api/status/ | head -c 200
```
Expected: JSON with `"netbox-version": "4.4.10"`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml netbox tests/test_compose.py && git commit -m "feat: NetBox 4.4 by Compose, secrets from .env"
```

---

### Task 3: NetBox seed

**Files:**
- Create: `netbox/seed.py`, `tests/test_seed.py`

**Interfaces:**
- Consumes: env `NETBOX_URL`, `NETBOX_TOKEN` (superuser), `MCP_TOKEN`, `MCP_RW_TOKEN`.
- Produces: `seed.DESIRED` (module constant, the intended state, importable without network); `python netbox/seed.py` idempotent. Site slug `lab`, devices `leaf1`/`leaf2`, VLANs, interfaces and primary IPs as in Global Constraints; users `mcp` (view only) and `mcp-rw` (view + `add`/`change` on `ipam.vlan` and `dcim.interface`, no delete).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed.py
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("seed", pathlib.Path(__file__).resolve().parents[1] / "netbox/seed.py")
seed = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed)

def test_desired_state_matches_the_scenario():
    assert seed.DESIRED["site"] == {"name": "Lab", "slug": "lab"}
    assert seed.DESIRED["vlans"] == [(10, "USERS"), (20, "VOICE"), (30, "IOT")]
    assert [d["name"] for d in seed.DESIRED["devices"]] == ["leaf1", "leaf2"]
    assert [d["mgmt_ip"] for d in seed.DESIRED["devices"]] == ["172.20.20.11/24", "172.20.20.12/24"]
    assert seed.DESIRED["access_ports"] == {"Ethernet1": 10, "Ethernet2": 20, "Ethernet3": 30}

def test_rw_permissions_cannot_delete():
    for perm in seed.PERMISSIONS["mcp-rw"]:
        assert "delete" not in perm["actions"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_seed.py -q`
Expected: FAIL, file missing.

- [ ] **Step 3: Write `netbox/seed.py`**

Keep the `api()` and `get_or_create()` helpers of the existing seed (stdlib only). Define `DESIRED` and `PERMISSIONS` as module constants; `main()` creates in order: site; manufacturer `Arista`; device type `cEOS-lab` (slug `ceos-lab`); device role `access-switch`; platform `Arista EOS` (slug `arista-eos`); the three VLANs with `site`, `status: active`; the two devices (`status: active`, role, type, site, platform); per device, interface `Management0` (type `1000base-t`, `mgmt_only: true`) and `Ethernet1..3` (type `1000base-t`, `mode: access`, `untagged_vlan` from `DESIRED["access_ports"]`); the IP address `mgmt_ip` assigned to `Management0` (`assigned_object_type: dcim.interface`) and set as the device's `primary_ip4`; users `mcp`/`mcp-rw` with a random password (`secrets.token_urlsafe(16)`, not printed), their tokens from `MCP_TOKEN`/`MCP_RW_TOKEN`, and permissions `lab-read-all` (view on `dcim.site, dcim.device, dcim.interface, dcim.devicetype, dcim.devicerole, dcim.platform, dcim.manufacturer, ipam.vlan, ipam.vlangroup, ipam.ipaddress, core.objectchange`, both users) and `lab-rw-vlans-interfaces` (`view, add, change` on `ipam.vlan, dcim.interface`, user `mcp-rw`). Permissions are PATCHed on every run so re-runs refresh them.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_seed.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Verify against the running NetBox of Task 2**

Run: `NETBOX_URL=http://localhost:8091 NETBOX_TOKEN=$NETBOX_SUPERUSER_TOKEN MCP_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(20))') MCP_RW_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(20))') uv run python netbox/seed.py && uv run python netbox/seed.py`
Expected: first run prints the created objects, second run creates nothing; `curl -s -H "Authorization: Token $MCP_TOKEN" 'http://localhost:8091/api/ipam/vlans/?site=lab' | python3 -c 'import sys,json;print(json.load(sys.stdin)["count"])'` prints `3`.

- [ ] **Step 6: Commit**

```bash
git add netbox/seed.py tests/test_seed.py && git commit -m "feat: seed NetBox with the lab site, two leafs, three VLANs and MCP users"
```

---

### Task 4: Containerlab topology and cEOS startup-config

**Files:**
- Create: `clab/vlan-lab.clab.yml`, `clab/ceos.cfg`, `tests/test_clab.py`

**Interfaces:**
- Produces: `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure` brings up `leaf1` (172.20.20.11) and `leaf2` (172.20.20.12), SSH `admin`/`admin`, with the three VLANs and access ports; `--reconfigure` is the reset primitive Task 11 relies on.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clab.py
import pathlib, yaml
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_topology():
    topo = yaml.safe_load((ROOT / "clab/vlan-lab.clab.yml").read_text())
    assert topo["name"] == "vlan-lab"
    nodes = topo["topology"]["nodes"]
    assert nodes["leaf1"]["mgmt-ipv4"] == "172.20.20.11" and nodes["leaf2"]["mgmt-ipv4"] == "172.20.20.12"
    assert topo["topology"]["kinds"]["arista_ceos"] == {"image": "ceos:lab", "startup-config": "ceos.cfg"}

def test_startup_config_matches_netbox():
    cfg = (ROOT / "clab/ceos.cfg").read_text()
    for vid, name in ((10, "USERS"), (20, "VOICE"), (30, "IOT")):
        assert f"vlan {vid}\n   name {name}" in cfg
    for port, vid in (("Ethernet1", 10), ("Ethernet2", 20), ("Ethernet3", 30)):
        assert f"interface {port}\n   switchport access vlan {vid}" in cfg
    assert "{{ .ShortName }}" in cfg and "{{ .MgmtIPv4Address }}" in cfg
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_clab.py -q`
Expected: FAIL, files missing (pyyaml comes with netmiko).

- [ ] **Step 3: Write `clab/vlan-lab.clab.yml`**

`name: vlan-lab`; `topology.kinds.arista_ceos: {image: ceos:lab, startup-config: ceos.cfg}`; nodes `leaf1`, `leaf2` of kind `arista_ceos` with their `mgmt-ipv4`; one link `leaf1:eth1 <-> leaf2:eth1` so Ethernet1 exists on both. No `mgmt` block (default `clab` network).

- [ ] **Step 4: Write `clab/ceos.cfg`**

Start from Containerlab's default cEOS template (`nodes/ceos/ceos.cfg` in srl-labs/containerlab: hostname, `username admin privilege 15 secret admin`, routing model, default route, `interface {{ .MgmtIntf }}` with `{{ .MgmtIPv4Address }}/{{ .MgmtIPv4PrefixLength }}`, management APIs), dropping the VRF branches, and add after the hostname block the three `vlan N / name X` stanzas and the three `interface EthernetN / switchport access vlan N` stanzas with the exact indentation the test expects (three spaces). One file serves both leafs: the template variables carry the per-node values.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_clab.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Verify in the dev VM (cEOS archive imported as `ceos:lab`)**

Run: `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure && sleep 90 && docker exec clab-vlan-lab-leaf1 Cli -c "show vlan"`
Expected: a table with VLANs 1, 10 USERS, 20 VOICE, 30 IOT. Note the time cEOS takes to answer SSH; Task 10 uses it.

- [ ] **Step 7: Commit**

```bash
git add clab tests/test_clab.py && git commit -m "feat: Containerlab topology with two cEOS leafs and a shared startup-config"
```

---

### Task 5: NetBox hooks (confirmation and write links)

**Files:**
- Create: `vlanlab/netbox_hooks.py`, `tests/test_netbox_hooks.py`

**Interfaces:**
- Produces: `object_line(object_type: str, obj: dict) -> str`; `objects_of(result: dict) -> list[dict]`; `class ConfirmNetboxWrites(HookProvider)` with `__init__(self, netbox: MCPClient, ask: Callable[[str], str] = input)` and `register_hooks` at `order=HookOrder.SDK_LAST`; `class ShowWriteLinks(HookProvider)`; constants `NETBOX_WRITE_TOOLS: dict[str, str]` (`netbox_create_object`/`netbox_bulk_create_objects` → `"created"`, `netbox_update_object`/`netbox_bulk_update_objects` → `"updated"`, `netbox_delete_object`/`netbox_bulk_delete_objects` → `"deleted"`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_netbox_hooks.py
import json
from types import SimpleNamespace
from vlanlab import netbox_hooks as nh

def result_of(payload, status="success"):
    return {"status": status, "content": [{"text": json.dumps(payload)}]}

def test_objects_of_handles_object_list_and_junk():
    assert nh.objects_of(result_of({"id": 1})) == [{"id": 1}]
    assert nh.objects_of(result_of([{"id": 1}, {"id": 2}])) == [{"id": 1}, {"id": 2}]
    assert nh.objects_of({"status": "success", "content": [{"text": "not json"}, {}]}) == []

def test_object_line_prefers_display_and_url():
    assert nh.object_line("vlans", {"id": 7, "display": "USERS (10)", "display_url": "http://nb/ipam/vlans/7/"}) == "USERS (10) (vlans #7) http://nb/ipam/vlans/7/"

def event(name, inputs, cancel_tool=False):
    return SimpleNamespace(tool_use={"name": name, "input": inputs}, cancel_tool=cancel_tool)

def test_confirm_lets_reads_through_and_asks_for_writes(capsys):
    hook = nh.ConfirmNetboxWrites(netbox=None, ask=lambda prompt: "n")
    e = event("netbox_get_objects", {"object_type": "vlans"}); hook.confirm(e); assert e.cancel_tool is False
    e = event("netbox_create_object", {"object_type": "vlans", "data": {"vid": 99, "name": "LEGACY"}}); hook.confirm(e)
    assert isinstance(e.cancel_tool, str) and "refused" in e.cancel_tool
    assert '"vid": 99' in capsys.readouterr().out

def test_confirm_yes_and_already_cancelled():
    hook = nh.ConfirmNetboxWrites(netbox=None, ask=lambda prompt: "y")
    e = event("netbox_update_object", {"object_type": "vlans", "object_id": 7, "data": {"name": "VOICE"}}); hook.confirm(e); assert e.cancel_tool is False
    e = event("netbox_update_object", {"object_type": "vlans", "object_id": 7, "data": {}}, cancel_tool="refused by steering")
    hook.confirm(e); assert e.cancel_tool == "refused by steering"

def test_confirm_refuses_without_terminal():
    def eof(prompt): raise EOFError
    hook = nh.ConfirmNetboxWrites(netbox=None, ask=eof)
    e = event("netbox_delete_object", {"object_type": "vlans", "object_id": 7}); hook.describe = lambda t, i: f"{t} #{i}"; hook.confirm(e)
    assert isinstance(e.cancel_tool, str)

def test_show_write_links_prints_one_line_per_object(capsys):
    e = SimpleNamespace(tool_use={"name": "netbox_create_object", "input": {"object_type": "vlans"}}, cancel_message=None, exception=None,
                        result=result_of({"id": 7, "display": "LEGACY (99)", "display_url": "u"}))
    nh.ShowWriteLinks().show(e)
    assert capsys.readouterr().out.strip() == "[netbox: created LEGACY (99) (vlans #7) u]"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_netbox_hooks.py -q`
Expected: FAIL, module missing.

- [ ] **Step 3: Implement `vlanlab/netbox_hooks.py`**

Port `object_line`, `objects_of`, `ShowWriteLinks` from `strand_agents_lab/netbox_agent.py`, replacing the dead `isinstance(result, Exception)` check by `event.exception`. Generalise `ConfirmDeletes` into `ConfirmNetboxWrites`: for deletes, describe each id with `netbox_get_object_by_id` via `self.netbox.call_tool_sync` inside a `try/except Exception` that falls back to `"{object_type} #{object_id}: lookup failed ({error})"`; for creates/updates, print the `object_type`, the `object_id` if any, and `json.dumps(data, indent=2)`; then `ask("  Confirm? [y/N] ")`, `EOFError` → refuse; a refusal sets `event.cancel_tool = "Write refused by the user. Do not retry it; tell the user it was not done."`. Return early when `event.cancel_tool` is already set. `register_hooks` uses `registry.add_callback(BeforeToolCallEvent, self.confirm, order=HookOrder.SDK_LAST)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_netbox_hooks.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add vlanlab/netbox_hooks.py tests/test_netbox_hooks.py && git commit -m "feat: NetBox write confirmation and write-link hooks"
```

---

### Task 6: The `configure_vlans` tool

**Files:**
- Create: `vlanlab/device_tool.py`, `tests/test_device_tool.py`

**Interfaces:**
- Consumes: the Netmiko Tools inventory `netmiko/.netmiko.yml` written by Task 10 (`leaf1`, `leaf2`: `device_type`, `host`, `username`, `password`).
- Produces: `INVENTORY_FILE = Path("netmiko/.netmiko.yml")`; `load_inventory(path: Path = INVENTORY_FILE) -> dict[str, dict]`; `connect = ConnectHandler` (module attribute, swapped in tests); `@tool configure_vlans(device: str, commands: list[str]) -> str`; `TOOL_NAME = "configure_vlans"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_device_tool.py
import pathlib, textwrap, pytest
from vlanlab import device_tool as dt

INV = textwrap.dedent("""
    leaf1: {device_type: arista_eos, host: 172.20.20.11, username: admin, password: admin}
    leaf2: {device_type: arista_eos, host: 172.20.20.12, username: admin, password: admin}
    leafs: [leaf1, leaf2]
""")

@pytest.fixture
def inventory(tmp_path, monkeypatch):
    p = tmp_path / ".netmiko.yml"; p.write_text(INV)
    monkeypatch.setattr(dt, "INVENTORY_FILE", p)
    return p

class FakeConn:
    sent, saved = [], 0
    def __init__(self, **kw): self.kw = kw
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def send_config_set(self, cmds): FakeConn.sent.extend(cmds); return "\n".join(cmds)
    def save_config(self): FakeConn.saved += 1; return "Copy completed"

def test_load_inventory_skips_groups(inventory):
    inv = dt.load_inventory(inventory)
    assert set(inv) == {"leaf1", "leaf2"} and inv["leaf1"]["device_type"] == "arista_eos"

def test_configure_pushes_and_saves(inventory, monkeypatch):
    monkeypatch.setattr(dt, "connect", FakeConn)
    out = dt.configure_vlans(device="leaf1", commands=["vlan 30", "name IOT"])
    assert FakeConn.sent == ["vlan 30", "name IOT"] and FakeConn.saved == 1
    assert "leaf1" in out and "saved" in out.lower()

def test_unknown_device_is_an_error_string(inventory, monkeypatch):
    monkeypatch.setattr(dt, "connect", FakeConn)
    out = dt.configure_vlans(device="spine1", commands=["vlan 30"])
    assert out.startswith("Error:") and "leaf1" in out and "leaf2" in out

def test_connection_failure_is_an_error_string(inventory, monkeypatch):
    class Boom:
        def __init__(self, **kw): raise TimeoutError("connection timed out")
    monkeypatch.setattr(dt, "connect", Boom)
    out = dt.configure_vlans(device="leaf1", commands=["vlan 30"])
    assert out.startswith("Error:") and "timed out" in out

def test_strands_sees_the_tool():
    assert dt.configure_vlans.tool_name == "configure_vlans"
    assert set(dt.configure_vlans.tool_spec["inputSchema"]["json"]["required"]) == {"device", "commands"}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_device_tool.py -q`
Expected: FAIL, module missing.

- [ ] **Step 3: Implement `vlanlab/device_tool.py`**

`load_inventory` uses `netmiko.utilities.load_yaml_file` and `obtain_all_devices` (the same loader `netmiko-mcp` uses, so encryption works the same way) and drops entries that are not dicts (groups). `configure_vlans` is decorated with `from strands import tool`; its docstring is what the model reads: it pushes configuration lines to one lab switch, says the lines must be `vlan N` and `name X` only, and that the user confirms before anything is sent. Body: resolve the device (unknown → `"Error: unknown device '…'. Known devices: leaf1, leaf2"`), `with connect(**params) as conn:` `send_config_set(commands)` then `save_config()`, return `f"{device}: configuration applied and saved.\n{output}"`; any `Exception` → `f"Error: {device}: {exc}"`. Never raise.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_device_tool.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add vlanlab/device_tool.py tests/test_device_tool.py && git commit -m "feat: configure_vlans Strands tool over Netmiko, sharing the netmiko-mcp inventory"
```

---

### Task 7: Guards: `VlanGuard` steering and `ConfirmDeviceWrites` hook

**Files:**
- Create: `vlanlab/guards.py`, `tests/test_guards.py`

**Interfaces:**
- Consumes: `device_tool.TOOL_NAME`.
- Produces: `VLAN_RE`, `NAME_RE` (compiled); `class VlanGuard(SteeringHandler)` with `name = "vlan-guard"`, `__init__(self, max_vlans: int = 5)`, `check(self, tool_use: dict) -> str | None` (pure), `vlan_ids(commands: list[str]) -> set[int]` (static), the `start_turn` hook and `steer_before_tool` as in `strand_agents_lab`'s `LimitDeletes`; `class ConfirmDeviceWrites(HookProvider)` with `__init__(self, ask=input)`, `confirm(self, event)`, registered at `HookOrder.SDK_LAST`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_guards.py
from types import SimpleNamespace
from vlanlab import guards

def use(commands, device="leaf1", name="configure_vlans"):
    return {"name": name, "input": {"device": device, "commands": commands}}

def guard(done_ids=()):
    g = guards.VlanGuard(max_vlans=5)
    g.turn_calls = lambda: [{"tool_name": "configure_vlans", "status": "success", "tool_args": {"commands": [f"vlan {i}" for i in done_ids]}}]
    return g

def test_allows_vlan_and_name_after_normalisation():
    assert guard().check(use(["VLAN 30", "  name   IOT "])) is None

def test_refuses_deletion_and_anything_else():
    for bad in (["no vlan 99"], ["vlan 30", "shutdown"], ["interface Ethernet1"], ["vlan 0"], ["vlan 4095"], ["name has space"], ["name " + "x" * 33], []):
        reason = guard().check(use(bad)); assert reason, bad
    assert "not allowed" in guard().check(use(["no vlan 99"]))

def test_ignores_other_tools():
    assert guard().check({"name": "send_show_command", "input": {"command": "no vlan 99"}}) is None

def test_caps_distinct_vlans_per_turn():
    assert guard(done_ids=(1, 2, 3)).check(use(["vlan 4", "vlan 5"])) is None
    assert guard(done_ids=(1, 2, 3)).check(use(["vlan 4", "vlan 5", "vlan 6"]))
    assert guard(done_ids=(1, 2, 3)).check(use(["vlan 3", "name A", "vlan 4", "vlan 5"])) is None  # 3 already counted

def test_confirm_device_writes(capsys):
    e = SimpleNamespace(tool_use=use(["vlan 30", "name IOT"]), cancel_tool=False)
    guards.ConfirmDeviceWrites(ask=lambda p: "y").confirm(e); assert e.cancel_tool is False
    assert "leaf1" in capsys.readouterr().out
    e = SimpleNamespace(tool_use=use(["vlan 30"]), cancel_tool=False)
    guards.ConfirmDeviceWrites(ask=lambda p: "").confirm(e); assert isinstance(e.cancel_tool, str)
    e = SimpleNamespace(tool_use=use(["vlan 30"]), cancel_tool="Tool call cancelled. deletions are not allowed")
    guards.ConfirmDeviceWrites(ask=lambda p: (_ for _ in ()).throw(AssertionError("must not ask"))).confirm(e)
    def eof(p): raise EOFError
    e = SimpleNamespace(tool_use=use(["vlan 30"]), cancel_tool=False)
    guards.ConfirmDeviceWrites(ask=eof).confirm(e); assert isinstance(e.cancel_tool, str)

def test_hook_order_is_after_steering():
    from strands.hooks import HookOrder
    calls = []
    class Reg:
        def add_callback(self, et, cb, order=HookOrder.DEFAULT): calls.append(order)
    guards.ConfirmDeviceWrites().register_hooks(Reg())
    assert calls == [HookOrder.SDK_LAST]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_guards.py -q`
Expected: FAIL, module missing.

- [ ] **Step 3: Implement `vlanlab/guards.py`**

`VLAN_RE = re.compile(r"^vlan (\d{1,4})$")`, `NAME_RE = re.compile(r"^name [A-Za-z0-9_-]{1,32}$")`. Normalise each command with `" ".join(cmd.lower().split())` before matching `VLAN_RE`; `NAME_RE` is matched on `" ".join(cmd.split())` (names keep their case). `check`: not our tool → `None`; empty list → reason; a command matching neither → reason naming the command and saying `"… is not allowed: only 'vlan N' and 'name X' may be sent, deletions are not allowed. Report it to the user instead of retrying."`; vid outside 1..4094 → reason; then `done = vlan_ids` of the successful `configure_vlans` calls of the turn (ledger, `status == "success"`), `asked = vlan_ids(commands)`, refuse when `len(done | asked) > max_vlans` with the same wording style as `LimitDeletes`. `steer_before_tool` prints `[guard: …]` and returns `Guide(reason)`; `start_turn`/`turn_calls` copied from `LimitDeletes`. `ConfirmDeviceWrites.confirm`: return if not our tool or `event.cancel_tool`; print `"\n  CONFIGURE {device}:"` then one `"    {cmd}"` per command; `ask("  Confirm? [y/N] ")`; anything but `y`, or `EOFError`, sets `event.cancel_tool = "Configuration refused by the user. Do not retry it; tell the user it was not done."`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_guards.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add vlanlab/guards.py tests/test_guards.py && git commit -m "feat: VLAN whitelist steering and device write confirmation"
```

---

### Task 8: Skills

**Files:**
- Create: `skills/vlan-audit/SKILL.md`, `skills/vlan-remediation/SKILL.md`, `tests/test_skills.py`

**Interfaces:**
- Produces: two skills loadable by `AgentSkills(skills=["skills"], strict=True)`; tool names used in the procedures: `netbox_get_objects`, `send_show_command`, `configure_vlans`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skills.py
import pathlib, re
ROOT = pathlib.Path(__file__).resolve().parents[1]

def frontmatter(p):
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S); assert m, p
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())

def test_skills_have_frontmatter_and_name_their_tools():
    audit = ROOT / "skills/vlan-audit/SKILL.md"; fix = ROOT / "skills/vlan-remediation/SKILL.md"
    assert frontmatter(audit)["name"] == "vlan-audit" and frontmatter(fix)["name"] == "vlan-remediation"
    assert "send_show_command" in audit.read_text() and "show vlan" in audit.read_text() and "netbox_get_objects" in audit.read_text()
    assert "configure_vlans" in fix.read_text() and "no vlan" in fix.read_text()

def test_agent_skills_plugin_loads_them():
    from strands import AgentSkills
    AgentSkills(skills=[str(ROOT / "skills")], strict=True)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_skills.py -q`
Expected: FAIL, files missing.

- [ ] **Step 3: Write `skills/vlan-audit/SKILL.md`**

Frontmatter `name: vlan-audit`, `description:` one sentence saying when to use it (user asks to audit, compare, check VLANs of a site against the switches). Body, as numbered steps: get the site's VLANs with `netbox_get_objects` (`object_type: vlans`, `filters: {"site": "<slug>"}`); get the site's devices (`object_type: devices`, same filter) and their interfaces if asked; for each device run `send_show_command` with `command: "show vlan"` and `use_textfsm: true`; compare on `vlan_id` and `vlan_name`, ignoring VLAN 1; render one table per device with columns VLAN, expected name, observed name, verdict (`ok`, `missing`, `renamed`), then list VLANs present on the switch but absent from NetBox as `undocumented`; end with a one-line summary per device. State that this skill changes nothing.

- [ ] **Step 4: Write `skills/vlan-remediation/SKILL.md`**

Frontmatter `name: vlan-remediation`, `description:` when the user asks to fix, align or remediate switches to match NetBox. Body: start from the audit in the conversation, or run `vlan-audit` first; for each device build the minimal command list: `vlan N` then `name X` for every `missing` or `renamed` VLAN; never emit `no vlan`, `shutdown`, interface or any other command, and say so when a VLAN is `undocumented`: it stays, and the user may document it in NetBox; call `configure_vlans` once per device; the user confirms on the terminal; then report, and offer to re-run the audit.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_skills.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add skills tests/test_skills.py && git commit -m "feat: vlan-audit and vlan-remediation skills"
```

---

### Task 9: The agent and `.mcp.json`

**Files:**
- Create: `agent.py`, `.mcp.json`, `tests/test_agent.py`

**Interfaces:**
- Consumes: Tasks 5, 6, 7, 8.
- Produces: `uv run python agent.py` (chat), `uv run python agent.py "question"` (one shot), `uv run python agent.py --list-tools` (builds the agent, starts both MCP servers, prints one tool name per line, exits 0; used by `install.sh`). `build_agent() -> Agent`. `.mcp.json` servers `netbox` and `netmiko`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent.py
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_mcp_json_declares_both_servers_pinned():
    cfg = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert set(cfg) == {"netbox", "netmiko"}
    assert "netmiko-mcp==0.2.0" in " ".join(cfg["netmiko"]["args"]) and "netmiko/netmiko-mcp.yml" in " ".join(cfg["netmiko"]["args"])
    assert "NETBOX_RW_TOKEN" in " ".join(cfg["netbox"]["args"])

def test_build_agent_wires_tools_hooks_and_guards(monkeypatch):
    import agent
    from vlanlab import guards, netbox_hooks
    monkeypatch.setattr(agent.MCPClient, "load_servers", classmethod(lambda cls, cfg: []))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    a = agent.build_agent()
    assert "configure_vlans" in a.tool_names                      # Agent.tool_names, Strands 1.61.1
    assert "vlan-guard" in a._plugin_registry._plugins            # plugins are registered by their `name`
    assert any(isinstance(h, netbox_hooks.ConfirmNetboxWrites) for h in a.hooks._registered_providers) if hasattr(a.hooks, "_registered_providers") else True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_agent.py -q`
Expected: FAIL, files missing. (With `load_servers` returning `[]`, `ConfirmNetboxWrites` gets `netbox=None`: `build_agent` passes `servers[0] if servers else None`.)

- [ ] **Step 3: Write `.mcp.json`**

```json
{"mcpServers": {
  "netbox":  {"command": "sh", "args": ["-c", "set -a; . ./.env; NETBOX_TOKEN=$NETBOX_RW_TOKEN exec uv --directory netbox-mcp-rw run server.py 2>>netbox-mcp-rw/server.log"]},
  "netmiko": {"command": "sh", "args": ["-c", "NETMIKO_MCP_CONFIG=netmiko/netmiko-mcp.yml exec uvx --from netmiko-mcp==0.2.0 netmiko-mcp"]}
}}
```

- [ ] **Step 4: Write `agent.py`**

Module docstring: what it is and the three ways to run it. `SYSTEM_PROMPT`: network inventory assistant; NetBox is the source of truth; switches are read with the netmiko tools and written only with `configure_vlans`; before any write state what will change and wait for the terminal confirmation; never send deletions; use the skills when a request matches; be concise; answer in the user's language. `build_agent()`: `servers = MCPClient.load_servers(".mcp.json")`; `AnthropicModel(model_id="claude-opus-5-5", max_tokens=16000)`; `Agent(model, tools=[*servers, configure_vlans], system_prompt, callback_handler=chat_handler, context_manager="auto", hooks=[ConfirmNetboxWrites(servers[0] if servers else None), ShowWriteLinks(), ConfirmDeviceWrites()], plugins=[AgentSkills(skills=["skills"], strict=True), VlanGuard()])`. `chat_handler`, `chat`, `main` ported from `strand_agents_lab/netbox_agent.py`; `main` handles `--list-tools` before anything else: `print("\n".join(agent.tool_names))` (triggers MCP start) then `cleanup()`. The streamed line for a tool call reads `[tool: <name>]`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_agent.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add agent.py .mcp.json tests/test_agent.py && git commit -m "feat: the agent, two MCP servers plus configure_vlans, guards and skills wired"
```

---

### Task 10: `install.sh` and `uninstall.sh`

**Files:**
- Create: `install.sh`, `uninstall.sh`, `tests/test_install_sh.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `sh install.sh` end to end; `sh uninstall.sh [--purge]`.

- [ ] **Step 1: Write the failing test (static checks on the script)**

```python
# tests/test_install_sh.py
import pathlib, re, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_install_sh_is_posix_and_pins_everything():
    s = (ROOT / "install.sh").read_text()
    assert s.startswith("#!/bin/sh") and "set -e" in s
    assert "netmiko-mcp==0.2.0" in s and "96705f8ff24b96e98f6d82e6f4fde399e5ac57d9" in s
    assert "ceos:lab" in s and "clab/vlan-lab.clab.yml" in s
    assert re.search(r"sudo containerlab", s) and not re.search(r"sudo uv", s)
    assert subprocess.run(["sh", "-n", str(ROOT / "install.sh")]).returncode == 0
    assert subprocess.run(["sh", "-n", str(ROOT / "uninstall.sh")]).returncode == 0

def test_install_sh_stops_without_image(tmp_path):
    # run only the prerequisite step: the script must exit 1 and name images/ when no archive is there
    r = subprocess.run(["sh", str(ROOT / "install.sh"), "--check-prereqs"], cwd=ROOT, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 1 and "images/" in r.stdout + r.stderr
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_install_sh.py -q`
Expected: FAIL, script missing.

- [ ] **Step 3: Write `install.sh`**

POSIX sh, `set -e`, `cd "$(dirname "$0")"`, `step()` helper, `--check-prereqs` flag that runs step 0 only. Steps, each printed as `== N/7 …`:
0. Prerequisites, all checked before exiting so one run reports every gap: `docker info` works without sudo (else: add the user to the `docker` group), `docker compose version`, `containerlab version` (else print `bash -c "$(curl -sL https://get.containerlab.dev)"`), `uv`, `git`; exactly one archive among `images/cEOS64-lab-*.tar*`, `images/cEOS-lab-*.tar*`, `images/cEOSarm-lab-*.tar*` (none → print the Arista download URL and the expected location; several → pick the lexically last and say so). Any gap → exit 1 after the list.
1. `.env`: keep existing values or generate `NETBOX_SUPERUSER_TOKEN` (40 hex), `NETBOX_TOKEN`, `NETBOX_RW_TOKEN` (40 hex each), `NETBOX_SECRET_KEY` (≥ 50 chars); write `NETBOX_URL=http://localhost:$PORT/`; keep an existing `ANTHROPIC_API_KEY` line, else write it empty with a comment. `docker compose up -d`; wait for `/login/` (10 minutes max); `sh netbox/bootstrap_token.sh`.
2. Seed: `NETBOX_URL=… NETBOX_TOKEN=$SUPERUSER MCP_TOKEN=… MCP_RW_TOKEN=… uv run python netbox/seed.py`.
3. `netbox-mcp-rw`: clone if missing, `checkout` the pinned commit, `.python-version` 3.13, `uv --directory netbox-mcp-rw sync -q`.
4. `netmiko-mcp`: `uv tool install --quiet netmiko-mcp==0.2.0`; write `netmiko/netmiko-mcp.yml` (`inventory_type: netmiko_tools`, `inventory_file`, `command_file`, `audit_log_file` as absolute paths under `$PWD/netmiko/`), `netmiko/.netmiko.yml` (leaf1, leaf2: `device_type: arista_eos`, hosts, `admin`/`admin`; group `leafs: [leaf1, leaf2]`), `netmiko/commands.yml` (`allowed_commands: ["show vlan*"]`, `denied_commands: []`).
5. Containerlab: `docker image inspect ceos:lab` or `docker import "$ARCHIVE" ceos:lab`; `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure`; wait until `uv run python -c` with Netmiko gets `show vlan` from both leafs (retry every 10 s, 5 minutes max).
6. Agent: `uv sync`; `uv run python agent.py --list-tools` must list `configure_vlans`, `send_show_command`, `netbox_get_objects`.
7. Checks, each printed `[ok]`/`[KO]`: NetBox VLAN count on site `lab` is 3 with the read token; the read token gets 403 on a PATCH; the rw token can PATCH a VLAN name to itself; `show vlan` on each leaf contains `USERS`, `VOICE`, `IOT`. Final line: NetBox URL, admin credentials, `uv run python agent.py`, and the reminder to set `ANTHROPIC_API_KEY` in `.env` if empty.

- [ ] **Step 4: Write `uninstall.sh`**

`sudo containerlab destroy -t clab/vlan-lab.clab.yml --cleanup` (ignore failure if not deployed), `docker compose down` (`--purge` adds `-v`), keep images and `.env`; print what was kept.

- [ ] **Step 5: Run the static test**

Run: `uv run pytest tests/test_install_sh.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Run the real thing in the dev VM, twice**

Run: `sh uninstall.sh --purge; sh install.sh && sh install.sh`
Expected: first run ends with all `[ok]` and the summary; second run creates nothing new (tokens kept, seed silent, `--reconfigure` redeploys) and ends `[ok]` again. Record the elapsed time of the first run and the cEOS boot wait for the README.

- [ ] **Step 7: Commit**

```bash
git add install.sh uninstall.sh tests/test_install_sh.py && git commit -m "feat: one-shot install.sh and uninstall.sh"
```

---

### Task 11: `drift.sh`

**Files:**
- Create: `drift.sh`, `tests/test_drift_sh.py`

**Interfaces:**
- Produces: `sh drift.sh` introduces the three drifts and prints `show vlan` of both leafs; `sh drift.sh --reset` redeploys the clean config from `clab/ceos.cfg` and waits for SSH.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift_sh.py
import pathlib, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_drift_sh_encodes_the_three_drifts():
    s = (ROOT / "drift.sh").read_text()
    assert subprocess.run(["sh", "-n", str(ROOT / "drift.sh")]).returncode == 0
    assert "clab-vlan-lab-leaf1" in s and "no vlan 30" in s
    assert "clab-vlan-lab-leaf2" in s and "name VOIP" in s and "vlan 99" in s and "name LEGACY" in s
    assert "--reconfigure" in s and "--reset" in s
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_drift_sh.py -q`
Expected: FAIL, script missing.

- [ ] **Step 3: Write `drift.sh`**

POSIX sh. A `cli()` helper: `docker exec "clab-vlan-lab-$1" Cli -p 15 -c "$2"` where `$2` is a multi-line string starting with `configure` and ending with `end` followed by `write`. Default mode: leaf1 `no vlan 30`; leaf2 `vlan 20` / `name VOIP`, `vlan 99` / `name LEGACY`; then `show vlan` on both, printed under a `== leafN` header. `--reset`: `sudo containerlab deploy -t clab/vlan-lab.clab.yml --reconfigure`, then the same SSH wait loop as `install.sh` step 5 (factor it into `scripts/wait_for_leafs.py` if you prefer; both scripts call it), then `show vlan` on both. Idempotent: EOS accepts `no vlan 30` when absent and `vlan 99` when present.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_drift_sh.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Verify in the dev VM**

Run: `sh drift.sh && sh drift.sh && sh drift.sh --reset`
Expected: after the first two runs, leaf1 shows no VLAN 30 and leaf2 shows `20 VOIP` and `99 LEGACY`; after `--reset`, both leafs show the clean three VLANs.

- [ ] **Step 6: Commit**

```bash
git add drift.sh tests/test_drift_sh.py && git commit -m "feat: drift.sh introduces the three VLAN drifts and resets the lab"
```

---

### Task 12: End-to-end run, README and macOS dev runbook

**Files:**
- Create: `README.md`, `docs/dev-macos.md`
- Modify: `.env.example` (cost line), `docs/dev-macos.md` with the observed ARM limits

**Interfaces:**
- Consumes: the whole stack, in the dev VM, with a real `ANTHROPIC_API_KEY`.

- [ ] **Step 1: Run the demo end to end and keep the transcript**

Run, in the VM: `sh drift.sh`, then `uv run python agent.py` and ask `Audit the VLANs of site lab against the switches.` then `Fix leaf1 and leaf2 so they match NetBox.` (answer `y` to both confirmations), then the audit again. Save the terminal output to `docs/demo-transcript.txt`.
Expected: audit table shows leaf1 `30 missing`, leaf2 `20 renamed`, `99 undocumented`; remediation shows `[guard: …]` only if the model tried a forbidden command, two `CONFIGURE` prompts, and a final sentence saying VLAN 99 was left in place; second audit shows only `99 undocumented`. Note the Anthropic usage (tokens and cost) of the session from the console.

- [ ] **Step 2: Try the forbidden path on purpose**

Ask: `Remove VLAN 99 from leaf2.`
Expected: a `[guard: …]` line, no `CONFIGURE` prompt, the agent explains it cannot delete and suggests documenting the VLAN in NetBox. If the model instead calls a NetBox write, the `ConfirmNetboxWrites` prompt appears; answer `n`.

- [ ] **Step 3: Write `README.md`**

Sections, in this order: what this is (two sentences and the link to the article placeholder); the scenario (the drift table from the spec); prerequisites (Linux x86_64 Ubuntu 22.04/24.04, Docker + Compose v2 without sudo, Containerlab, uv, git, an Arista account to download `cEOS64-lab-<version>.tar.xz` into `images/`, `ANTHROPIC_API_KEY`); install (`git clone …`, put the archive, `sh install.sh`, the measured durations); run the demo (`sh drift.sh`, the two questions, `sh drift.sh --reset`); how it works (one paragraph per file: `agent.py`, `vlanlab/device_tool.py`, `vlanlab/guards.py`, `vlanlab/netbox_hooks.py`, `skills/`); "Why netmiko-mcp for reads and a custom tool for writes" (netmiko-mcp is the official server by the Netmiko author, read-only by design with a server-side command whitelist; it has no config mode, so writes go through `configure_vlans`, where the agent's own guards apply); the server-side whitelist (`netmiko/commands.yml`); cost of a demo session (measured in Step 1); tested-on statement (arm64 under OrbStack with the cEOS ARM build; x86_64 is the documented target and has not been run by the author yet); cleanup (`sh uninstall.sh [--purge]`); licence.

- [ ] **Step 4: Write `docs/dev-macos.md`**

Create the OrbStack Linux arm64 VM (Ubuntu), install Docker, Containerlab, uv, git inside it; clone the repo in the VM; put `cEOSarm-lab-*.tar.xz` in `images/`; run `install.sh`; reach NetBox from macOS through the VM's address; the limits of the ARM image met during Task 10 to 12 (whatever they were: boot time, missing features, error messages), each with the workaround used.

- [ ] **Step 5: Run the whole test suite and the static checks once more**

Run: `uv run pytest -q && sh -n install.sh && sh -n drift.sh && sh -n uninstall.sh && grep -rIl --exclude-dir=.git --exclude-dir=.venv --exclude-dir=netbox-mcp-rw -e c9500 -e NGW -e "poc" -e 5trandagent5lab -e Europe/Paris . || true`
Expected: all tests pass; the grep prints nothing (if it prints this plan or the spec, that is fine: only `docs/superpowers/` may mention the old lab).

- [ ] **Step 6: Commit and push**

```bash
git add README.md docs .env.example && git commit -m "docs: README, macOS dev runbook, demo transcript" && git push -u origin main
```
