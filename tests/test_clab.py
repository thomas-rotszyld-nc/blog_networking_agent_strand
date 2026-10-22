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


def test_topology_has_three_data_ports_per_leaf_and_an_ipv4_only_mgmt_network():
    topo = yaml.safe_load((ROOT / "clab/vlan-lab.clab.yml").read_text())
    endpoints = sorted(e for link in topo["topology"]["links"] for e in link["endpoints"])
    assert endpoints == sorted(f"{leaf}:eth{n}" for leaf in ("leaf1", "leaf2") for n in (1, 2, 3))
    assert topo["mgmt"] == {"network": "vlan-lab", "ipv4-subnet": "172.20.20.0/24"}
