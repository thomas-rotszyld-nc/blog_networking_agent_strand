import pytest

from vlanlab import infrahub_api as api


class Node:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Attr:
    def __init__(self, value):
        self.value = value


class FakeStore:
    blobs: dict[str, str] = {}

    def get(self, identifier):
        return self.blobs[identifier]


class FakeClient:
    def __init__(self, artifacts, blobs):
        self.artifacts, self.calls = artifacts, []
        self.object_store = FakeStore()
        FakeStore.blobs = blobs

    def filters(self, kind, **kw):
        self.calls.append((kind, kw))
        if kind == "CoreReadOnlyRepository":   # the plain fake has no repository registered
            return []
        return self.artifacts

    def execute_graphql(self, query, **kw):
        self.calls.append(("gql", query))
        return {"InfrahubReadOnlyRepositoryImportLastCommit": {"ok": True}}


def ready(device, storage):
    return Node(status=Attr("Ready"), storage_id=Attr(storage), object=Node(display_label=device))


def test_fetch_artifact_returns_body():
    c = FakeClient([ready("leaf1", "s1")], {"s1": "hostname leaf1\nend\n"})
    assert api.fetch_artifact("leaf1", client=c) == "hostname leaf1\nend\n"


def test_fetch_artifact_not_ready():
    pending = Node(status=Attr("Pending"), storage_id=Attr(None), object=Node(display_label="leaf1"))
    with pytest.raises(api.ArtifactNotReady):
        api.fetch_artifact("leaf1", client=FakeClient([pending], {}))


def test_wait_artifacts_times_out(monkeypatch):
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    with pytest.raises(TimeoutError):
        api.wait_artifacts(["leaf1"], timeout=0, client=FakeClient([], {}))


def test_wait_artifacts_returns_contents():
    c = FakeClient([ready("leaf1", "s1"), ready("leaf2", "s2")], {"s1": "hostname leaf1\n", "s2": "hostname leaf2\n"})
    assert api.wait_artifacts(["leaf1", "leaf2"], timeout=5, client=c) == {"leaf1": "hostname leaf1\n", "leaf2": "hostname leaf2\n"}


def test_reimport_runs_the_mutation(monkeypatch):
    c = FakeClient([], {})
    monkeypatch.setattr(api, "repository_id", lambda name, client=None: "repo-1")
    api.reimport_repository(client=c)
    assert any("InfrahubReadOnlyRepositoryImportLastCommit" in q and "repo-1" in q for kind, q in c.calls if kind == "gql")


def test_wait_artifacts_can_wait_for_a_change(monkeypatch):
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    same = FakeClient([ready("leaf1", "s1")], {"s1": "hostname leaf1\n"})
    with pytest.raises(TimeoutError):
        api.wait_artifacts(["leaf1"], timeout=0, client=same, previous={"leaf1": "hostname leaf1\n"})
    changed = FakeClient([ready("leaf1", "s2")], {"s2": "hostname leaf1\nvlan 40\n"})
    assert api.wait_artifacts(["leaf1"], timeout=0, client=changed, previous={"leaf1": "hostname leaf1\n"}) == {"leaf1": "hostname leaf1\nvlan 40\n"}


class RepoAwareClient(FakeClient):
    """FakeClient that also answers for the read-only repository, with the given sync_status."""

    def __init__(self, artifacts, blobs, repo_status):
        super().__init__(artifacts, blobs)
        self.repo_status = repo_status

    def filters(self, kind, **kw):
        if kind == "CoreReadOnlyRepository":
            return [Node(id="r1", sync_status=Attr(self.repo_status), ref=Attr("main"), commit=Attr("abc1234"))]
        return super().filters(kind, **kw)


def test_wait_artifacts_fails_fast_when_the_repository_import_failed():
    with pytest.raises(RuntimeError, match="error-import"):          # no 600 s wait for artifacts that will never come
        api.wait_artifacts(["leaf1"], timeout=5, client=RepoAwareClient([], {}, "error-import"))


def test_wait_artifacts_timeout_names_the_repository_status():
    with pytest.raises(TimeoutError, match="syncing"):
        api.wait_artifacts(["leaf1"], timeout=0, client=RepoAwareClient([], {}, "syncing"))


def test_generate_artifacts_posts_to_the_generate_endpoint(monkeypatch):
    # Infrahub does not re-render on a branch by itself for these changes (spike, 2026-10-23): the lab asks for it
    calls = []
    c = RepoAwareClient([], {}, "in-sync")
    c.filters = lambda kind, **kw: [Node(id="def-1")] if kind == "CoreArtifactDefinition" else []
    monkeypatch.setattr(api, "_post", lambda url, headers: calls.append((url, headers)) or 200)
    monkeypatch.setenv("INFRAHUB_ADDRESS", "http://ih:8000")
    monkeypatch.setenv("INFRAHUB_API_TOKEN", "tok")
    assert api.generate_artifacts("agent/x", client=c) == 200
    assert calls == [("http://ih:8000/api/artifact/generate/def-1?branch=agent/x", {"X-INFRAHUB-KEY": "tok"})]


class RenderClient(RepoAwareClient):
    """Fake for render_artifacts: artifacts whose checksum changes once the generation tasks have run."""

    def __init__(self):
        super().__init__([], {}, "in-sync")
        self.polls = 0

    def filters(self, kind, **kw):
        if kind == "CoreArtifactDefinition":
            return [Node(id="def-1")]
        if kind == "CoreArtifact":
            tag = "new" if self.polls >= 2 else "old"
            return [Node(status=Attr("Ready"), storage_id=Attr("s"), checksum=Attr(f"{tag}-{d}"), object=Node(display_label=d))
                    for d in ("leaf1", "leaf2")]
        return super().filters(kind, **kw)

    def execute_graphql(self, query, **kw):
        self.polls += 1
        tasks = [{"title": "older", "state": "COMPLETED", "created_at": "2026-10-23T10:00:00+00:00", "workflow": "hfid-process"}]
        if self.polls >= 2:   # after the POST: the trigger task, then one generation task per device, all finished
            tasks += [{"title": "Trigger Generation of Artifacts", "state": "COMPLETED", "created_at": "2026-10-23T11:00:01+00:00",
                       "workflow": "request_artifact_definitions_generate"}]
            tasks += [{"title": "Generate artifact startup-config", "state": "COMPLETED", "created_at": "2026-10-23T11:00:02+00:00",
                       "workflow": "artifact-generate"} for _ in range(2)]
        return {"InfrahubTask": {"edges": [{"node": t} for t in tasks]}}


def test_render_artifacts_waits_for_the_generation_tasks_and_reports_changes(monkeypatch):
    posted = []
    monkeypatch.setattr(api, "_post", lambda url, headers: posted.append(url) or 200)
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    c = RenderClient()
    assert api.render_artifacts(["leaf1", "leaf2"], branch="main", timeout=5, client=c) == {"leaf1": True, "leaf2": True}
    assert posted and "/api/artifact/generate/def-1?branch=main" in posted[0]
    assert c.polls >= 2   # the tasks were read after the POST, not assumed


def test_generate_artifacts_raises_on_an_http_error(monkeypatch):
    # review: the status was returned and ignored, so a 401/404 surfaced 60 s later as a misleading rendering timeout
    c = RepoAwareClient([], {}, "in-sync")
    c.filters = lambda kind, **kw: [Node(id="def-1")] if kind == "CoreArtifactDefinition" else []
    monkeypatch.setattr(api, "_post", lambda url, headers: 401)
    with pytest.raises(RuntimeError, match="401"):
        api.generate_artifacts("agent/x", client=c)
