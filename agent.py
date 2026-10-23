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
Environment: ANTHROPIC_API_KEY (export it in your shell, or put it in .env), INFRAHUB_ADDRESS, INFRAHUB_API_TOKEN
(install.sh writes the last two to .env; .env never overrides a variable already exported).
"""

import os
import sys
from pathlib import Path

from strands import Agent, AgentSkills
from strands.models.anthropic import AnthropicModel
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


def load_dotenv(path: Path = Path(".env")) -> None:
    """Puts the KEY=value lines of .env into the environment, without overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
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


def build_agent() -> Agent:
    """The agent: Anthropic model, the two MCP servers of .mcp.json, the two local tools, hooks, steering and skills."""
    servers = MCPClient.load_servers(".mcp.json")
    infrahub = servers[0] if servers else None  # .mcp.json lists infrahub first; the hook only needs call_tool_sync
    base_url = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000")
    model = AnthropicModel(model_id="claude-opus-5-5", max_tokens=16000)  # ANTHROPIC_API_KEY from the environment
    return Agent(model=model, tools=[*servers, render_configs, preview_config, deploy_config], system_prompt=SYSTEM_PROMPT,
                 callback_handler=chat_handler, context_manager="auto",
                 hooks=[ShowInfrahubLinks(infrahub, base_url), ConfirmDeploy()],
                 plugins=[AgentSkills(skills=["skills"], strict=True), DeployGuard()])


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
        agent(question)


def usage_line(result) -> str:
    """Token count of a run, for the cost section of the README: input (with the part read from the cache) and output."""
    usage = result.metrics.accumulated_usage
    return (f"[usage: {usage.get('inputTokens', 0)} input tokens ({usage.get('cacheReadInputTokens', 0)} read from cache), "
            f"{usage.get('outputTokens', 0)} output tokens]")


def main() -> None:
    """--list-tools, one shot with the question on the command line, or the interactive chat."""
    load_dotenv()
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
