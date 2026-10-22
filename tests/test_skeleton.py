import subprocess


def test_dependencies_import():
    import netmiko, strands, strands.models.anthropic, infrahub_sdk  # noqa: F401


def test_infrahubctl_is_in_the_venv():
    assert subprocess.run(["uv", "run", "infrahubctl", "version"], capture_output=True).returncode == 0
