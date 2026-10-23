import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_install_sh_static():
    s = (ROOT / "install.sh").read_text()
    assert s.startswith("#!/bin/sh") and "set -e" in s
    for pin in ("infrahub.opsmill.io/1.11.9", "netmiko-mcp==0.2.0", "ceos:lab", "clab/vlan-lab.clab.yml",
                "infrahubctl schema load", "infrahubctl object load", "repository add", "--read-only"):
        assert pin in s, pin
    assert re.search(r"sudo containerlab", s) and not re.search(r"sudo (uv|docker|curl)", s)
    for f in ("install.sh", "uninstall.sh", "scripts/reimport.sh"):
        assert subprocess.run(["sh", "-n", str(ROOT / f)]).returncode == 0, f


def test_install_sh_reports_all_missing_prereqs():
    r = subprocess.run(["sh", str(ROOT / "install.sh"), "--check-prereqs"], cwd=ROOT, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(ROOT)})
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "images/" in out and "containerlab" in out


def test_install_sh_checks_survive_set_e_and_rerun_after_the_demo():
    s = (ROOT / "install.sh").read_text()
    assert "$?" not in s                      # every check captures its status with `|| rc=$?`
    assert "len(vlans) >= 3" in s             # VLAN 40 added by the demo must not break a re-run
    assert "--env-file infrahub/.env" in s    # only the three compose secrets reach the containers
    assert "--env-file .env" not in s
    assert "infrahub/.env" in (ROOT / ".gitignore").read_text()


def _debian_family() -> bool:
    try:
        return any(w in pathlib.Path("/etc/os-release").read_text().lower() for w in ("debian", "ubuntu"))
    except OSError:
        return False


def test_install_sh_install_prereqs_is_opt_in():
    s = (ROOT / "install.sh").read_text()
    assert "--install-prereqs" in s
    for src in ("get.docker.com", "get.containerlab.dev", "astral.sh/uv/install.sh", "usermod -aG docker"):
        assert src in s, src
    env = {"PATH": "/usr/bin:/bin", "HOME": str(ROOT)}
    r = subprocess.run(["sh", str(ROOT / "install.sh"), "--check-prereqs"], cwd=ROOT, capture_output=True, text=True, env=env)
    assert "--install-prereqs" in r.stdout + r.stderr   # the check only reports, and names the option
    if not _debian_family():                            # elsewhere the option refuses instead of guessing
        r = subprocess.run(["sh", str(ROOT / "install.sh"), "--install-prereqs"], cwd=ROOT, capture_output=True,
                           text=True, env=env)
        assert r.returncode == 1 and "Ubuntu" in r.stdout + r.stderr


def test_install_sh_runs_docker_native_and_verifies_the_token_before_loading():
    s = (ROOT / "install.sh").read_text()
    assert "unset DOCKER_DEFAULT_PLATFORM" in s            # a Mac shell exporting linux/amd64 would emulate everything
    i_up = s.index("/api/config")                           # Infrahub answers...
    i_tok = s.index("infrahubctl info")                     # ...then the token is verified...
    i_schema = s.index("infrahubctl schema load")           # ...before anything is loaded
    assert i_up < i_tok < i_schema
    assert "uninstall.sh --purge" in s                      # the remedy when the data volumes outlived the .env


def test_netmiko_mcp_runs_on_mcp_1x():
    # netmiko-mcp 0.2.0 imports mcp.server.fastmcp, removed in mcp 2.x; an unpinned uvx resolves 2.x and crashes at start
    mcp_json = (ROOT / ".mcp.json").read_text()
    assert "netmiko-mcp==0.2.0" in mcp_json and "mcp<2" in mcp_json
    s = (ROOT / "install.sh").read_text()
    assert "mcp<2" in s and "uv tool install" not in s   # the same uvx environment as .mcp.json, pre-built at install


def test_reimport_waits_for_the_re_rendering():
    # right after an import the old artifacts are still Ready: without --until-changed the script downloads stale files
    assert "--until-changed" in (ROOT / "scripts/reimport.sh").read_text()


def test_install_sh_keeps_mcp_server_noise_out_of_the_tool_check():
    s = (ROOT / "install.sh").read_text()
    assert "vlan-lab-agent.err" in s        # MCP servers chat on stderr at startup; shown only when the check fails


def test_install_sh_requires_the_render_tool():
    assert "render_configs" in (ROOT / "install.sh").read_text()


def test_install_sh_accepts_the_anthropic_key_from_the_shell():
    """The final hint looks at the environment (shell export or .env), and recommends the export."""
    script = (ROOT / "install.sh").read_text()
    assert '[ -n "${ANTHROPIC_API_KEY:-}" ]' in script
    assert "export %s=" in script and "hint ANTHROPIC_API_KEY" in script


def test_install_sh_re_renders_main_after_loading_the_objects():
    """A re-run reloads the seed objects (Ethernet3 back on IOT) but Infrahub re-renders nothing by itself: without an
    explicit rendering, clab/generated and the leafs would follow stale artifacts that no longer match the data."""
    script = (ROOT / "install.sh").read_text()
    step5 = script[script.index('step "5/9'):script.index('step "6/9')]
    assert "render_artifacts" in step5
    assert step5.index("render_artifacts") < step5.index("--out clab/generated")   # rendered first, then downloaded


def test_install_sh_stops_when_a_download_or_environment_build_fails():
    """Review: `cmd && echo ok` under set -e does not stop the script when cmd fails; the netmiko-mcp environment,
    the apt install and the Docker script must fail loudly instead of letting later steps hit confusing errors."""
    s = (ROOT / "install.sh").read_text()
    assert "import netmiko_mcp.server\" || fail" in s
    assert "apt-get install -y -qq git curl ca-certificates || fail" in s
    assert "sudo sh \"$DOCKER_SCRIPT\" || fail" in s and "DOCKER_SCRIPT=$(mktemp)" in s


def test_install_sh_asks_for_the_model_provider_once_and_keeps_it():
    """Step 1 asks the reader which provider to use (Enter = Anthropic), writes MODEL_PROVIDER to .env and, like the
    tokens, keeps it on re-runs; --provider answers without the prompt (re-runs, no terminal)."""
    s = (ROOT / "install.sh").read_text()
    step1 = s[s.index('step "1/9'):s.index('step "2/9')]
    assert "getenv MODEL_PROVIDER" in step1 and "MODEL_PROVIDER=$PROVIDER" in step1
    assert "read " in step1 and "anthropic" in step1 and "openai" in step1 and "gemini" in step1
    assert "--provider" in s[:s.index('step "0/9')]       # parsed before anything runs


def test_install_sh_refuses_an_unknown_provider_before_doing_anything():
    r = subprocess.run(["sh", str(ROOT / "install.sh"), "--provider", "mistral"], cwd=ROOT, capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(ROOT)})
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "anthropic" in out and "openai" in out and "gemini" in out
    assert "prerequisites" not in out


def test_install_sh_final_hint_names_the_key_of_the_chosen_provider():
    s = (ROOT / "install.sh").read_text()
    tail = s[s.index("Lab ready"):]
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        assert var in tail, var


def test_install_sh_never_writes_an_empty_key_line_to_dotenv():
    """Step 2 sources .env with `set -a`: an `ANTHROPIC_API_KEY=` line written for a reader who exports the key in the
    shell blanked that export, and the final hint then asked for a key that was there. Empty keys become a comment."""
    s = (ROOT / "install.sh").read_text()
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        assert f"{var}=$" not in s, var                     # no unconditional KEY=$VALUE line in the heredoc
        assert f"keyline {var}" in s, var
    keyline = next(line for line in s.splitlines() if line.startswith("keyline()"))
    r = subprocess.run(["sh", "-c", keyline + '; keyline OPENAI_API_KEY ""; keyline OPENAI_API_KEY sk-test'],
                       capture_output=True, text=True)
    lines = r.stdout.splitlines()
    assert lines[0].startswith("#") and "OPENAI_API_KEY" in lines[0]     # a comment: sourcing it changes nothing
    assert lines[1] == "OPENAI_API_KEY=sk-test"                           # a kept value is written as before
