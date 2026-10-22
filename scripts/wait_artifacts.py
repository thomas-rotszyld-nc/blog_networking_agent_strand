"""Waits for the startup-config artifacts of the given devices and writes them as <out>/<device>.cfg.

  uv run python scripts/wait_artifacts.py leaf1 leaf2 --out clab/generated --timeout 600
  uv run python scripts/wait_artifacts.py leaf1 leaf2 --until-changed   # after a merge: wait for the re-rendering
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from vlanlab.infrahub_api import wait_artifacts  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("devices", nargs="+")
    parser.add_argument("--out", default="clab/generated")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--until-changed", action="store_true",
                        help="wait until each rendering differs from the file already in --out (after a merge)")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    previous = None
    if args.until_changed:
        previous = {d: (out / f"{d}.cfg").read_text() for d in args.devices if (out / f"{d}.cfg").exists()}
    for device, content in wait_artifacts(args.devices, timeout=args.timeout, previous=previous).items():
        path = out / f"{device}.cfg"
        path.write_text(content if content.endswith("\n") else content + "\n")
        print(f"  {path} ({len(content.splitlines())} lines)")


if __name__ == "__main__":
    main()
