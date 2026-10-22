from types import SimpleNamespace

import pytest

from vlanlab import guards

GOOD = ("hostname leaf1\n!\nusername admin privilege 15 role network-admin secret admin\n!\n"
        "interface Management0\n   ip address 172.20.20.11/24\n!\nend\n")
INV = {"leaf1": {"host": "172.20.20.11"}, "leaf2": {"host": "172.20.20.12"}}


def guard(rendered=GOOD, done=()):
    g = guards.DeployGuard(max_devices=2)

    def render(device, **kw):  # a rendering for `device`: GOOD is written for leaf1, adapt name and address
        if rendered is None:
            raise guards.ArtifactNotReady(device)
        return rendered.replace("hostname leaf1", f"hostname {device}").replace("172.20.20.11", INV[device]["host"]) if device in INV else rendered

    g.render = render
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
    assert "admin" in guard(rendered=GOOD.replace("username admin privilege 15 role network-admin secret admin\n", "")).check(use())
    assert guard().check(use(device="spine1"))


def test_caps_devices_per_turn():
    assert guard(done=("leaf1",)).check(use("leaf2")) is None
    assert guard(done=("leaf1", "leaf2")).check(use("leaf1")) is None  # same devices again: still 2 distinct
    g = guards.DeployGuard(max_devices=1)
    g.render, g.inventory = guard().render, lambda: INV
    g.turn_calls = lambda: [{"tool_name": "deploy_config", "status": "success", "tool_args": {"device": "leaf1"}}]
    assert "1" in g.check(use("leaf2"))


def test_ignores_other_tools():
    assert guard(rendered=None).check(use(name="preview_config")) is None


def test_confirm_deploy(capsys):
    hook = guards.ConfirmDeploy(ask=lambda p: "y")
    hook.preview = lambda d: "+vlan 40"
    e = SimpleNamespace(tool_use=use(), cancel_tool=False)
    hook.confirm(e)
    assert e.cancel_tool is False
    out = capsys.readouterr().out
    assert "leaf1" in out and "+vlan 40" in out

    e = SimpleNamespace(tool_use=use(), cancel_tool=False)
    h = guards.ConfirmDeploy(ask=lambda p: "n"); h.preview = lambda d: ""
    h.confirm(e)
    assert isinstance(e.cancel_tool, str) and "refused" in e.cancel_tool

    e = SimpleNamespace(tool_use=use(), cancel_tool="Tool call cancelled.")
    def must_not_ask(p):
        raise AssertionError("must not ask")
    guards.ConfirmDeploy(ask=must_not_ask).confirm(e)

    def eof(p):
        raise EOFError
    e = SimpleNamespace(tool_use=use(), cancel_tool=False)
    h = guards.ConfirmDeploy(ask=eof); h.preview = lambda d: ""
    h.confirm(e)
    assert isinstance(e.cancel_tool, str)


def test_confirm_ignores_other_tools():
    e = SimpleNamespace(tool_use=use(name="preview_config"), cancel_tool=False)
    guards.ConfirmDeploy(ask=lambda p: (_ for _ in ()).throw(AssertionError())).confirm(e)
    assert e.cancel_tool is False


def test_hook_order_is_after_steering():
    from strands.hooks import HookOrder

    calls = []

    class Reg:
        def add_callback(self, et, cb, order=HookOrder.DEFAULT):
            calls.append(order)

    guards.ConfirmDeploy().register_hooks(Reg())
    assert calls == [HookOrder.SDK_LAST]
