"""A Strands agent between Infrahub and the lab switches, as a turn-by-turn chat on the terminal.

Tools come from two MCP servers declared in .mcp.json (the file Claude Code reads too) and two functions of this repo:

  infrahub   infrahub-mcp, the official OpsMill server: reads Infrahub, writes on a session branch, opens Proposed Changes
  netmiko    netmiko-mcp, the official Netmiko server, read-only: `show vlan`, `show running-config`
  render_configs / preview_config / deploy_config   vlanlab/infrahub_tools.py: re-render, diff and deploy Infrahub's configuration

Guards: DeployGuard (steering, refuses unsafe or too many deployments), ConfirmDeploy (asks on the terminal),
ShowInfrahubLinks (prints the branch and links of what the agent wrote in Infrahub). Skills in skills/.

  uv run python agent.py                  # interactive: one question per turn, the conversation is kept
  uv run python agent.py "your question"  # one shot
  uv run python agent.py --list-tools     # start the MCP servers, print the tool names, exit (used by install.sh)

In the chat, an empty line, "exit", "quit" or Ctrl-D ends the session; "/reset" clears the conversation.
Environment: MODEL_PROVIDER (anthropic, the default, openai or gemini; install.sh asks and writes it to .env), MODEL_ID
(optional, replaces the provider's default model), the provider's key (ANTHROPIC_API_KEY, OPENAI_API_KEY or
GEMINI_API_KEY: export it in your shell, or put it in .env), INFRAHUB_ADDRESS, INFRAHUB_API_TOKEN
(install.sh writes the last two to .env; .env never overrides a variable already exported). The MCP servers see only .env:
the MCP SDK starts a stdio server with six variables of the environment (HOME, PATH...), so .mcp.json loads .env itself.
When a server fails to start, its stderr in logs/ says why; the agent quotes it and exits.
"""

import os
import re
import sys
from pathlib import Path

from strands import Agent, AgentSkills
from strands.models.model import CacheConfig
from strands.tools.mcp import MCPClient

from vlanlab.guards import ConfirmDeploy, DeployGuard
from vlanlab.infrahub_tools import ShowInfrahubLinks, deploy_config, preview_config, render_configs

SYSTEM_PROMPT = """You are a network automation assistant for a small lab: two Arista leaf switches (leaf1, leaf2) and
Infrahub as the source of truth. Infrahub generates the complete configuration of each switch from its data.
Changes of intent (VLANs, interface assignments) go to Infrahub through its tools, always on your session branch, and
end with a proposed change that a human reviews and merges; you never write to the default branch.
Switches are read with the netmiko tools and written only with deploy_config, which deploys the configuration Infrahub
rendered and nothing else: never send configuration lines yourself, never compose configuration text.
Before any deployment, run preview_config and show the user what changes; the user confirms on the terminal.
When a request matches one of the available skills, activate it with the skills tool and follow its procedure.
Be concise, answer in the user's language, and report refusals or errors as they are."""


LOGS = Path("logs")   # where .mcp.json sends the servers' stderr: logs/<server>-mcp.log
MAX_TOKENS = 16000
PROVIDERS = {   # MODEL_PROVIDER: (default model, key variable). The defaults sit at the price level of Claude Opus 5.5.
    "anthropic": ("claude-opus-5-5", "ANTHROPIC_API_KEY"),
    "openai": ("gpt-6.1-sol", "OPENAI_API_KEY"),
    "gemini": ("gemini-4-argon", "GEMINI_API_KEY"),
}


def load_dotenv(path: Path = Path(".env")) -> None:
    """Puts the KEY=value lines of .env into the environment, without overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.strip().strip('"'):   # install.sh writes `ANTHROPIC_API_KEY=` when it knows no key: leave it unset
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def chat_handler(**kwargs) -> None:
    """Callback handler of the Agent: streams the answer to stdout, and prints one line per tool call."""
    if data := kwargs.get("data"):
        print(data, end="", flush=True)
    if tool := kwargs.get("current_tool_use"):
        if tool.get("toolUseId") != chat_handler.last_tool:
            chat_handler.last_tool = tool["toolUseId"]
            print(f"\n  [tool: {tool['name']}]", flush=True)
    if kwargs.get("complete"):
        print()


chat_handler.last_tool = None  # toolUseId of the last tool call shown


def mcp_log_offsets() -> dict[Path, int]:
    """Size of each server log before the servers start: what follows is this run's."""
    return {log: log.stat().st_size for log in LOGS.glob("*-mcp.log")}


def mcp_startup_error(offsets: dict[Path, int]) -> str:
    """Why a server did not start. Strands reports 'unhandled errors in a TaskGroup' and hides the cause, which is the
    last exception the server wrote on stderr since the agent started (earlier runs leave their own errors in the file)."""
    found = []
    for log in sorted(LOGS.glob("*-mcp.log")):
        new_lines = log.read_text(errors="replace")[offsets.get(log, 0):].splitlines()
        errors = [line for line in new_lines if re.match(r"\w*(Error|Exception)\b", line)]
        if errors:
            found.append(f"  {log}: {errors[-1]}")
    detail = "\n".join(found) or f"  nothing new in {LOGS}/*-mcp.log: run the server's command of .mcp.json by hand to see it fail"
    return f"an MCP server of .mcp.json did not start; its stderr is in {LOGS}/:\n{detail}"


def provider() -> tuple[str, str, str]:
    """(provider, model id, key variable) from MODEL_PROVIDER and MODEL_ID; exits on a provider the lab does not know."""
    name = os.environ.get("MODEL_PROVIDER", "anthropic").strip().lower()
    if name not in PROVIDERS:
        raise SystemExit(f"MODEL_PROVIDER={name!r} in .env or the shell: the lab knows anthropic, openai and gemini"
                         " (sh install.sh --provider <name> rewrites .env)")
    default_model, key_var = PROVIDERS[name]
    return name, os.environ.get("MODEL_ID") or default_model, key_var


def build_model():
    """The Strands model of the chosen provider. Its client reads the key from the environment. The prompt cache is an
    Anthropic feature: with it, almost all of a turn's input is read from the cache (see the cost section of the README)."""
    name, model_id, key_var = provider()
    if name == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(model_id=model_id, max_tokens=MAX_TOKENS,
                              cache_config=CacheConfig(ttl="5m", system_prompt_ttl=True, tools_ttl=True))  # the prefix is the same every turn
    if name == "openai":
        from strands.models.openai import OpenAIModel

        # the OpenAI client refuses to construct without a key; install.sh lists the tools before the reader has one
        client_args = {} if os.environ.get(key_var) else {"api_key": "unset"}
        return OpenAIModel(client_args=client_args, model_id=model_id, params={"max_completion_tokens": MAX_TOKENS})
    from strands.models.gemini import GeminiModel

    return GeminiModel(model_id=model_id, params={"max_output_tokens": MAX_TOKENS})


def missing_key_hint() -> str | None:
    """One line for the terminal when the chosen provider's key is not set; None when it is."""
    name, _, key_var = provider()
    if os.environ.get(key_var) or (name == "gemini" and os.environ.get("GOOGLE_API_KEY")):
        return None
    return f"{key_var} is not set: export it in your shell (or put it in .env) before asking the agent anything"


def build_agent() -> Agent:
    """The agent: the model of MODEL_PROVIDER, the two MCP servers of .mcp.json, the two local tools, hooks, steering, skills."""
    servers = MCPClient.load_servers(".mcp.json")
    infrahub = servers[0] if servers else None  # .mcp.json lists infrahub first; the hook only needs call_tool_sync
    base_url = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000")
    model = build_model()
    offsets = mcp_log_offsets()
    try:
        return Agent(model=model, tools=[*servers, render_configs, preview_config, deploy_config], system_prompt=SYSTEM_PROMPT,
                     callback_handler=chat_handler, context_manager="auto",
                     hooks=[ShowInfrahubLinks(infrahub, base_url), ConfirmDeploy()],
                     plugins=[AgentSkills(skills=["skills"], strict=True), DeployGuard()])
    except ValueError as e:   # Agent() starts the MCP servers: a server that dies at start surfaces here, cause hidden
        if "Failed to start MCP client" not in str(e):
            raise
        raise SystemExit(f"{mcp_startup_error(offsets)}\n({e})") from None


def chat(agent: Agent) -> None:
    """Interactive loop: one question per turn, the conversation kept in agent.messages until /reset or exit."""
    print("Infrahub lab agent. One question per turn; empty line, exit, quit or Ctrl-D to leave; /reset to forget the conversation.")
    while True:
        try:
            question = input("\nyou> ").strip()
        except EOFError:
            print()
            break
        if question in ("", "exit", "quit"):
            break
        if question == "/reset":
            agent.messages.clear()
            print("conversation cleared")
            continue
        print("agent> ", end="", flush=True)
        result = agent(question)
        print(usage_line(result, "usage, session total"), file=sys.stderr)


def usage_line(result, label: str = "usage") -> str:
    """Token count, for the cost section of the README. Anthropic bills the three kinds of input tokens differently:
    uncached, read from the cache, written to the cache. Strands accumulates the counters over the agent's life, so in
    the chat the line is the session total."""
    u = result.metrics.accumulated_usage
    return (f"[{label}: input tokens {u.get('inputTokens', 0)} uncached + {u.get('cacheReadInputTokens', 0)} cache read"
            f" + {u.get('cacheWriteInputTokens', 0)} cache write, output tokens {u.get('outputTokens', 0)}]")


def main() -> None:
    """--list-tools, one shot with the question on the command line, or the interactive chat."""
    load_dotenv()
    if hint := missing_key_hint():
        print(hint, file=sys.stderr)
    agent = build_agent()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--list-tools":
            print("\n".join(agent.tool_names))  # starts the MCP servers
        elif len(sys.argv) > 1:
            result = agent(" ".join(sys.argv[1:]))
            print(usage_line(result), file=sys.stderr)
        else:
            chat(agent)
    finally:
        agent.cleanup()  # stops the MCP server processes


if __name__ == "__main__":
    main()
