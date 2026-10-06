"""Group hashed images into sets of exact and near duplicates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from .hashing import HashedImage
from .keeper import rank

DEFAULT_THRESHOLD = 6
MAX_THRESHOLD = 16


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class UnionFind:
    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        parent = self._parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a


class BKTree:
    """Metric tree over integers under Hamming distance."""

    def __init__(self) -> None:
        self._root: tuple[int, dict] | None = None

    def add(self, value: int) -> None:
        if self._root is None:
            self._root = (value, {})
            return
        node = self._root
        while True:
            distance = hamming(value, node[0])
            if distance == 0:
                return
            child = node[1].get(distance)
            if child is None:
                node[1][distance] = (value, {})
                return
            node = child

    def query(self, value: int, radius: int) -> list[int]:
        """Return every stored value within `radius` of `value`."""
        if self._root is None:
            return []
        found = []
        stack = [self._root]
        while stack:
            node_value, children = stack.pop()
            distance = hamming(value, node_value)
            if distance <= radius:
                found.append(node_value)
            for edge, child in children.items():
                if distance - radius <= edge <= distance + radius:
                    stack.append(child)
        return found


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    images: tuple[HashedImage, ...]  # best keeper first
    kind: Literal["exact", "similar"]
    max_distance: int

    @property
    def keeper(self) -> HashedImage:
        return self.images[0]

    @property
    def reclaimable(self) -> int:
        """Bytes freed by removing everything except the suggested keeper."""
        return sum(image.file.size for image in self.images[1:])


def _max_distance(images: Sequence[HashedImage]) -> int:
    hashes = list({image.phash for image in images})
    if len(hashes) > 200:  # avoid a quadratic blow-up on huge groups
        return max(hamming(hashes[0], other) for other in hashes)
    return max((hamming(a, b) for a, b in combinations(hashes, 2)), default=0)


def build_groups(images: Sequence[HashedImage], threshold: int = DEFAULT_THRESHOLD) -> list[DuplicateGroup]:
    """Group images whose bytes match or whose pHashes are within `threshold` bits.

    Matches are transitive, so a group can chain A~B~C even when A and C are
    further apart than the threshold. Largest reclaimable space comes first.
    """
    links = UnionFind(len(images))
    by_sha: dict[str, int] = {}
    by_phash: dict[int, int] = {}
    for index, image in enumerate(images):
        if image.sha256:
            links.union(by_sha.setdefault(image.sha256, index), index)
        links.union(by_phash.setdefault(image.phash, index), index)

    if threshold > 0:
        tree = BKTree()
        for value, index in by_phash.items():
            for neighbour in tree.query(value, threshold):
                links.union(by_phash[neighbour], index)
            tree.add(value)

    members: dict[int, list[HashedImage]] = {}
    for index, image in enumerate(images):
        members.setdefault(links.find(index), []).append(image)

    groups = []
    for group in members.values():
        if len(group) < 2:
            continue
        digests = {image.sha256 for image in group}
        exact = len(digests) == 1 and None not in digests
        groups.append(DuplicateGroup(tuple(rank(group)), "exact" if exact else "similar", _max_distance(group)))
    groups.sort(key=lambda group: (-group.reclaimable, str(group.keeper.file.path)))
    return groups
