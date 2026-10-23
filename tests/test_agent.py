import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_mcp_json():
    cfg = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert set(cfg) == {"infrahub", "netmiko"}
    infrahub = " ".join(cfg["infrahub"]["args"])
    # infrahub-mcp 1.2.0 runs through scripts/infrahub_mcp_stdio.py: one session branch for the process (opsmill/infrahub-mcp#187)
    assert "infrahub-mcp==1.2.0" in infrahub and "agent/{date}-{hex}" in infrahub
    assert "python scripts/infrahub_mcp_stdio.py" in infrahub
    assert "INFRAHUB_MCP_LOG_LEVEL=warning" in infrahub   # its info/debug logs otherwise flood the terminal
    netmiko = " ".join(cfg["netmiko"]["args"])
    assert "netmiko-mcp==0.2.0" in netmiko and "netmiko/netmiko-mcp.yml" in netmiko
    # both servers write banners, SSH chatter and validation warnings on stderr, which would land in the chat terminal
    assert "2>>logs/infrahub-mcp.log" in infrahub and "2>>logs/netmiko-mcp.log" in netmiko
    assert (ROOT / "logs" / ".gitkeep").exists() and "logs/*" in (ROOT / ".gitignore").read_text()


def test_build_agent_wiring(monkeypatch):
    import agent

    monkeypatch.setattr(agent.MCPClient, "load_servers", classmethod(lambda cls, cfg: []))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("INFRAHUB_ADDRESS", "http://localhost:8000")
    a = agent.build_agent()
    assert {"preview_config", "deploy_config"} <= set(a.tool_names)
    assert "deploy-guard" in a._plugin_registry._plugins
    cache = a.model.config.get("cache_config")   # ~90k input tokens per turn without it, mostly the same prefix
    assert cache is not None and cache.system_prompt_ttl and cache.tools_ttl


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
        accumulated_usage = {"inputTokens": 1200, "outputTokens": 340, "cacheReadInputTokens": 900, "cacheWriteInputTokens": 300}

    class Result:
        metrics = Metrics()

    # Anthropic counts the three input kinds separately: uncached, read from the cache, written to the cache
    assert agent.usage_line(Result()) == "[usage: input tokens 1200 uncached + 900 cache read + 300 cache write, output tokens 340]"
