from pathlib import Path

import pytest

from dupimg.core import actions, pipeline
from dupimg.core.cache import HashCache
from dupimg.core.grouping import BKTree, build_groups, hamming
from dupimg.core.hashing import HashedImage, hash_file, perceptual_hash
from dupimg.core.keeper import rank
from dupimg.core.pipeline import ScanCancelled, run_scan
from dupimg.core.scanner import ImageFile, scan


def names(images) -> set[str]:
    return {image.file.path.name for image in images}


def fake(name: str, width=100, height=100, size=1000, mtime=0, sha=None, phash=0) -> HashedImage:
    return HashedImage(ImageFile(Path(name), size, mtime), sha, phash, width, height)


# --- scanner ---------------------------------------------------------------


def test_scan_finds_images_recursively_and_ignores_other_files(library):
    found = {file.path.name for file in scan([library["root"]])}
    assert found == {"base.png", "copy.png", "resized.png", "recompressed.jpg", "rotated.jpg", "other.png", "broken.jpg"}


def test_scan_overlapping_folders_yields_each_file_once(library):
    files = list(scan([library["root"], library["root"] / "sub"]))
    assert len(files) == len({file.path for file in files}) == 7


def test_scan_missing_folder_is_reported_not_raised(tmp_path):
    skipped = []
    assert list(scan([tmp_path / "nope"], skipped)) == []
    assert len(skipped) == 1


# --- hashing ---------------------------------------------------------------


def test_perceptual_hash_survives_resize_recompress_and_exif_rotation(library):
    base, width, height = perceptual_hash(library["base"])
    assert (width, height) == (640, 480)
    for variant in ("resized", "jpeg", "rotated"):
        assert hamming(base, perceptual_hash(library[variant])[0]) <= 6, variant
    assert hamming(base, perceptual_hash(library["other"])[0]) > 16


def test_exif_rotated_image_reports_upright_dimensions(library):
    assert perceptual_hash(library["rotated"])[1:] == (640, 480)


def test_hash_file_reports_errors_instead_of_raising(library):
    *_, error = hash_file(str(library["broken"]), need_sha=True)
    assert error


# --- grouping --------------------------------------------------------------


def test_bktree_query_matches_brute_force():
    import random

    rng = random.Random(0)
    values = [rng.getrandbits(64) for _ in range(300)]
    values += [value ^ (1 << rng.randrange(64)) for value in values[:100]]
    tree = BKTree()
    for value in values:
        tree.add(value)
    for probe in values[:50]:
        expected = {value for value in values if hamming(probe, value) <= 4}
        assert set(tree.query(probe, 4)) == expected


def test_groups_from_real_files(library):
    result = run_scan([library["root"]])
    assert [path.name for path, _reason in result.skipped] == ["broken.jpg"]

    groups = build_groups(result.images)
    assert len(groups) == 1
    assert names(groups[0].images) == {"base.png", "copy.png", "resized.png", "recompressed.jpg", "rotated.jpg"}
    assert groups[0].kind == "similar"


def test_byte_identical_files_form_an_exact_group(library):
    result = run_scan([library["root"] / "sub", library["base"].parent])
    pair = [image for image in result.images if image.file.path.name in ("base.png", "copy.png")]
    groups = build_groups(pair, threshold=0)
    assert len(groups) == 1 and groups[0].kind == "exact" and groups[0].max_distance == 0


def test_threshold_controls_grouping():
    images = [fake("a", phash=0b0), fake("b", phash=0b111), fake("c", phash=0xFFFF_0000_0000)]
    assert build_groups(images, threshold=2) == []
    assert names(build_groups(images, threshold=3)[0].images) == {"a", "b"}


def test_groups_sorted_by_reclaimable_space():
    images = [
        fake("small1", size=10, phash=1),
        fake("small2", size=10, phash=1),
        fake("big1", size=5000, phash=0xFF00),
        fake("big2", size=5000, phash=0xFF00),
    ]
    groups = build_groups(images)
    assert [group.reclaimable for group in groups] == [5000, 10]


# --- keeper ----------------------------------------------------------------


def test_keeper_prefers_resolution_then_lossless_then_size_then_age():
    assert rank([fake("lo.png", 10, 10), fake("hi.jpg", 20, 20)])[0].file.path.name == "hi.jpg"
    assert rank([fake("a.jpg"), fake("a.png")])[0].file.path.name == "a.png"
    assert rank([fake("a.jpg", size=1), fake("b.jpg", size=2)])[0].file.path.name == "b.jpg"
    assert rank([fake("new.jpg", mtime=9), fake("old.jpg", mtime=1)])[0].file.path.name == "old.jpg"


def test_keeper_of_real_group_is_a_full_resolution_png(library):
    group = build_groups(run_scan([library["root"]]).images)[0]
    assert group.keeper.file.path.name in ("base.png", "copy.png")
    assert group.keeper.pixels == 640 * 480


# --- cache and pipeline ----------------------------------------------------


def test_second_scan_uses_cache_and_rehashes_only_changed_files(library, tmp_path, monkeypatch):
    calls = []
    real_hash_file = pipeline.hash_file
    monkeypatch.setattr(pipeline, "hash_file", lambda path, need_sha: calls.append(path) or real_hash_file(path, need_sha))

    with HashCache(tmp_path / "cache.db") as cache:
        first = run_scan([library["root"]], cache)
    assert len(calls) == 7

    calls.clear()
    with HashCache(tmp_path / "cache.db") as cache:
        second = run_scan([library["root"]], cache)
    assert [Path(path).name for path in calls] == ["broken.jpg"]  # failures are not cached
    assert sorted(second.images, key=str) == sorted(first.images, key=str)

    calls.clear()
    library["other"].write_bytes(library["jpeg"].read_bytes())
    with HashCache(tmp_path / "cache.db") as cache:
        run_scan([library["root"]], cache)
    # "other" changed, and "recompressed" now shares its size so needs a content hash.
    assert {Path(path).name for path in calls} == {"broken.jpg", "other.png", "recompressed.jpg"}


def test_worker_pool_gives_same_result_as_inline(library, monkeypatch):
    inline = run_scan([library["root"]])
    monkeypatch.setattr(pipeline, "_INLINE_LIMIT", 0)
    pooled = run_scan([library["root"]], workers=2)
    assert sorted(pooled.images, key=str) == sorted(inline.images, key=str)


def test_scan_reports_progress_and_can_be_cancelled(library):
    events = []
    run_scan([library["root"]], progress=lambda *event: events.append(event))
    assert events[-1] == ("hashing", 7, 7)

    with pytest.raises(ScanCancelled):
        run_scan([library["root"]], cancel=lambda: True)


# --- actions ---------------------------------------------------------------


@pytest.fixture
def trashed(monkeypatch):
    sent = []
    monkeypatch.setattr(actions, "send2trash", sent.append)
    return sent


def test_remove_sends_only_selected_files_to_recycle_bin(library, trashed):
    group = build_groups(run_scan([library["root"]]).images)[0]
    remove = {library["resized"], library["jpeg"]}
    result = actions.remove_from_groups([group], remove)
    assert set(result.trashed) == remove and not result.failed
    assert set(trashed) == {str(path) for path in remove}


def test_remove_refuses_to_take_every_file_in_a_group(library, trashed):
    group = build_groups(run_scan([library["root"]]).images)[0]
    everything = {image.file.path for image in group.images}
    result = actions.remove_from_groups([group], everything)
    assert not trashed and not result.trashed
    assert {path for path, _reason in result.failed} == everything


def test_remove_refuses_when_the_kept_files_are_gone(library, trashed):
    pair = [image for image in run_scan([library["root"]]).images if image.file.path.name in ("base.png", "copy.png")]
    group = build_groups(pair)[0]
    library["base"].unlink()
    result = actions.remove_from_groups([group], {library["copy"]})
    assert not trashed and len(result.failed) == 1


def test_remove_skips_files_changed_or_deleted_since_the_scan(library, trashed):
    group = build_groups(run_scan([library["root"]]).images)[0]
    library["resized"].write_bytes(b"changed")
    library["jpeg"].unlink()
    result = actions.remove_from_groups([group], {library["resized"], library["jpeg"], library["rotated"]})
    assert result.trashed == [library["rotated"]]
    assert {path.name: reason for path, reason in result.failed} == {
        "resized.png": "file changed since the scan",
        "recompressed.jpg": "file no longer exists",
    }
