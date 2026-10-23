"""Access to the lab switches with Netmiko: inventory, running configuration, atomic replacement.

The inventory is the same `.netmiko.yml` netmiko-mcp uses (written by install.sh), so devices and credentials live
in one place. Replacement goes through an EOS configuration session: `rollback clean-config` empties the candidate,
the rendered configuration is pasted, `commit` applies it atomically, then `write memory`. Nothing here decides what
to send: the configuration always comes from Infrahub (see vlanlab/infrahub_tools.py).
"""

import secrets
from datetime import datetime
from pathlib import Path

from netmiko import ConnectHandler
from netmiko.utilities import load_yaml_file, obtain_all_devices

INVENTORY_FILE = Path("netmiko/.netmiko.yml")
connect = ConnectHandler  # swapped by the tests


class DeployError(Exception):
    """The configuration could not be applied, or the switch stopped answering afterwards."""


def load_inventory(path: Path = INVENTORY_FILE) -> dict[str, dict]:
    """{device name: Netmiko connection parameters}; groups (lists) of the Netmiko Tools format are skipped."""
    devices = obtain_all_devices(load_yaml_file(str(path)))
    return {name: params for name, params in devices.items() if isinstance(params, dict)}


def running_config(params: dict) -> str:
    """`show running-config` of one switch."""
    with connect(**params) as conn:
        return conn.send_command("show running-config", read_timeout=60)


def _config_lines(config: str) -> list[str]:
    """The lines to paste into a configuration session: no comments, no blank lines, no trailing `end`."""
    lines = [line.rstrip() for line in config.splitlines()]
    return [line for line in lines if line.strip() and not line.startswith("!") and line.strip() != "end"]


def session_command() -> str:
    """`configure session <name>` with a name no deployment used before: EOS keeps a committed session as "completed"
    and refuses to enter a session of that name again (`% Cannot enter session ... (already completed)`)."""
    return f"configure session infrahub-{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(2)}"


def replace_config(params: dict, config: str) -> str:
    """Replaces the whole running configuration with `config`, saves it, and checks the switch still answers.

    The lines are pasted into a configuration session after `rollback clean-config`. EOS answers `% Invalid input`
    (or another `%` error) to a line it rejects; if any such line comes back, the session is aborted and nothing is
    committed: the replacement is all or nothing. Only a clean paste is committed, then saved.
    """
    host = params.get("host", "?")
    try:
        with connect(**params) as conn:
            output = conn.send_config_set(["rollback clean-config", *_config_lines(config)], config_mode_command=session_command(),
                                          exit_config_mode=False, cmd_verify=False, read_timeout=120)
            rejected = [line.strip() for line in output.splitlines() if line.lstrip().startswith("%")]
            if rejected:
                conn.send_command_timing("abort")
                raise DeployError(f"{host}: the switch rejected part of the rendering, session aborted, nothing committed: "
                                  + " | ".join(rejected[:5]))
            output += "\n" + conn.send_command_timing("commit")
            output += "\n" + conn.save_config()
        with connect(**params) as conn:  # a fresh session proves management access survived the replacement
            hostname = conn.send_command("show hostname")
    except DeployError:
        raise
    except Exception as exc:  # Netmiko raises many types; the caller only needs one
        raise DeployError(f"{host}: {exc}") from exc
    return f"{output}\nswitch answers after commit: {hostname.strip()}"
