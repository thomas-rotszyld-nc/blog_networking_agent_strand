import pathlib

import yaml
from infrahub_sdk.schema.repository import InfrahubRepositoryConfig

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_infrahub_yml_is_valid_and_wired():
    cfg = InfrahubRepositoryConfig(**yaml.safe_load((ROOT / ".infrahub.yml").read_text()))
    assert [q.name for q in cfg.queries] == ["leaf_config"]
    t = cfg.jinja2_transforms[0]
    assert (t.name, t.query, str(t.template_path)) == ("eos_leaf", "leaf_config", "infrahub/templates/eos_leaf.j2")
    a = cfg.artifact_definitions[0]
    assert (a.name, a.artifact_name, a.content_type, a.targets, a.transformation, a.parameters) == (
        "leaf_startup_config", "startup-config", "text/plain", "leafs", "eos_leaf", {"device": "name__value"})
    assert (ROOT / cfg.queries[0].file_path).exists() and (ROOT / t.template_path).exists()
