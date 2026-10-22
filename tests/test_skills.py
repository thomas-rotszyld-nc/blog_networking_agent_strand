import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def fm(p):
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S)
    assert m, p
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


def test_skills_frontmatter_and_tools():
    change, deploy, check = (ROOT / f"skills/{n}/SKILL.md" for n in ("infrahub-change", "deploy-config", "vlan-check"))
    assert fm(change)["name"] == "infrahub-change" and fm(deploy)["name"] == "deploy-config" and fm(check)["name"] == "vlan-check"
    t = change.read_text()
    assert all(k in t for k in ("mutate_graphql", "get_session_info", "propose_changes", "IpamVLANCreate", "untagged_vlan"))
    t = deploy.read_text()
    assert all(k in t for k in ("preview_config", "deploy_config")) and "no difference" in t
    t = check.read_text()
    assert "send_show_command" in t and "show vlan" in t


def test_agent_skills_plugin_loads_them():
    from strands import AgentSkills

    AgentSkills(skills=[str(ROOT / "skills")], strict=True)
