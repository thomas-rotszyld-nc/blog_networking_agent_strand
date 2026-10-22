"""Waits until every leaf of the inventory answers `show running-config` over SSH (cEOS takes a minute or two to boot).

  uv run python scripts/wait_leafs.py [--timeout 300]
"""

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from vlanlab.eos import load_inventory, running_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    pending = dict(load_inventory())
    deadline = time.monotonic() + args.timeout
    while pending:
        for name, params in list(pending.items()):
            try:
                running_config({**params, "conn_timeout": 10, "banner_timeout": 20})
            except Exception:
                continue
            print(f"  {name} answers", flush=True)
            del pending[name]
        if pending and time.monotonic() >= deadline:
            sys.exit(f"still no SSH answer from {', '.join(sorted(pending))} after {args.timeout}s")
        if pending:
            time.sleep(10)


if __name__ == "__main__":
    main()
