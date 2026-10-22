"""Access to the lab switches with Netmiko: inventory, running configuration, atomic replacement.

The inventory is the same `.netmiko.yml` netmiko-mcp uses (written by install.sh), so devices and credentials live
in one place. Replacement goes through an EOS configuration session: `rollback clean-config` empties the candidate,
the rendered configuration is pasted, `commit` applies it atomically, then `write memory`. Nothing here decides what
to send: the configuration always comes from Infrahub (see vlanlab/infrahub_tools.py).
"""

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


def replace_config(params: dict, config: str) -> str:
    """Replaces the whole running configuration with `config`, saves it, and checks the switch still answers."""
    commands = ["configure session infrahub-deploy", "rollback clean-config", *_config_lines(config), "commit"]
    try:
        with connect(**params) as conn:
            output = conn.send_config_set(commands, exit_config_mode=False, cmd_verify=False, read_timeout=120)
            output += "\n" + conn.save_config()
        with connect(**params) as conn:  # a fresh session proves management access survived the replacement
            hostname = conn.send_command("show hostname")
    except Exception as exc:  # Netmiko raises many types; the caller only needs one
        raise DeployError(f"{params.get('host', '?')}: {exc}") from exc
    return f"{output}\nswitch answers after commit: {hostname.strip()}"
