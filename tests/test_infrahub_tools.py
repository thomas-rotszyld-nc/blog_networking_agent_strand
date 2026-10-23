import json
from types import SimpleNamespace

from vlanlab import infrahub_tools as it

RUNNING = "! Command: show running-config\n! device: leaf1 (cEOSLab)\n!\nhostname leaf1\n!\nvlan 10\n   name USERS\n!\nend\n"
RENDERED = "hostname leaf1\n!\nvlan 10\n   name USERS\n!\nend\n"


def test_normalize_ignores_comments_blank_and_end():
    assert it.normalize(RUNNING) == it.normalize(RENDERED) == ["hostname leaf1", "vlan 10", "   name USERS"]
    assert it.config_diff(RUNNING, RENDERED) == ""
    assert "+vlan 40" in it.config_diff(RUNNING, RENDERED + "vlan 40\n   name GUESTS\n")


def test_diff_ignores_block_order_and_hashed_secrets():
    running = "username admin privilege 15 role network-admin secret sha512 $6$abc\n!\nvlan 10\n   name USERS\n!\nhostname leaf1\n!\nend\n"
    rendered = "hostname leaf1\n!\nusername admin privilege 15 role network-admin secret admin\n!\nvlan 10\n   name USERS\n!\nend\n"
    assert it.config_diff(running, rendered) == ""
    assert "username" in it.config_diff(running, rendered.replace("username admin", "username bob"))


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

    def missing(device, **kw):
        raise it.ArtifactNotReady(device)

    monkeypatch.setattr(it, "fetch_artifact", missing)
    out = it.preview_config(device="leaf1")
    assert out.startswith("Error:") and "artifact" in out.lower()


def test_deploy_pushes_rendered_and_reports(monkeypatch):
    pushed = patch_backend(monkeypatch, rendered=RENDERED + "vlan 40\n   name GUESTS\n")
    out = it.deploy_config(device="leaf1")
    assert pushed and "GUESTS" in pushed[0] and out.startswith("leaf1:")


def test_deploy_errors_are_strings(monkeypatch):
    patch_backend(monkeypatch)

    def boom(params, cfg):
        raise it.DeployError("ssh lost")

    monkeypatch.setattr(it, "replace_config", boom)
    assert it.deploy_config(device="leaf1").startswith("Error:")


def test_tools_are_strands_tools():
    assert it.preview_config.tool_name == "preview_config" and it.deploy_config.tool_name == "deploy_config"
    assert it.deploy_config.tool_spec["inputSchema"]["json"]["required"] == ["device"]


def event(name, result, inputs=None):
    return SimpleNamespace(tool_use={"name": name, "input": inputs or {}}, cancel_message=None, exception=None,
                           result={"status": "success", "content": [{"text": json.dumps(result)}]})


def test_show_links(capsys):
    hook = it.ShowInfrahubLinks(infrahub=None, base_url="http://localhost:8000", generate=lambda branch: None)
    hook.session_branch = lambda: "agent/20261022-ab12"
    hook.show(event("node_upsert", {"id": "u1", "display_label": "GUESTS", "branch": "agent/20261022-ab12"}, {"kind": "IpamVLAN"}))
    hook.show(event("propose_changes", {"id": "pc1", "source_branch": "agent/20261022-ab12"}))
    hook.show(event("mutate_graphql", {"IpamVLANCreate": {"ok": True, "object": {"id": "u2"}}}))
    hook.show(event("get_nodes", {"nodes": []}))
    out = capsys.readouterr().out
    assert "http://localhost:8000/objects/IpamVLAN/u1?branch=agent/20261022-ab12" in out
    assert "http://localhost:8000/proposed-changes/pc1" in out
    assert "u2" in out and "agent/20261022-ab12" in out and out.count("[infrahub:") == 4   # 4th: rendering on the branch


def test_show_links_never_raises(capsys):
    hook = it.ShowInfrahubLinks(infrahub=None, base_url="http://x")
    hook.show(SimpleNamespace(tool_use={"name": "node_upsert", "input": {}}, cancel_message=None, exception=None,
                              result={"status": "error", "content": [{"text": "boom"}]}))
    hook.show(event("mutate_graphql", "not a dict"))
    hook.show(event("propose_changes", {"no_id": True}))


def test_show_links_renders_the_branch_after_a_proposed_change(capsys):
    asked = []
    hook = it.ShowInfrahubLinks(infrahub=None, base_url="http://localhost:8000", generate=lambda branch: asked.append(branch))
    hook.show(event("propose_changes", {"id": "pc1", "source_branch": "agent/20261023-ab12", "destination_branch": "main"}))
    out = capsys.readouterr().out
    assert asked == ["agent/20261023-ab12"]
    assert "rendering" in out and "agent/20261023-ab12" in out


def test_render_configs_tool_reports_per_device(monkeypatch):
    monkeypatch.setattr(it, "render_artifacts", lambda devices, **kw: {d: d == "leaf1" for d in devices})
    monkeypatch.setattr(it, "load_inventory", lambda: {"leaf1": {}, "leaf2": {}})
    out = it.render_configs()
    assert "leaf1: re-rendered" in out and "leaf2: unchanged" in out
    monkeypatch.setattr(it, "render_artifacts", lambda devices, **kw: (_ for _ in ()).throw(TimeoutError("slow")))
    assert it.render_configs().startswith("Error:")
    assert it.render_configs.tool_name == "render_configs"


def test_deploy_result_is_a_summary_and_the_session_log_goes_to_a_file(monkeypatch, tmp_path):
    # live run: the EOS session echoes every line with its prompt (60+ lines) — that is for a log file, not for the model
    patch_backend(monkeypatch, rendered=RENDERED + "vlan 40\n   name GUESTS\n")
    echo = "\n".join(f"leaf1(config-s-infrahub-d)#{line}" for line in RENDERED.splitlines()) + "\ncommit\ncopy running-config startup-config\nswitch answers after commit: Hostname: leaf1"
    monkeypatch.setattr(it, "replace_config", lambda params, cfg: echo)
    monkeypatch.setattr(it, "DEPLOY_LOG_DIR", tmp_path)
    out = it.deploy_config(device="leaf1")
    assert out.startswith("leaf1: configuration replaced and saved") and out.count("\n") <= 3 and "config-s" not in out
    log = tmp_path / "deploy-leaf1.log"
    assert log.exists() and "config-s-infrahub-d" in log.read_text() and str(log) in out
