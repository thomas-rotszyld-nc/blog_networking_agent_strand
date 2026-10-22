import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
PINNED = "26336e9026dff1907f2c58e81dd6ae7b5c3f763e"


def docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def test_schema_files_are_pinned_copies():
    files = sorted((ROOT / "infrahub/schema").glob("*.yml"))
    assert [f.name[3:] for f in files] == ["organization.yml", "location.yml", "dcim.yml", "ipam.yml", "location_site.yml", "vlan.yml"]
    for f in files:
        assert PINNED in f.read_text().splitlines()[1], f.name


def test_objects_match_the_scenario():
    objs = {}
    for f in sorted((ROOT / "infrahub/objects").glob("*.yml")):
        for d in docs(f):
            assert d["apiVersion"] == "infrahub.app/v1" and d["kind"] == "Object"
            objs.setdefault(d["spec"]["kind"], []).extend(d["spec"]["data"])
    assert [v["name"] for v in objs["IpamVLAN"]] == ["USERS", "VOICE", "IOT"]
    assert [v["vlan_id"] for v in objs["IpamVLAN"]] == [10, 20, 30]
    assert objs["IpamVLANGroup"][0]["scope"]["kind"] == "LocationSite"
    assert [g["name"] for g in objs["CoreStandardGroup"]] == ["leafs"]
    devices = objs["DcimDevice"]
    assert [d["name"] for d in devices] == ["leaf1", "leaf2"]
    for d in devices:
        assert d["member_of_groups"] == ["leafs"] and d["role"] == "leaf"
        names = [i["name"] for i in d["interfaces"]["data"]]
        assert names == ["Management0", "Ethernet1", "Ethernet2", "Ethernet3"]
        assert [i.get("untagged_vlan") for i in d["interfaces"]["data"][1:]] == ["USERS", "VOICE", "IOT"]
    assert sorted(ip["address"] for ip in objs["IpamIPAddress"]) == ["172.20.20.11/24", "172.20.20.12/24"]
