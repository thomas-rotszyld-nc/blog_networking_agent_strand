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
    # the MCP SDK hands a stdio server six variables of the environment (HOME, PATH...), so the servers see .env and nothing
    # else; a .env without INFRAHUB_ADDRESS must still start the server, with the default agent.py and vlanlab already use
    assert ". ./.env; INFRAHUB_ADDRESS=${INFRAHUB_ADDRESS:-http://localhost:8000}" in infrahub
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
    monkeypatch.setenv("INFRAHUB_ADDRESS", "placeholder"); monkeypatch.delenv("INFRAHUB_ADDRESS")   # restored after the test
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


def test_chat_prints_the_usage_line_after_each_turn(monkeypatch, capsys):
    """The interactive loop reports tokens too, so the cost of a whole demo session can be added up."""
    import agent

    class Metrics:
        accumulated_usage = {"inputTokens": 5, "outputTokens": 7, "cacheReadInputTokens": 11, "cacheWriteInputTokens": 0}

    class Result:
        metrics = Metrics()

    class FakeAgent:
        messages = []

        def __call__(self, question):
            return Result()

    answers = iter(["hello", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    agent.chat(FakeAgent())
    # Strands' accumulated_usage covers every invocation of the agent, so the chat says so
    assert "[usage, session total: input tokens 5 uncached + 11 cache read + 0 cache write, output tokens 7]" in capsys.readouterr().err


def test_load_dotenv_skips_empty_values(monkeypatch, tmp_path):
    # review: install.sh writes `ANTHROPIC_API_KEY=` when no key is known; an empty variable gave the SDK's
    # "invalid x-api-key" instead of its clear missing-key error
    import agent

    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=\nINFRAHUB_ADDRESS=http://x:8000\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("INFRAHUB_ADDRESS", "placeholder"); monkeypatch.delenv("INFRAHUB_ADDRESS")   # restored after the test
    agent.load_dotenv(env)
    assert "ANTHROPIC_API_KEY" not in os.environ and os.environ["INFRAHUB_ADDRESS"] == "http://x:8000"


def test_mcp_startup_error_quotes_what_the_server_wrote_since_the_start(tmp_path, monkeypatch):
    """Strands hides the cause of a server start failure behind 'unhandled errors in a TaskGroup'; the cause is the last
    exception the server wrote on stderr, in logs/, after the agent started (earlier runs leave their own errors there)."""
    import agent

    logs = tmp_path / "logs"; logs.mkdir()
    monkeypatch.setattr(agent, "LOGS", logs)
    (logs / "infrahub-mcp.log").write_text("Traceback (most recent call last):\nRuntimeError: stale error of an earlier run\n")
    offsets = agent.mcp_log_offsets()
    with (logs / "infrahub-mcp.log").open("a") as f:
        f.write("Traceback (most recent call last):\n  File x\nRuntimeError: INFRAHUB_ADDRESS is required. Set it.\n")
    (logs / "netmiko-mcp.log").write_text("INFO Processing request\n")   # created after the start, no error
    msg = agent.mcp_startup_error(offsets)
    assert "RuntimeError: INFRAHUB_ADDRESS is required. Set it." in msg and "stale" not in msg
    assert "infrahub-mcp.log" in msg and "netmiko-mcp.log" not in msg and ".mcp.json" in msg


def test_mcp_startup_error_without_a_new_error_says_so(tmp_path, monkeypatch):
    import agent

    logs = tmp_path / "logs"; logs.mkdir()
    monkeypatch.setattr(agent, "LOGS", logs)
    msg = agent.mcp_startup_error(agent.mcp_log_offsets())
    assert "nothing new" in msg and ".mcp.json" in msg


def test_build_agent_turns_a_server_start_failure_into_a_readable_exit(monkeypatch, tmp_path):
    import pytest

    import agent

    logs = tmp_path / "logs"; logs.mkdir()
    monkeypatch.setattr(agent, "LOGS", logs)
    monkeypatch.setattr(agent.MCPClient, "load_servers", classmethod(lambda cls, cfg: []))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def failing_agent(*args, **kwargs):
        (logs / "infrahub-mcp.log").write_text("RuntimeError: Authentication required. Set INFRAHUB_API_TOKEN\n")
        raise ValueError("Failed to load tool <MCPClient>: Failed to start MCP client: unhandled errors in a TaskGroup (1 sub-exception)")

    monkeypatch.setattr(agent, "Agent", failing_agent)
    with pytest.raises(SystemExit) as exc:
        agent.build_agent()
    assert "Authentication required" in str(exc.value) and "logs/" in str(exc.value)

    def other_failure(*args, **kwargs):
        raise ValueError("something else")

    monkeypatch.setattr(agent, "Agent", other_failure)
    with pytest.raises(ValueError, match="something else"):   # only server start failures are translated
        agent.build_agent()


def _provider_env(monkeypatch, provider=None, model_id=None, **keys):
    for var in ("MODEL_PROVIDER", "MODEL_ID", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    if provider:
        monkeypatch.setenv("MODEL_PROVIDER", provider)
    if model_id:
        monkeypatch.setenv("MODEL_ID", model_id)
    for var, value in keys.items():
        monkeypatch.setenv(var, value)


def test_build_model_defaults_to_anthropic_opus_with_caching(monkeypatch):
    """No MODEL_PROVIDER in .env: the lab runs as before, Claude Opus 5.5 with the prompt cache on."""
    import agent

    _provider_env(monkeypatch, ANTHROPIC_API_KEY="test")
    m = agent.build_model()
    assert type(m).__name__ == "AnthropicModel" and m.get_config()["model_id"] == "claude-opus-5-5"
    cache = m.get_config().get("cache_config")
    assert cache is not None and cache.system_prompt_ttl and cache.tools_ttl


def test_build_model_openai_and_gemini_with_their_default_models(monkeypatch):
    """One model per provider, at the price level of Opus 5.5; MODEL_ID in .env overrides it."""
    import agent

    _provider_env(monkeypatch, "openai", OPENAI_API_KEY="test")
    m = agent.build_model()
    assert type(m).__name__ == "OpenAIModel" and m.get_config()["model_id"] == "gpt-6.1-sol"
    _provider_env(monkeypatch, "gemini", GEMINI_API_KEY="test")
    m = agent.build_model()
    assert type(m).__name__ == "GeminiModel" and m.get_config()["model_id"] == "gemini-4-argon"
    _provider_env(monkeypatch, "openai", model_id="gpt-6-astra", OPENAI_API_KEY="test")
    assert agent.build_model().get_config()["model_id"] == "gpt-6-astra"


def test_build_model_constructs_without_the_key(monkeypatch):
    """install.sh step 8 lists the tools before the reader has exported a key: the OpenAI and Gemini clients refuse to
    construct without one, so the model is built with a placeholder and the hint names the variable to export."""
    import agent

    for provider, var in (("openai", "OPENAI_API_KEY"), ("gemini", "GEMINI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")):
        _provider_env(monkeypatch, provider)
        agent.build_model()                              # no exception
        assert var in agent.missing_key_hint()
    _provider_env(monkeypatch, "openai", OPENAI_API_KEY="test")
    assert agent.missing_key_hint() is None


def test_build_model_rejects_an_unknown_provider(monkeypatch):
    import pytest

    import agent

    _provider_env(monkeypatch, "mistral")
    with pytest.raises(SystemExit) as exc:
        agent.build_model()
    assert "anthropic" in str(exc.value) and "openai" in str(exc.value) and "gemini" in str(exc.value)


def test_pyproject_installs_the_three_providers():
    """Switching provider in .env must not require a reinstall."""
    s = (ROOT / "pyproject.toml").read_text()
    assert "strands-agents[anthropic,gemini,openai]" in s
