"""Infrahub access for the lab: rendered artifacts and the read-only repository.

Infrahub renders one `startup-config` artifact per leaf (definition `leaf_startup_config` of .infrahub.yml). These
helpers read them with the Infrahub SDK, wait for them to be ready, and tell Infrahub to re-import the Git repository
after a push (a read-only repository does not follow pushes on its own).

Connection comes from the environment, as for infrahubctl and infrahub-mcp: INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN.
"""

import os
import time

import httpx
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


def _post(url: str, headers: dict[str, str]) -> int:
    return httpx.post(url, headers=headers, timeout=30).status_code


def generate_artifacts(branch: str, definition: str = ARTIFACT_DEFINITION, client=None) -> int:
    """Asks Infrahub to (re)render the artifacts of `definition` on `branch`; returns the HTTP status (fire-and-forget).

    Infrahub 1.11 decides by itself which artifacts a branch change impacts, and for the changes of this lab (a new
    VLAN, an interface moved to it) it concluded "no applicable node changes" (spike of 2026-10-23): without this call
    the Proposed Change shows no artifact diff, and main keeps the old renderings after the merge.
    """
    c = client or globals()["client"]()
    definitions = c.filters(kind="CoreArtifactDefinition", name__value=definition)
    if not definitions:
        raise LookupError(f"no artifact definition named {definition!r} in Infrahub")
    address = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000").rstrip("/")
    return _post(f"{address}/api/artifact/generate/{definitions[0].id}?branch={branch}",
                 {"X-INFRAHUB-KEY": os.environ.get("INFRAHUB_API_TOKEN", "")})


TRIGGER_WORKFLOW = "request_artifact_definitions_generate"
GENERATE_WORKFLOW = "artifact-generate"
TERMINAL_STATES = ("COMPLETED", "FAILED", "CANCELLED", "CRASHED")
TASKS_QUERY = """query Tasks($branch: String!, $limit: Int!) {
  InfrahubTask(branch: $branch, limit: $limit) { edges { node { title state created_at workflow } } } }"""


def _tasks(c, branch: str, limit: int = 40) -> list[dict]:
    data = c.execute_graphql(query=TASKS_QUERY, variables={"branch": branch, "limit": limit})
    return [edge["node"] for edge in data["InfrahubTask"]["edges"]]


def _checksum(c, device: str, branch: str) -> str | None:
    for artifact in c.filters(kind="CoreArtifact", branch=branch, definition__name__value=ARTIFACT_DEFINITION, include=["object"]):
        if _target_label(artifact) == device:
            return getattr(getattr(artifact, "checksum", None), "value", None)
    return None


def render_artifacts(devices: list[str], branch: str = "main", timeout: int = 60, client=None) -> dict[str, bool]:
    """Asks Infrahub to re-render the startup-configs on `branch` and waits for it; returns {device: content changed}.

    The POST only queues the work (plugin rule: never trust its 200). Completion is read from Infrahub's task log:
    one trigger task plus one generation task per device, all created after the request and all in a terminal state.
    """
    c = client or globals()["client"]()
    before = {d: _checksum(c, d, branch) for d in devices}
    watermark = max((t["created_at"] for t in _tasks(c, branch)), default="")
    generate_artifacts(branch, client=c)
    deadline = time.monotonic() + timeout
    while True:
        new = [t for t in _tasks(c, branch) if t["created_at"] > watermark and t["workflow"] in (TRIGGER_WORKFLOW, GENERATE_WORKFLOW)]
        failed = [t for t in new if t["state"] in TERMINAL_STATES and t["state"] != "COMPLETED"]
        if failed:
            raise RuntimeError(f"Infrahub task failed while rendering: {failed[0]['title']} ({failed[0]['state']})")
        generations = [t for t in new if t["workflow"] == GENERATE_WORKFLOW]
        trigger_done = any(t["workflow"] == TRIGGER_WORKFLOW and t["state"] == "COMPLETED" for t in new)
        if trigger_done and len(generations) >= len(devices) and all(t["state"] == "COMPLETED" for t in generations):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Infrahub did not finish rendering on {branch} within {timeout}s "
                               f"({len(generations)} generation task(s) seen for {len(devices)} device(s))")
        time.sleep(1)
    return {d: _checksum(c, d, branch) != before[d] for d in devices}


def repository_status(name: str = REPOSITORY_NAME, client=None) -> str | None:
    """sync_status of the read-only repository (in-sync, syncing, error-import, ...), or None when it is not registered."""
    c = client or globals()["client"]()
    repos = c.filters(kind="CoreReadOnlyRepository", name__value=name)
    return repos[0].sync_status.value if repos else None


def wait_artifacts(devices: list[str], timeout: int = 600, client=None, previous: dict[str, str] | None = None) -> dict[str, str]:
    """Polls until every device has a ready artifact; returns {device: content}.

    Fails fast with RuntimeError when the repository import failed (sync_status error-import: nothing will ever be
    rendered, typically a ref without .infrahub.yml); the TimeoutError names the missing devices and the sync_status.
    With `previous` ({device: content seen before}), an artifact still equal to its previous content does not count:
    right after a merge, Infrahub's artifact stays Ready with the old body until the worker re-renders it.
    """
    c = client or globals()["client"]()
    deadline = time.monotonic() + timeout
    contents: dict[str, str] = {}
    while True:
        for device in devices:
            if device not in contents:
                try:
                    content = fetch_artifact(device, client=c)
                except ArtifactNotReady:
                    continue
                if previous is not None and previous.get(device) is not None and _same(content, previous[device]):
                    continue
                contents[device] = content
        if len(contents) == len(devices):
            return contents
        status = repository_status(client=c)
        if status == "error-import":
            raise RuntimeError(f"repository {REPOSITORY_NAME!r} failed to import (sync_status error-import): does the ref "
                               f"of INFRAHUB_REPO_REF carry .infrahub.yml? Details: docker compose -p vlan-lab logs task-worker")
        if time.monotonic() >= deadline:
            missing = [d for d in devices if d not in contents]
            raise TimeoutError(f"no ready artifact for {', '.join(missing)} after {timeout}s "
                               f"(repository sync_status: {status or 'not registered'})")
        time.sleep(POLL_SECONDS)


def _same(a: str, b: str) -> bool:
    return a.rstrip("\n") == b.rstrip("\n")


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
