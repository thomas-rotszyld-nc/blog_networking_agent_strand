"""The two Strands tools that touch the switches, and the hook that shows what the agent wrote in Infrahub.

`preview_config` and `deploy_config` never take configuration text: they fetch the startup-config Infrahub rendered
for the device (vlanlab.infrahub_api) and compare it with, or apply it to, the switch (vlanlab.eos). The agent decides
*when*; Infrahub decides *what*.

`ShowInfrahubLinks` subscribes to AfterToolCallEvent and prints, after each infrahub-mcp write, the session branch and
the link of the object or Proposed Change in the Infrahub UI, so the user can review and merge.
"""

import difflib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from strands import tool
from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry

from vlanlab.eos import DeployError, load_inventory, replace_config, running_config
from vlanlab.infrahub_api import ArtifactNotReady, fetch_artifact, generate_artifacts, render_artifacts

PREVIEW_TOOL = "preview_config"
DEPLOY_TOOL = "deploy_config"
DEPLOY_LOG_DIR = Path("netmiko")   # the EOS session echo of each deployment, next to the inventory (not committed)
INFRAHUB_WRITE_TOOLS = ("node_upsert", "mutate_graphql", "propose_changes")
SECRET_RE = re.compile(r"^(\s*username \S+ .*?secret) .*$")


# --- comparing a rendering with a running configuration -------------------------------------------------------------

def normalize(config: str) -> list[str]:
    """Lines that carry configuration: no comments (`!`), no blank lines, no `end`, no trailing spaces.

    `username … secret <value>` keeps only its prefix: EOS stores the hash of what the template sent in clear.
    """
    lines = []
    for raw in config.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.startswith("!") or line.strip() == "end":
            continue
        lines.append(SECRET_RE.sub(r"\1 <secret>", line))
    return lines


def _blocks(lines: list[str]) -> list[str]:
    """Top-level blocks (a non-indented line and its indented children), sorted: EOS does not care about their order."""
    blocks, current = [], []
    for line in lines:
        if not line.startswith(" ") and current:
            blocks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return sorted(blocks)


def config_diff(running: str, rendered: str) -> str:
    """Unified diff between the switch (running) and Infrahub (rendered), block order ignored; "" when equivalent."""
    a = "\n".join(_blocks(normalize(running))).splitlines()
    b = "\n".join(_blocks(normalize(rendered))).splitlines()
    return "\n".join(difflib.unified_diff(a, b, fromfile="running", tofile="rendered", lineterm=""))


# --- the tools --------------------------------------------------------------------------------------------------------

def _resolve(device: str) -> tuple[dict | None, str | None, str | None]:
    """(connection params, rendered config, error message) for a device; exactly one of error/others is set."""
    inventory = load_inventory()
    params = inventory.get(device)
    if params is None:
        return None, None, f"Error: unknown device {device!r}. Known devices: {', '.join(sorted(inventory))}."
    try:
        rendered = fetch_artifact(device)
    except ArtifactNotReady:
        return None, None, f"Error: no ready artifact for {device!r} in Infrahub (definition leaf_startup_config). Nothing to compare or deploy; report it instead of retrying."
    except Exception as exc:  # Infrahub unreachable, token refused…
        return None, None, f"Error: could not read the artifact of {device!r} from Infrahub: {exc}"
    return params, rendered, None


@tool
def preview_config(device: str) -> str:
    """Show the difference between the configuration Infrahub rendered for a switch and its running configuration.

    Read-only: nothing is sent to the switch. Returns a unified diff (running -> rendered), or a sentence saying there
    is no difference. Use it before deploy_config, and to check whether a switch drifted from the source of truth.

    Args:
        device: the switch name as in the inventory (leaf1, leaf2).
    """
    params, rendered, error = _resolve(device)
    if error:
        return error
    try:
        running = running_config(params)
    except Exception as exc:
        return f"Error: could not read the running configuration of {device!r}: {exc}"
    diff = config_diff(running, rendered)
    if not diff:
        return f"{device}: no difference between the rendered and the running configuration."
    return f"{device}: differences (running -> rendered):\n{diff}"


@tool
def render_configs() -> str:
    """Asks Infrahub to re-render the startup-configs of all lab switches on main and waits for it (a few seconds).

    Call it once, before preview_config, after a Proposed Change was merged: Infrahub does not re-render main by
    itself for these changes. Returns, per device, whether the rendering changed.
    """
    devices = sorted(load_inventory())
    try:
        changed = render_artifacts(devices, branch="main")
    except Exception as exc:
        return f"Error: {exc}"
    return "Infrahub rendered the startup-configs on main. " + ", ".join(
        f"{d}: {'re-rendered (content changed)' if changed[d] else 'unchanged'}" for d in devices)


@tool
def deploy_config(device: str) -> str:
    """Replace the whole running configuration of a switch with the startup-config Infrahub rendered for it.

    Takes no configuration text: the configuration always comes from Infrahub's artifact for this device. The user
    confirms on the terminal before anything is sent. Run preview_config first and deploy only when it shows a
    difference.

    Args:
        device: the switch name as in the inventory (leaf1, leaf2).
    """
    params, rendered, error = _resolve(device)
    if error:
        return error
    try:
        output = replace_config(params, rendered)
    except DeployError as exc:
        return f"Error: deployment to {device!r} failed: {exc}"
    except Exception as exc:
        return f"Error: deployment to {device!r} failed unexpectedly: {exc}"
    log = _deploy_log(device, output)
    answer = output.strip().splitlines()[-1] if output.strip() else ""
    return (f"{device}: configuration replaced and saved ({len(normalize(rendered))} lines pushed in one EOS session).\n"
            f"{answer}\nSession log: {log}")


def _deploy_log(device: str, output: str) -> Path:
    """Writes the raw session echo to netmiko/deploy-<device>.log (overwritten each time); returns the path."""
    DEPLOY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEPLOY_LOG_DIR / f"deploy-{device}.log"
    path.write_text(f"# {datetime.now(timezone.utc).isoformat(timespec='seconds')} deploy_config({device})\n{output}\n")
    return path


# --- the hook ---------------------------------------------------------------------------------------------------------

def _first_json(result: dict):
    """The first JSON content block of an MCP tool result, or None."""
    for block in result.get("content", []):
        try:
            return json.loads(block.get("text", ""))
        except (TypeError, ValueError):
            continue
    return None


def _object_ids(payload, found=None) -> list[str]:
    """Every `object.id` in a GraphQL mutation response (mutations are asked to return `object { id }`)."""
    found = [] if found is None else found
    if isinstance(payload, dict):
        obj = payload.get("object")
        if isinstance(obj, dict) and obj.get("id"):
            found.append(obj["id"])
        for value in payload.values():
            _object_ids(value, found)
    elif isinstance(payload, list):
        for value in payload:
            _object_ids(value, found)
    return found


class ShowInfrahubLinks(HookProvider):
    """Prints, after each infrahub-mcp write, the branch and the Infrahub UI link of what was written.

    `node_upsert` returns id, display_label and branch; `propose_changes` returns the id of the Proposed Change;
    `mutate_graphql` returns the raw GraphQL data, so the object ids are dug out of it and the branch is asked to the
    server with `get_session_info`. Never raises: a hook failure must not end the agent's turn.
    """

    def __init__(self, infrahub, base_url: str, generate=generate_artifacts) -> None:
        self.infrahub = infrahub
        self.base_url = base_url.rstrip("/")
        self.generate = generate  # called with the source branch after propose_changes, so the review has an artifact diff

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(AfterToolCallEvent, self.show)

    def session_branch(self) -> str:
        """The active session branch of the infrahub-mcp server, "?" when it cannot be read."""
        try:
            result = self.infrahub.call_tool_sync(f"links-{uuid.uuid4().hex[:8]}", "get_session_info", {})
            payload = _first_json(result) or {}
            return payload.get("session_branch") or "?"
        except Exception:
            return "?"

    def show(self, event) -> None:
        try:
            name = event.tool_use["name"]
            if name not in INFRAHUB_WRITE_TOOLS or event.cancel_message or event.exception:
                return
            result = event.result
            if not isinstance(result, dict) or result.get("status") != "success":
                return
            payload = _first_json(result)
            if payload is None:
                return
            for line in self._lines(name, payload, event.tool_use.get("input") or {}):
                print(f"  [infrahub: {line}]", flush=True)
        except Exception:
            return

    def _lines(self, name: str, payload, inputs: dict) -> list[str]:
        if name == "node_upsert" and isinstance(payload, dict) and payload.get("id"):
            kind = inputs.get("kind", "?")
            branch = payload.get("branch") or self.session_branch()
            return [f"{payload.get('display_label') or kind} ({kind}) on branch {branch} "
                    f"{self.base_url}/objects/{kind}/{payload['id']}?branch={branch}"]
        if name == "propose_changes" and isinstance(payload, dict) and payload.get("id"):
            lines = [f"proposed change {payload.get('source_branch') or ''} -> {payload.get('destination_branch') or 'main'} "
                     f"{self.base_url}/proposed-changes/{payload['id']}".replace("  ", " ")]
            branch = payload.get("source_branch") or self.session_branch()
            if branch and branch != "?":
                try:
                    self.generate(branch)
                    lines.append(f"rendering the startup-configs on branch {branch}, the artifact diff appears in the proposed change in a few seconds")
                except Exception as exc:  # the review still works without the diff; say so
                    lines.append(f"could not ask for the rendering on branch {branch}: {exc}")
            return lines
        if name == "mutate_graphql":
            ids = _object_ids(payload)
            if ids:
                branch = self.session_branch()
                return [f"mutation wrote object {i} on branch {branch} {self.base_url}/objects/CoreNode/{i}?branch={branch}" for i in ids]
        return []
