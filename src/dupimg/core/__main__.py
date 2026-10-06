"""Debug printout of duplicate groups: python -m dupimg.core <folder>... [--threshold N]"""

from __future__ import annotations

import argparse

from ..util import human_size, plural
from .cache import HashCache
from .grouping import DEFAULT_THRESHOLD, build_groups
from .pipeline import run_scan


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m dupimg.core", description=__doc__)
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    cache = None if args.no_cache else HashCache()
    try:
        result = run_scan(args.folders, cache)
    finally:
        if cache:
            cache.close()

    groups = build_groups(result.images, args.threshold)
    for number, group in enumerate(groups, 1):
        print(f"\nGroup {number}: {group.kind}, distance <= {group.max_distance}, {human_size(group.reclaimable)} reclaimable")
        for index, image in enumerate(group.images):
            mark = "keep  " if index == 0 else "remove"
            print(f"  {mark} {image.width}x{image.height} {human_size(image.file.size):>9}  {image.file.path}")
    total = sum(group.reclaimable for group in groups)
    print(f"\n{len(result.images)} images, {plural(len(groups), 'group')}, {human_size(total)} reclaimable, {len(result.skipped)} skipped")
    for path, reason in result.skipped:
        print(f"  skipped {path}: {reason}")


if __name__ == "__main__":
    main()
