"""The guards around deploy_config, enforced in code before the tool runs.

Two layers, in this order:

1. `DeployGuard`, a Strands steering handler (BeforeToolCallEvent packaged by Strands): refuses a deployment whose
   rendering is missing, or would lock the operator out (wrong hostname, no management block with the inventory
   address, no admin user), or that would exceed `max_devices` distinct switches in the turn. The reason goes back to
   the model with the instruction to report it, not retry. Steering is fail-open in Strands (an exception lets the
   tool run), so everything here stays defensive.
2. `ConfirmDeploy`, a BeforeToolCallEvent hook registered at HookOrder.SDK_LAST so it runs after the steering: shows
   the device and the preview diff on the terminal and waits for a `y`. Without a terminal, it refuses. It never asks
   for a call the steering already cancelled.
"""

import re

from strands.hooks import BeforeInvocationEvent, BeforeToolCallEvent, HookOrder, HookProvider, HookRegistry
from strands.plugins import hook
from strands.vended_plugins.steering import Guide, LedgerProvider, Proceed, SteeringHandler, ToolSteeringAction

from vlanlab.eos import load_inventory
from vlanlab.infrahub_api import ArtifactNotReady, fetch_artifact
from vlanlab.infrahub_tools import DEPLOY_TOOL, preview_config

REFUSE_SUFFIX = " Do not retry; report it to the user."


def management_block(rendered: str) -> list[str]:
    """The indented lines under `interface Management0`, [] when the block is missing."""
    lines = rendered.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "interface Management0":
            block = []
            for child in lines[i + 1:]:
                if not child.startswith(" "):
                    break
                block.append(child.strip())
            return block
    return []


class DeployGuard(SteeringHandler):
    """At most `max_devices` switches deployed per turn, and only with a rendering that keeps management access."""

    name = "deploy-guard"

    def __init__(self, max_devices: int = 2) -> None:
        super().__init__(context_providers=[LedgerProvider()])
        self.max_devices = max_devices
        self.render = fetch_artifact   # swapped by the tests
        self.inventory = load_inventory

    @hook
    def start_turn(self, event: BeforeInvocationEvent) -> None:
        """Remembers where the current turn starts in the ledger of tool calls."""
        ledger = self.steering_context.data.get("ledger") or {}
        self.steering_context.data.set("turn_start", len(ledger.get("tool_calls", [])))

    def turn_calls(self) -> list[dict]:
        """The ledger entries of the current turn, oldest first."""
        ledger = self.steering_context.data.get("ledger") or {}
        return list(ledger.get("tool_calls", []))[self.steering_context.data.get("turn_start") or 0:]

    def check(self, tool_use: dict) -> str | None:
        """The reason to refuse this call, or None to let it run. Pure logic, testable without an agent."""
        if tool_use.get("name") != DEPLOY_TOOL:
            return None
        device = (tool_use.get("input") or {}).get("device")
        inventory = self.inventory()
        if device not in inventory:
            return f"Unknown device {device!r}; known devices: {', '.join(sorted(inventory))}." + REFUSE_SUFFIX
        try:
            rendered = self.render(device)
        except ArtifactNotReady:
            rendered = ""
        except Exception as exc:
            return f"Could not read the Infrahub artifact of {device!r}: {exc}." + REFUSE_SUFFIX
        if not rendered.strip():
            return f"No ready artifact for {device!r} in Infrahub: nothing to deploy." + REFUSE_SUFFIX
        if not re.search(rf"^hostname {re.escape(device)}\s*$", rendered, re.M):
            return f"The rendering for {device!r} does not set `hostname {device}`; refusing to deploy it." + REFUSE_SUFFIX
        host = str(inventory[device].get("host", ""))
        if not any(line.startswith(f"ip address {host}/") for line in management_block(rendered)):
            return (f"The rendering for {device!r} has no `interface Management0` block with address {host}: deploying it "
                    f"would cut the management access; refusing.") + REFUSE_SUFFIX
        if not re.search(r"^username admin\b", rendered, re.M):
            return f"The rendering for {device!r} has no `username admin` line: deploying it would lock us out; refusing." + REFUSE_SUFFIX
        done = {(c.get("tool_args") or {}).get("device") for c in self.turn_calls()
                if c.get("tool_name") == DEPLOY_TOOL and c.get("status") == "success"}
        done.discard(None)
        if len(done | {device}) > self.max_devices:
            return (f"At most {self.max_devices} switches may be deployed per turn: {', '.join(sorted(done))} already done. "
                    f"Stop, report what was deployed and what remains, and let the user ask again for the rest.")
        return None

    async def steer_before_tool(self, *, agent, tool_use, **kwargs) -> ToolSteeringAction:
        """Called by Strands before every tool call: applies `check` and prints the refusal, if any."""
        reason = self.check(tool_use)
        if reason is None:
            return Proceed(reason="not a deployment, or a safe one under the limit")
        print(f"\n  [guard: {reason}]", flush=True)
        return Guide(reason=reason)


class ConfirmDeploy(HookProvider):
    """Asks the user on the terminal before deploy_config runs, after the steering had its say."""

    def __init__(self, ask=input) -> None:
        self.ask = ask
        self.preview = lambda device: preview_config(device=device)  # swapped by the tests

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self.confirm, order=HookOrder.SDK_LAST)

    def confirm(self, event) -> None:
        if event.tool_use.get("name") != DEPLOY_TOOL or event.cancel_tool:
            return
        device = (event.tool_use.get("input") or {}).get("device", "?")
        print(f"\n  DEPLOY {device}: replace the running configuration with Infrahub's rendering", flush=True)
        try:
            diff = self.preview(device)
        except Exception as exc:
            diff = f"(preview unavailable: {exc})"
        for line in (diff or "").splitlines():
            print(f"    {line}", flush=True)
        try:
            answer = self.ask("  Confirm? [y/N] ").strip().lower()
        except EOFError:  # no terminal to ask on: refuse
            answer = ""
        if answer != "y":
            event.cancel_tool = "Deployment refused by the user. Do not retry it; tell the user it was not done."
