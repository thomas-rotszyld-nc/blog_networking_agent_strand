import json
import os
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


def test_load_dotenv_never_overrides_the_shell(monkeypatch, tmp_path):
    """The key can stay out of .env: an exported ANTHROPIC_API_KEY wins over the file."""
    import agent

    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\nINFRAHUB_ADDRESS=http://from-file:8000\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    monkeypatch.delenv("INFRAHUB_ADDRESS", raising=False)
    agent.load_dotenv(env)
    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"
    assert os.environ["INFRAHUB_ADDRESS"] == "http://from-file:8000"


def test_usage_line_sums_the_tokens_of_a_result():
    """One-shot runs end with a token count on stderr, so a reader can price a demo session."""
    import agent

    class Metrics:
        accumulated_usage = {"inputTokens": 1200, "outputTokens": 340, "cacheReadInputTokens": 900, "cacheWriteInputTokens": 0}

    class Result:
        metrics = Metrics()

    assert agent.usage_line(Result()) == "[usage: 1200 input tokens (900 read from cache), 340 output tokens]"
