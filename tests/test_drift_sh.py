import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_drift_sh_encodes_the_drift():
    s = (ROOT / "drift.sh").read_text()
    assert subprocess.run(["sh", "-n", str(ROOT / "drift.sh")]).returncode == 0
    assert "clab-vlan-lab-" in s and 'cli leaf2 "configure' in s and "name VOIP" in s and "vlan 99" in s and "name LEGACY" in s
    assert "--reset" in s and "--reconfigure" in s and "scripts/wait_leafs.py" in s
    assert s.index("scripts/wait_artifacts.py") < s.index("containerlab deploy")  # fresh renderings before the redeploy
