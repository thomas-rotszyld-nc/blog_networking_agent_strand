"""The stdio wrapper around infrahub-mcp 1.2.0: the session branch must survive from one tool call to the next.

With the mcp 2.x SDK every request gets a new ServerSession object, so infrahub-mcp 1.2.0, which keys the session
branch on that object (WeakKeyDictionary), forgets its branch after each call: every write lands on a new branch and
propose_changes fails with "No session branch exists yet". Over stdio there is exactly one client, so one key for the
whole process is right (what opsmill/infrahub-mcp#187 does upstream, unreleased at the time of writing).
"""
import importlib.util
import pathlib
import types
import weakref

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_wrapper():
    spec = importlib.util.spec_from_file_location("infrahub_mcp_stdio", ROOT / "scripts" / "infrahub_mcp_stdio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # importing must not start the server
    return module


def test_the_session_key_is_the_same_object_for_every_request():
    wrapper = load_wrapper()
    utils = types.SimpleNamespace(_session_obj=lambda ctx: object())   # upstream: a new ServerSession per request
    wrapper.patch(utils)
    first, second = utils._session_obj(ctx=object()), utils._session_obj(ctx=object())
    assert first is second
    weakref.ref(first)   # infrahub-mcp keeps it in a WeakKeyDictionary: the key must accept weak references
    d = weakref.WeakKeyDictionary()
    d[first] = "agent/20261023-abcd"
    assert d.get(second) == "agent/20261023-abcd"
