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
