import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_mcp_json():
    cfg = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert set(cfg) == {"infrahub", "netmiko"}
    infrahub = " ".join(cfg["infrahub"]["args"])
    assert "infrahub-mcp==1.2.0" in infrahub and "agent/{date}-{hex}" in infrahub
    netmiko = " ".join(cfg["netmiko"]["args"])
    assert "netmiko-mcp==0.2.0" in netmiko and "netmiko/netmiko-mcp.yml" in netmiko


def test_build_agent_wiring(monkeypatch):
    import agent

    monkeypatch.setattr(agent.MCPClient, "load_servers", classmethod(lambda cls, cfg: []))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("INFRAHUB_ADDRESS", "http://localhost:8000")
    a = agent.build_agent()
    assert {"preview_config", "deploy_config"} <= set(a.tool_names)
    assert "deploy-guard" in a._plugin_registry._plugins
