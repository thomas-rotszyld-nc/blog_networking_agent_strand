"""Infrahub access for the lab: rendered artifacts and the read-only repository.

Infrahub renders one `startup-config` artifact per leaf (definition `leaf_startup_config` of .infrahub.yml). These
helpers read them with the Infrahub SDK, wait for them to be ready, and tell Infrahub to re-import the Git repository
after a push (a read-only repository does not follow pushes on its own).

Connection comes from the environment, as for infrahubctl and infrahub-mcp: INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN.
"""

import os
import time

from infrahub_sdk import Config, InfrahubClientSync

ARTIFACT_DEFINITION = "leaf_startup_config"
REPOSITORY_NAME = "blog-lab"
POLL_SECONDS = 5


class ArtifactNotReady(Exception):
    """No artifact with a rendered body exists yet for this device."""


def client() -> InfrahubClientSync:
    """A sync SDK client built from INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN."""
    return InfrahubClientSync(config=Config(address=os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000"),
                                            api_token=os.environ.get("INFRAHUB_API_TOKEN")))


def _target_label(artifact) -> str | None:
    """Display label of the node an artifact is rendered for (the device name)."""
    related = getattr(artifact, "object", None)
    label = getattr(related, "display_label", None)
    if label is None and getattr(related, "peer", None) is not None:
        label = getattr(related.peer, "display_label", None)
    return label


def fetch_artifact(device: str, name: str = "startup-config", branch: str = "main", client=None) -> str:
    """The rendered startup-config of `device` on `branch`, or ArtifactNotReady.

    Infrahub creates the CoreArtifact node before its body exists: only an artifact with status Ready and a storage_id
    counts (plugin rule: never trust the node count alone).
    """
    c = client or globals()["client"]()
    artifacts = c.filters(kind="CoreArtifact", branch=branch, definition__name__value=ARTIFACT_DEFINITION, include=["object"])
    for artifact in artifacts:
        if _target_label(artifact) != device:
            continue
        if artifact.status.value != "Ready" or not artifact.storage_id.value:
            continue
        return c.object_store.get(artifact.storage_id.value)
    raise ArtifactNotReady(device)


def wait_artifacts(devices: list[str], timeout: int = 600, client=None) -> dict[str, str]:
    """Polls until every device has a ready artifact; returns {device: content}. TimeoutError names the missing ones."""
    c = client or globals()["client"]()
    deadline = time.monotonic() + timeout
    contents: dict[str, str] = {}
    while True:
        for device in devices:
            if device not in contents:
                try:
                    contents[device] = fetch_artifact(device, client=c)
                except ArtifactNotReady:
                    pass
        if len(contents) == len(devices):
            return contents
        if time.monotonic() >= deadline:
            missing = [d for d in devices if d not in contents]
            raise TimeoutError(f"no ready artifact for {', '.join(missing)} after {timeout}s")
        time.sleep(POLL_SECONDS)


def repository_id(name: str = REPOSITORY_NAME, client=None) -> str:
    """Id of the read-only repository registered under `name`."""
    c = client or globals()["client"]()
    repos = c.filters(kind="CoreReadOnlyRepository", name__value=name)
    if not repos:
        raise LookupError(f"no read-only repository named {name!r} in Infrahub")
    return repos[0].id


def reimport_repository(name: str = REPOSITORY_NAME, client=None) -> None:
    """Makes the read-only repository import the last commit of its ref (it never follows pushes by itself)."""
    c = client or globals()["client"]()
    repo_id = repository_id(name, client=c)
    mutation = 'mutation { InfrahubReadOnlyRepositoryImportLastCommit(data: { id: "%s" }) { ok } }' % repo_id
    result = c.execute_graphql(query=mutation)
    if not result.get("InfrahubReadOnlyRepositoryImportLastCommit", {}).get("ok"):
        raise RuntimeError(f"re-import of repository {name!r} was not accepted: {result}")
