"""Starts infrahub-mcp over stdio with one session branch for the whole process.

Workaround for opsmill/infrahub-mcp#187 (unreleased when this was written): infrahub-mcp 1.2.0 keys its session branch
on the MCP session object, which the mcp 2.x SDK recreates for every request. Each write then lands on a fresh branch
and propose_changes fails with "No session branch exists yet". Over stdio there is exactly one client per process, so
one key for the process is the right scope (the upstream fix uses the same "process" key when there is no HTTP session).
Launched by .mcp.json: `uvx --from infrahub-mcp==1.2.0 python scripts/infrahub_mcp_stdio.py`.
Remove this file and launch `uvx infrahub-mcp==<fixed version>` once the fix is released.
"""


class _ProcessSession:
    """The one key infrahub-mcp stores its session branch under (WeakKeyDictionary: must accept weak references)."""


_SESSION = _ProcessSession()


def patch(utils) -> None:
    """Makes every request of this process look like the same MCP session to infrahub-mcp."""
    utils._session_obj = lambda ctx: _SESSION


if __name__ == "__main__":
    import infrahub_mcp
    import infrahub_mcp.utils

    patch(infrahub_mcp.utils)
    infrahub_mcp.main()
