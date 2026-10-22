import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_topology_uses_generated_startup_configs():
    topo = yaml.safe_load((ROOT / "clab/vlan-lab.clab.yml").read_text())
    assert topo["name"] == "vlan-lab"
    assert topo["topology"]["kinds"]["arista_ceos"]["image"] == "ceos:lab"
    nodes = topo["topology"]["nodes"]
    assert nodes["leaf1"] == {"kind": "arista_ceos", "mgmt-ipv4": "172.20.20.11", "startup-config": "generated/leaf1.cfg"}
    assert nodes["leaf2"] == {"kind": "arista_ceos", "mgmt-ipv4": "172.20.20.12", "startup-config": "generated/leaf2.cfg"}
