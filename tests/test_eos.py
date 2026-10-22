import textwrap

import pytest

from vlanlab import eos

INV = textwrap.dedent("""
    leaf1: {device_type: arista_eos, host: 172.20.20.11, username: admin, password: admin}
    leaf2: {device_type: arista_eos, host: 172.20.20.12, username: admin, password: admin}
    leafs: [leaf1, leaf2]
""")


class FakeConn:
    sent: list[str] = []
    saved = 0

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def send_command(self, cmd, **kw):
        return "hostname leaf1\n!\nend\n" if "running" in cmd else "leaf1"

    reject = False
    config_mode_commands: list[str] = []

    def send_config_set(self, cmds, **kw):
        FakeConn.sent.extend(cmds)
        FakeConn.config_mode_commands.append(kw.get("config_mode_command"))
        return "\n".join(cmds) + ("\n% Invalid input\n" if FakeConn.reject else "")

    def send_command_timing(self, cmd, **kw):
        FakeConn.sent.append(cmd)
        return "ok"

    def save_config(self):
        FakeConn.saved += 1
        return "Copy completed"


def test_load_inventory_skips_groups(tmp_path):
    p = tmp_path / ".netmiko.yml"
    p.write_text(INV)
    inv = eos.load_inventory(p)
    assert set(inv) == {"leaf1", "leaf2"} and inv["leaf2"]["host"] == "172.20.20.12"


def test_running_config_and_replace(monkeypatch):
    FakeConn.sent, FakeConn.saved = [], 0
    monkeypatch.setattr(eos, "connect", FakeConn)
    assert eos.running_config({"host": "x"}).startswith("hostname leaf1")
    out = eos.replace_config({"host": "x"}, "hostname leaf1\nvlan 40\n   name GUESTS\nend\n")
    assert "vlan 40" in FakeConn.sent and FakeConn.saved == 1 and isinstance(out, str)
    assert "end" not in FakeConn.sent and FakeConn.sent[0] == "rollback clean-config" and FakeConn.sent[-1] == "commit"
    assert FakeConn.config_mode_commands == ["configure session infrahub-deploy"]


def test_rejected_line_aborts_the_session_without_commit(monkeypatch):
    FakeConn.sent, FakeConn.saved, FakeConn.reject = [], 0, True
    monkeypatch.setattr(eos, "connect", FakeConn)
    with pytest.raises(eos.DeployError) as exc:
        eos.replace_config({"host": "x"}, "hostname leaf1\ninterface Ethernet9\nend\n")
    FakeConn.reject = False
    assert "abort" in FakeConn.sent and "commit" not in FakeConn.sent and FakeConn.saved == 0
    assert "Invalid input" in str(exc.value)


def test_connection_failure_is_deploy_error(monkeypatch):
    class Boom:
        def __init__(self, **kw):
            raise TimeoutError("timed out")

    monkeypatch.setattr(eos, "connect", Boom)
    with pytest.raises(eos.DeployError):
        eos.replace_config({"host": "x"}, "hostname leaf1\nend\n")
