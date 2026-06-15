"""Local import: process Snapchat bulk-export ZIPs (inline media) instead of downloading.

Newer Snapchat exports ("Export your Memories" selected) bundle the actual media
inside the export ZIPs (memories/<UTC-date>_<UUID>-main.<ext> plus optional
memories/<...>-overlay.png) and ship a memories_history.json whose
"Media Download Url" / "Download Link" fields are EMPTY. Nothing can be
downloaded; instead, this module maps each JSON entry to its inline file and
runs the same overlay-merge + metadata pipeline used for downloads.

Mapping key: the ZIP member's DOS timestamp is the entry's UTC capture time at
2-second resolution (odd seconds truncate down). (media type, UTC floored to an
even second) matches every file to its JSON entry; simultaneous bursts inside
the same 2-second window are assigned in chronological order.

JSON entries with no media file are classified into missing_media.csv:
most are duplicate ledger rows whose twin entry (same second/type) HAS the file.
"""

import asyncio
import csv
import os
import re
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tqdm.asyncio import tqdm

from . import config
from .config import OverlayMode, OverlayNaming
from .memory import Memory, MediaType
from .stats import Stats
from .overlay import merge_image_overlay, merge_video_overlay, _unwrap_overlay_data
from .metadata import apply_metadata_and_timestamps
from .download import _filter_memories_to_download

MEMBER_RE = re.compile(
    r"^memories/(\d{4}-\d{2}-\d{2})_([0-9A-Fa-f-]{36})-(main|overlay)\.([A-Za-z0-9]+)$"
)
IMAGE_EXTS = {"jpg", "jpeg", "png", "heic", "webp"}
VIDEO_EXTS = {"mp4", "mov"}

# A same-type file within this window is hinted as a possible duplicate ledger row
DUP_TWIN_MAX_S = 2

# Scenarios --test tries to export one or two of (kept in sync with select_test_set).
_TEST_SCENARIOS = [
    "photo + GPS",
    "photo, no GPS",
    "video + GPS",
    "video, no GPS",
    "media with merged caption overlay",
    "media with SCOF-wrapped overlay",
    "segment of a stitched/duplicated memory",
]

# Warnings and informational notes printed during the run are collected and
# re-printed after the final summary -- progress output scrolls them away
# otherwise.
_run_messages: list[str] = []


def _warn(message: str) -> None:
    _run_messages.append(message)
    print(message)


def _info(message: str) -> None:
    _run_messages.append(message)
    print(message)


class ExportFile:
    """One -main media member inside an export ZIP (overlay tracked separately)."""

    __slots__ = ("zip_path", "member", "base", "media_type", "mtime", "size")

    def __init__(self, zip_path: Path, member: str, base: str, media_type: str,
                 mtime: datetime, size: int):
        self.zip_path = zip_path
        self.member = member
        self.base = base          # "<UTC-date>_<UUID>"
        self.media_type = media_type  # "image" | "video"
        self.mtime = mtime        # naive UTC, even seconds (DOS resolution)
        self.size = size          # uncompressed bytes


def _floor2(dt: datetime) -> datetime:
    """Floor to even second (DOS timestamp resolution).

    ZIP members store mtimes as DOS timestamps, whose seconds field holds
    seconds/2 -- only even seconds are representable, so odd-second capture
    times truncate down by one second. Flooring BOTH sides to even seconds
    makes the match an exact key equality, not a range search.

    Empirically validated on a real multi-thousand-file export: treating member
    mtimes as UTC, every file fell within 0-1s of a JSON entry (exactly 0s for
    even-second captures, 1s for odd-second truncations) and none beyond --
    a perfect two-bucket split with an empty tail, i.e. quantization, not noise.
    """
    return dt.replace(second=dt.second // 2 * 2, microsecond=0)


def _memory_utc(memory: Memory) -> datetime:
    """Entry capture time as naive UTC (memory.date may have been localized)."""
    return memory.date.astimezone(timezone.utc).replace(tzinfo=None)


def index_zips(zips_dir: Path) -> tuple[list[ExportFile], dict[str, tuple[Path, str, datetime]], list[tuple[Path, str]]]:
    """Index all export ZIPs' central directories (no media decompressed).

    Returns (main files, overlay members keyed by base name, unknown-extension
    -main members as (zip_path, member) for raw rescue).
    """
    mains: dict[str, ExportFile] = {}
    overlays: dict[str, tuple[Path, str, datetime]] = {}
    unknown: list[tuple[Path, str]] = []
    zip_paths = sorted(zips_dir.glob("*.zip"))
    if not zip_paths:
        raise FileNotFoundError(f"No .zip files found in {zips_dir}")

    dup_mains = dup_overlays = dup_size_mismatch = 0
    for zip_path in zip_paths:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                m = MEMBER_RE.match(info.filename)
                if not m:
                    continue
                date_str, uuid, kind, ext = m.group(1), m.group(2), m.group(3), m.group(4).lower()
                base = f"{date_str}_{uuid}"
                if kind == "overlay":
                    if base in overlays:
                        dup_overlays += 1
                    else:
                        overlays[base] = (zip_path, info.filename, datetime(*info.date_time))
                    continue
                if base in mains:
                    # Same basename in more than one ZIP: keep the first, but never
                    # silently -- differing sizes mean the copies are NOT identical.
                    dup_mains += 1
                    if info.file_size != mains[base].size:
                        dup_size_mismatch += 1
                    continue
                if ext in IMAGE_EXTS:
                    media_type = "image"
                elif ext in VIDEO_EXTS:
                    media_type = "video"
                else:
                    # Unrecognized extension: can't infer a media type to tag it, but
                    # never drop media silently -- record it so its raw bytes can be
                    # rescued to recovered/ and reported.
                    unknown.append((zip_path, info.filename))
                    continue
                mains[base] = ExportFile(
                    zip_path, info.filename, base, media_type,
                    datetime(*info.date_time), info.file_size,
                )

    print(f"Indexed {len(zip_paths)} ZIPs: {len(mains)} media files, {len(overlays)} overlays")
    if dup_mains or dup_overlays:
        _warn(f"WARNING: duplicate filenames across ZIPs skipped (first occurrence used): "
              f"{dup_mains} media, {dup_overlays} overlays"
              + (f" -- {dup_size_mismatch} of the media duplicates have DIFFERENT sizes, "
                 f"so the copies are not identical!" if dup_size_mismatch else "")
              + "\nIf you combined multiple exports in one folder, process each export separately.")
    return list(mains.values()), overlays, unknown


def map_memories(
    memories: list[Memory], files: list[ExportFile]
) -> tuple[list[tuple[Memory, ExportFile]], list[Memory], list[ExportFile]]:
    """Match each export file to its JSON entry via (type, UTC floored to 2s).

    Files/entries sharing one key (simultaneous bursts) are paired in
    chronological order. Returns (matched pairs, entries without file,
    files without entry).
    """
    entries_by_key: dict[tuple[str, datetime], list[Memory]] = defaultdict(list)
    for memory in memories:
        entries_by_key[(memory.media_type.value, _floor2(_memory_utc(memory)))].append(memory)
    for group in entries_by_key.values():
        group.sort(key=_memory_utc)

    matched: list[tuple[Memory, ExportFile]] = []
    unmatched_files: list[ExportFile] = []
    claimed: set[int] = set()

    for file in sorted(files, key=lambda f: (f.mtime, f.base)):
        group = entries_by_key.get((file.media_type, file.mtime), [])
        memory = next((m for m in group if id(m) not in claimed), None)
        if memory is None:
            unmatched_files.append(file)
            continue
        claimed.add(id(memory))
        matched.append((memory, file))

    unmatched_memories = [m for m in memories if id(m) not in claimed]
    return matched, unmatched_memories, unmatched_files


def write_missing_report(
    unmatched_memories: list[Memory],
    matched: list[tuple[Memory, ExportFile]],
    output_dir: Path,
    all_memories: list[Memory],
) -> tuple[int, int, Path] | None:
    """Write missing_media.csv: every JSON entry that has NO media file in the export.

    Every row should be reviewed in the Snapchat app and saved manually if it is a
    real memory -- exports have been observed to silently omit media that still
    exists in the app.

    `duplicate_save_of` names the file of an ADJACENT ledger row with the same
    media type, identical GPS, and a (near-)identical timestamp. That signature
    matches cases where Snapchat stored the same footage under more than one
    save (observed in the wild: a memory shown in the app both as one stitched
    video and as 10-second segments -- each representation gets ledger rows,
    while the export ships media only for the segments; the stitched tile
    appears to be an app-side proxy view over the same footage rather than a
    separately exported asset). Footage for such rows is present via the named
    file. It is strong evidence, not a guarantee -- verify against the app,
    not the hint.
    """
    if not unmatched_memories:
        return

    # Double-save signature: adjacent ledger row, same type, identical GPS,
    # (near-)identical timestamp, and that row's media IS in the export.
    ledger_pos = {id(m): i for i, m in enumerate(all_memories)}
    filed_memories = {id(m): m.get_filename(occurrence=m.occurrence) for m, _ in matched}

    def _duplicate_save_of(memory: Memory) -> str:
        i = ledger_pos.get(id(memory))
        if i is None:
            return ""
        for j in (i - 1, i + 1):
            if not 0 <= j < len(all_memories):
                continue
            neighbor = all_memories[j]
            # Require real GPS on both sides: latitude/longitude are None for no-GPS
            # snaps, and None == None is True -- without this, two unrelated no-GPS
            # snaps within 2s would look like a duplicate pair and a genuinely distinct
            # missing memory could be wrongly labeled "already saved".
            if (id(neighbor) in filed_memories
                    and neighbor.media_type == memory.media_type
                    and memory.latitude is not None
                    and memory.longitude is not None
                    and neighbor.latitude == memory.latitude
                    and neighbor.longitude == memory.longitude
                    and abs((_memory_utc(neighbor) - _memory_utc(memory)).total_seconds()) <= DUP_TWIN_MAX_S):
                return filed_memories[id(neighbor)]
        return ""

    report_path = output_dir / "missing_media.csv"
    dup_saves = 0
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["utc_date", "media_type", "latitude", "longitude",
                         "action", "duplicate_save_of"])
        for memory in sorted(unmatched_memories, key=_memory_utc):
            dt = _memory_utc(memory)
            twin = _duplicate_save_of(memory)
            dup_saves += bool(twin)
            action = (
                "footage already in archive (see duplicate_save_of); verify once in the app"
                if twin else
                "CHECK IN APP at this time; if the memory exists there, save it manually -- the export omitted it"
            )
            writer.writerow([
                dt.strftime("%Y-%m-%d %H:%M:%S"),
                memory.media_type.value,
                memory.latitude if memory.latitude is not None else "",
                memory.longitude if memory.longitude is not None else "",
                action,
                twin,
            ])
    _warn(
        f"WARNING: {len(unmatched_memories)} JSON entries have NO media file in this export\n"
        f"  -> {report_path}\n"
        f"Snapchat exports can silently omit media, for unknown reasons, that still exists in the app.\n"
        f"Review every row in that CSV against the Snapchat app, and manually save anything that\n"
        f"really exists there, before closing your account.\n"
        f"{dup_saves} of these rows are probably NOT lost media: Snapchat sometimes lists the same\n"
        f"snap twice, and the duplicate row has no file of its own. For those rows the\n"
        f"duplicate_save_of column points to the already-saved file with the same footage.\n"
        f"Spot-check a few in the app instead of trusting this blindly."
    )
    return len(unmatched_memories), dup_saves, report_path


def _save_orphan_overlays(
    overlays: dict[str, tuple[Path, str, datetime]],
    files: list[ExportFile],
    output_dir: Path,
) -> int:
    """Save caption overlays whose parent media is absent from the export.

    For a memory whose media Snapchat omitted, the caption overlay can be the
    only surviving trace. Write it as <utc-timestamp>_overlay.png so it is not
    silently lost with its parent."""
    have = {f.base for f in files}
    orphans = sorted((base, ref) for base, ref in overlays.items() if base not in have)
    if not orphans:
        return 0
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for _base, (zip_path, member, mtime) in orphans:
        # Saving a keepsake overlay must never abort the run: a single corrupt
        # overlay should be skipped and reported, not block importing the actual
        # media (this runs before the media gather).
        try:
            with zipfile.ZipFile(zip_path) as zf:
                data = _unwrap_overlay_data(zf.read(member))
            out = output_dir / f"{mtime.strftime('%Y-%m-%d_%H-%M-%S')}_overlay.png"
            version = 1
            while out.exists() and out.read_bytes() != data:
                out = output_dir / f"{mtime.strftime('%Y-%m-%d_%H-%M-%S')}_v{version}_overlay.png"
                version += 1
            out.write_bytes(data)
            ts = mtime.replace(tzinfo=timezone.utc).timestamp()
            os.utime(out, (ts, ts))
            saved.append(out.name)
        except Exception as e:
            _warn(f"WARNING: could not save orphan caption overlay {member}: {e}")
    if saved:
        _info(f"NOTE: {len(saved)} caption overlay(s) have no parent media in this export --\n"
              f"their photo/video is missing. Saved the caption layer(s) as keepsakes:\n"
              f"  " + ", ".join(saved))
    return len(saved)


def _overlay_is_scof(overlays: dict, base: str) -> bool:
    """True if this base's overlay is wrapped in Snapchat's SCOF container."""
    ref = overlays.get(base)
    if not ref:
        return False
    zip_path, member = ref[0], ref[1]
    with zipfile.ZipFile(zip_path) as zf:
        head = zf.read(member)[:8]
    return head[4:8] == b"SCOF"


def _scenario_slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def select_test_set(
    memories: list[Memory],
    matched: list[tuple[Memory, ExportFile]],
    unmatched_memories: list[Memory],
    overlays: dict,
    per_scenario: int = 2,
) -> list[tuple[str, Memory, ExportFile]]:
    """Pick up to `per_scenario` representatives of each distinct scenario, so a tiny
    export exercises every metadata path end-to-end (verify in your photo app).
    Two per scenario by default, so one odd result can be told apart from a real bug.
    Returns an ordered list of (scenario label, memory, file); every file is distinct."""
    selected: list[tuple[str, Memory, ExportFile]] = []
    used: set[int] = set()

    def take(label: str, pred) -> None:
        n = 0
        for m, f in matched:
            if n >= per_scenario:
                break
            if id(m) not in used and pred(m, f):
                selected.append((label, m, f))
                used.add(id(m))
                n += 1

    # SCOF first (needs a byte check) so it isn't starved by the plain overlay combo
    n = 0
    for m, f in matched:
        if n >= per_scenario:
            break
        if id(m) not in used and f.base in overlays and _overlay_is_scof(overlays, f.base):
            selected.append(("media with SCOF-wrapped overlay", m, f))
            used.add(id(m))
            n += 1
    take("media with merged caption overlay", lambda m, f: f.base in overlays)
    take("photo + GPS", lambda m, f: f.media_type == "image" and m.location_available)
    take("photo, no GPS", lambda m, f: f.media_type == "image" and not m.location_available)
    take("video + GPS", lambda m, f: f.media_type == "video" and m.location_available)
    take("video, no GPS", lambda m, f: f.media_type == "video" and not m.location_available)

    # segments whose duplicate (stitched) row has no file -- the dedup scenario
    filed_by_id = {id(m): (m, f) for m, f in matched}
    pos = {id(m): i for i, m in enumerate(memories)}
    n = 0
    for um in unmatched_memories:
        if n >= per_scenario:
            break
        i = pos.get(id(um))
        if i is None:
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(memories):
                nb = memories[j]
                if (id(nb) in filed_by_id and id(nb) not in used
                        and nb.media_type == um.media_type
                        and nb.latitude == um.latitude and nb.longitude == um.longitude
                        and abs((_memory_utc(nb) - _memory_utc(um)).total_seconds()) <= DUP_TWIN_MAX_S):
                    selected.append(("segment of a stitched/duplicated memory", *filed_by_id[id(nb)]))
                    used.add(id(nb))
                    n += 1
                    break

    return selected


def write_test_expectations(
    selection: list[tuple[str, Memory, ExportFile]], overlays: dict, output_dir: Path,
    *, unlisted: int = 0, missing_total: int = 0, missing_dup: int = 0, orphans: int = 0,
) -> None:
    """Rename each test file to a self-describing name (scenario + index) and write
    TEST_EXPECTATIONS.txt describing what each should show in a photo app, plus a
    coverage summary that names scenarios with no example in this export."""
    sep = "-" * 70
    lines = [
        "TEST EXPORT - what to expect in your photos app",
        "===============================================",
        "",
        "Each file is named  <scenario>_<n>__<timestamp>",
        "Two of every scenario, so one odd result can be told from a real bug.",
        "Upload this folder to your photos app, then check each file below.",
        "",
        "For Google Photos users, this is the expected behavior (tested 2026-06-13):",
        "  - Photo with GPS     ->  local time + map pin",
        "  - Photo without GPS  ->  shown as GMT+00:00 (honest UTC, no guessed zone)",
        "  - Video with GPS     ->  correct local time of the location + map pin (GP reads the GPS for both)",
        "  - Video without GPS  ->  no GPS means no timezone in the file; Google Photos shows the",
        "                           moment in whatever timezone it picks, so the time-of-day may look shifted",
        "  - OTHER PHOTO APPS MAY DIFFER",
        "",
        sep,
    ]
    counts: dict[str, int] = defaultdict(int)
    for label, memory, file in selection:
        counts[label] += 1
        written = memory.path_with_overlay or memory.path_without_overlay
        orig = written.name if written else memory.get_filename(occurrence=memory.occurrence)
        new_name = f"{_scenario_slug(label)}_{counts[label]}__{orig}"
        if written and written.exists():
            written.rename(written.with_name(new_name))

        utc = _memory_utc(memory)
        if memory.location_available:
            date_exp = f"{memory.date.strftime('%Y-%m-%d %H:%M:%S %z')} (local at the GPS location)"
        elif file.media_type == "image":
            date_exp = f"{utc:%Y-%m-%d %H:%M:%S} shown as GMT+00:00 (no GPS)"
        else:
            date_exp = (f"{utc:%Y-%m-%d %H:%M:%S} UTC; no GPS, so Google Photos shows it in a "
                        f"timezone it picks (time-of-day may look shifted)")
        if memory.location_available:
            loc_exp = f"map pin near {memory.latitude:.5f}, {memory.longitude:.5f}"
        else:
            loc_exp = "no location shown"
        if file.base in overlays:
            scof = " (was SCOF-wrapped; unwrapped on import)" if _overlay_is_scof(overlays, file.base) else ""
            cap_exp = f"caption/sticker should be visible{scof}"
        else:
            cap_exp = "no separate overlay (older media may still show a burned-in caption)"

        lines += [
            "",
            new_name,
            f"    scenario :  {label}",
            f"    date     :  {date_exp}",
            f"    location :  {loc_exp}",
            f"    caption  :  {cap_exp}",
            "",
            sep,
        ]

    # Coverage: name EVERY scenario, including ones with no example in this export.
    found: dict[str, int] = defaultdict(int)
    for label, _m, _f in selection:
        found[label] += 1
    lines += ["", "SCENARIO COVERAGE IN THIS EXPORT", ""]
    for sc in _TEST_SCENARIOS:
        n = found.get(sc, 0)
        lines.append(f"  {sc:<42} {(str(n) + ' exported') if n else 'none found in this export'}")
    lines += [
        "",
        "  Report-only (no media file to hand to your photo app):",
        f"  {'files in ZIPs but missing from JSON':<42} "
        + (f"{unlisted} (re-run with --import-unlisted to include them)" if unlisted else "none found"),
        f"  {'ledger rows with no media file':<42} "
        + (f"{missing_total} -> see missing_media.csv ({missing_dup} likely duplicates already saved, "
           f"{missing_total - missing_dup} to check in the app)" if missing_total else "none found"),
        f"  {'orphan caption overlays (media missing)':<42} "
        + (f"{orphans} (saved as <timestamp>_overlay.png keepsakes)" if orphans else "none found"),
        f"  {'My Eyes Only':<42} may be indexed without media included -- save from the app (see README)",
        "",
        "missing_media.csv in this folder is the real list from your full export.",
    ]
    (output_dir / "TEST_EXPECTATIONS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Test expectations -> {output_dir / 'TEST_EXPECTATIONS.txt'}")


def pick_subset(matched: list[tuple[Memory, ExportFile]], overlays: dict, n: int):
    """Curate n items spread across (media type x GPS x overlay) buckets so a
    small test exercises every risky combination."""
    buckets: dict[tuple, list] = defaultdict(list)
    for memory, file in matched:
        key = (file.media_type, memory.location_available, file.base in overlays)
        buckets[key].append((memory, file))

    # Overlay-having buckets first: they exercise the most failure modes
    ordered = sorted(buckets, key=lambda k: (not k[2], k[0], not k[1]))
    print("Subset buckets available: " + ", ".join(
        f"{k[0]}{'+gps' if k[1] else ''}{'+overlay' if k[2] else ''}: {len(buckets[k])}"
        for k in ordered
    ))
    picked, i = [], 0
    while len(picked) < n and any(i < len(buckets[k]) for k in ordered):
        for k in ordered:
            if len(picked) >= n:
                break
            if i < len(buckets[k]):
                picked.append(buckets[k][i])
        i += 1
    return picked


async def _process_one(
    memory: Memory,
    file: ExportFile,
    overlays: dict[str, tuple[Path, str, datetime]],
    semaphore: asyncio.Semaphore,
    stats: Stats,
    progress_bar,
    dest_dir: Path,
) -> None:
    """Read one memory's media from its ZIP, merge overlay, embed metadata.

    Mirrors download.py/zip_processor.py output semantics exactly:
    - overlay 'none':  raw main written to output root
    - overlay 'with':  merged version (when overlay exists) else raw main
    - overlay 'both':  merged to with_overlays/, raw main to without_overlays/

    `dest_dir` is where this memory's media is written -- the output root normally,
    or a batch_NN/ subfolder under --split. Reports and recovered/ stay at the root.
    """
    async with semaphore:
        main_data = None
        try:
            main_data = await asyncio.to_thread(_read_member, file.zip_path, file.member)
            overlay_ref = overlays.get(file.base) if config.overlay_mode != OverlayMode.NONE else None
            overlay_data = (
                await asyncio.to_thread(_read_member, overlay_ref[0], overlay_ref[1])
                if overlay_ref else None
            )

            filename = memory.get_filename(occurrence=memory.occurrence)
            is_image = memory.media_type == MediaType.IMAGE

            if config.overlay_mode == OverlayMode.BOTH and overlay_data:
                if config.overlay_naming == OverlayNaming.SEPARATE_FOLDERS:
                    merged_path = dest_dir / config.WITH_OVERLAYS_DIR / filename
                    raw_path = dest_dir / config.WITHOUT_OVERLAYS_DIR / filename
                else:
                    merged_path = dest_dir / memory.get_filename(has_overlay=True, occurrence=memory.occurrence)
                    raw_path = dest_dir / filename
                memory.path_with_overlay = merged_path
                memory.path_without_overlay = raw_path
                if is_image:
                    merge_image_overlay(merged_path, main_data, overlay_data, memory)
                    stats.total_images += 1
                    stats.images_with_overlay += 1
                else:
                    await merge_video_overlay(merged_path, main_data, overlay_data, memory)
                    stats.total_videos += 1
                    stats.videos_with_overlay += 1
                raw_path.write_bytes(main_data)
                if is_image:
                    stats.extra_images_without_overlay += 1
                else:
                    stats.extra_videos_without_overlay += 1
                if config.save_overlays_only:
                    overlay_copy = dest_dir / config.overlays_dir / memory.get_overlay_filename(occurrence=memory.occurrence)
                    overlay_copy.parent.mkdir(parents=True, exist_ok=True)
                    overlay_copy.write_bytes(overlay_data)
            elif config.overlay_mode == OverlayMode.WITH and overlay_data:
                merged_path = dest_dir / filename
                memory.path_with_overlay = merged_path
                # Fallback target: on overlay-merge failure, overlay.py saves the
                # raw main bytes to path_without_overlay so the memory is never
                # lost. Without this it would be None and the fallback would crash.
                memory.path_without_overlay = merged_path
                if is_image:
                    merge_image_overlay(merged_path, main_data, overlay_data, memory)
                    stats.total_images += 1
                    stats.images_with_overlay += 1
                else:
                    await merge_video_overlay(merged_path, main_data, overlay_data, memory)
                    stats.total_videos += 1
                    stats.videos_with_overlay += 1
            else:
                # No overlay (or 'none' mode): raw main bytes, no re-encode
                if config.overlay_mode == OverlayMode.BOTH and config.overlay_naming == OverlayNaming.SEPARATE_FOLDERS:
                    raw_path = dest_dir / config.WITHOUT_OVERLAYS_DIR / filename
                else:
                    raw_path = dest_dir / filename
                raw_path.write_bytes(main_data)
                memory.path_without_overlay = raw_path
                if is_image:
                    stats.total_images += 1
                    stats.images_without_overlay += 1
                else:
                    stats.total_videos += 1
                    stats.videos_without_overlay += 1

            await asyncio.to_thread(apply_metadata_and_timestamps, memory)
            stats.downloaded += 1
            stats.mb += len(main_data) / 1024 / 1024
        except Exception as e:
            stats.failed += 1
            print(f"\nError processing {file.member}: {e}")
            # Safety net: never lose media. If processing failed after the bytes
            # were read (e.g. an undecodable image that has an overlay), drop the
            # raw original into recovered/ -- but only if nothing already landed
            # for this memory (the overlay-merge fallback may have saved the raw
            # main already), so recovered/ holds only truly-unsaved media.
            already_saved = any(
                p is not None and p.exists()
                for p in (memory.path_with_overlay, memory.path_without_overlay)
            )
            if main_data is not None and not already_saved:
                try:
                    recovered = config.output_dir / "recovered" / Path(file.member).name
                    recovered.parent.mkdir(parents=True, exist_ok=True)
                    if not recovered.exists():
                        recovered.write_bytes(main_data)
                        print(f"  saved raw original to {recovered}")
                except Exception as rescue_error:
                    print(f"  WARNING: could not save raw original for {file.member}: {rescue_error}")
        finally:
            progress_bar.update(1)


def _read_member(zip_path: Path, member: str) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(member)


def _write_unmatched_report(unmatched_files: list[ExportFile], output_dir: Path) -> Path:
    """Write unmatched_files.csv: media files present in the export but absent
    from the JSON."""
    report_path = output_dir / "unmatched_files.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["zip", "member", "utc_timestamp_from_file", "media_type"])
        for file in unmatched_files:
            writer.writerow([file.zip_path.name, file.member,
                             file.mtime.strftime("%Y-%m-%d %H:%M:%S"), file.media_type])
    return report_path


def _synthesize_memories(
    unmatched_files: list[ExportFile], taken_names: set[str]
) -> list[tuple[Memory, ExportFile]]:
    """Build Memory objects for files that have no JSON entry, so their media
    can be imported instead of dropped. The file's own ZIP timestamp (UTC)
    becomes the capture time; no GPS is available."""
    synthetic: list[tuple[Memory, ExportFile]] = []
    for file in unmatched_files:
        memory = Memory(**{
            "Date": file.mtime.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "Media Type": file.media_type,
            "Media Download Url": "",
        })
        # No suffix unless the name is taken by an existing same-second output
        occurrence = 0
        while memory.get_filename(occurrence=occurrence) in taken_names:
            occurrence += 1
        memory.occurrence = occurrence
        taken_names.add(memory.get_filename(occurrence=occurrence))
        synthetic.append((memory, file))
    return synthetic


async def import_all(memories: list[Memory]) -> None:
    """Entry point: map memories to inline export files and process them."""
    assert config.from_zips is not None, "import_all requires config.from_zips"
    _run_messages.clear()
    files, overlays, unknown_members = index_zips(config.from_zips)
    if overlays and config.overlay_mode == OverlayMode.NONE:
        _warn(f"WARNING: this export contains {len(overlays)} overlay (caption) files, but "
              f"--overlay none skips merging them.\n"
              f"Captions would be missing from the output. Use --overlay with (or both) to keep them.")
    matched, unmatched_memories, unmatched_files = map_memories(memories, files)

    print(f"Mapped {len(matched)}/{len(files)} media files to JSON entries")
    _info("NOTE: My Eyes Only snaps may be listed in the index without their media included --\n"
          "save them from the app. (See the README.)")
    if unmatched_files:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = _write_unmatched_report(unmatched_files, config.output_dir)
        if config.import_unlisted:
            taken = {m.get_filename(occurrence=m.occurrence) for m, _ in matched}
            matched = matched + _synthesize_memories(unmatched_files, taken)
            _warn(f"{len(unmatched_files)} files have no JSON entry -> {report_path}\n"
                  f"--import-unlisted: importing them with the file's own timestamp (UTC), no GPS.")
        else:
            _warn(f"WARNING: {len(unmatched_files)} of {len(files)} files are not listed in this JSON\n"
                  f"  -> {report_path}\n"
                  f"They are NOT imported. If these are real memories (and not just a partial JSON),\n"
                  f"re-run with --import-unlisted to import them using each file's own timestamp.")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    if config.overlay_mode == OverlayMode.BOTH and config.overlay_naming == OverlayNaming.SEPARATE_FOLDERS:
        (config.output_dir / config.WITH_OVERLAYS_DIR).mkdir(parents=True, exist_ok=True)
        (config.output_dir / config.WITHOUT_OVERLAYS_DIR).mkdir(parents=True, exist_ok=True)

    # Unknown-extension media can't be tagged (no inferable type), but must not be
    # lost -- copy the raw bytes into recovered/ and report them.
    if unknown_members:
        recovered_dir = config.output_dir / "recovered"
        recovered_dir.mkdir(parents=True, exist_ok=True)
        for zip_path, member in unknown_members:
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    data = zf.read(member)
                out = recovered_dir / Path(member).name
                if not out.exists():
                    out.write_bytes(data)
            except Exception as e:
                _warn(f"WARNING: could not rescue unknown-type media {member}: {e}")
        _warn(f"WARNING: {len(unknown_members)} media file(s) have an unrecognized extension and\n"
              f"could not be tagged. Their raw bytes were copied to {recovered_dir} so nothing is\n"
              f"lost -- review them manually.")

    test_selection = None
    test_coverage: dict[str, int] = {}
    # Reports reflect the FULL export, so they are written in test mode too.
    missing_report = write_missing_report(unmatched_memories, matched, config.output_dir, memories)
    orphan_count = _save_orphan_overlays(overlays, files, config.output_dir)

    if config.test:
        test_coverage = {
            "unlisted": len(unmatched_files),
            "missing_total": missing_report[0] if missing_report else 0,
            "missing_dup": missing_report[1] if missing_report else 0,
            "orphans": orphan_count,
        }
        test_selection = select_test_set(memories, matched, unmatched_memories, overlays)
        matched = [(m, f) for _, m, f in test_selection]
        scenarios = sorted({label for label, _, _ in test_selection})
        print(f"Test mode: {len(matched)} items, up to 2 each of {len(scenarios)} scenarios "
              f"({', '.join(scenarios)})")
    elif config.subset:
        matched = pick_subset(matched, overlays, config.subset)
        print(f"Subset mode: processing {len(matched)} curated items")

    stats = Stats()
    to_process = matched
    if config.skip_existing:
        keep = set(id(m) for m in _filter_memories_to_download([m for m, _ in matched], stats))
        to_process = [(m, f) for m, f in matched if id(m) in keep]
    if not to_process:
        print("All files already imported!")
        return

    # --split: deal each memory's media into numbered batch_NN/ subfolders so the
    # user can upload one folder at a time (Google Photos web stalls on huge album
    # uploads). to_process is roughly chronological, so batches are time-ordered.
    # Reports, recovered/, and orphan overlays deliberately stay in the output root.
    dest_for: dict[int, Path] = {}
    if config.split and not config.test:
        n_batches = (len(to_process) + config.split - 1) // config.split
        width = max(2, len(str(n_batches)))
        for i, (m, _f) in enumerate(to_process):
            dest_for[id(m)] = config.output_dir / f"batch_{i // config.split + 1:0{width}d}"
        for d in sorted(set(dest_for.values())):
            d.mkdir(parents=True, exist_ok=True)
            if config.overlay_mode == OverlayMode.BOTH and config.overlay_naming == OverlayNaming.SEPARATE_FOLDERS:
                (d / config.WITH_OVERLAYS_DIR).mkdir(parents=True, exist_ok=True)
                (d / config.WITHOUT_OVERLAYS_DIR).mkdir(parents=True, exist_ok=True)
        _info(f"--split {config.split}: media written into {n_batches} subfolder(s) "
              f"(batch_01 ... batch_{n_batches:0{width}d}), up to {config.split} files each. "
              f"Upload one folder at a time. Reports and any recovered/orphan files stay in the output root.")

    # Local processing is CPU/disk-bound (ffmpeg merges), not network-bound
    concurrency = min(config.max_concurrent, 8)
    semaphore = asyncio.Semaphore(concurrency)
    progress_bar = tqdm(total=len(to_process), desc="Importing", unit="file")
    start_time = time.time()

    await asyncio.gather(
        *[_process_one(m, f, overlays, semaphore, stats, progress_bar,
                       dest_for.get(id(m), config.output_dir)) for m, f in to_process]
    )

    progress_bar.close()
    stats.print_summary(time.time() - start_time)

    if test_selection is not None:
        write_test_expectations(
            test_selection, overlays, config.output_dir,
            unlisted=test_coverage["unlisted"],
            missing_total=test_coverage["missing_total"],
            missing_dup=test_coverage["missing_dup"],
            orphans=test_coverage["orphans"],
        )

    # Re-print everything important AFTER the summary: warnings printed during
    # the run scroll out of sight behind the progress output.
    if missing_report:
        total, dup_saves, report_path = missing_report
        print("=" * 70)
        print("REPORTS")
        print("=" * 70)
        print(f"{report_path.name}: {total} ledger entries have no media file in the export")
        print(f"  - {dup_saves} are probably just duplicate listings of snaps that ARE saved")
        print(f"    (the duplicate_save_of column names the already-saved file)")
        print(f"  - {total - dup_saves} need review in the Snapchat app")
        print(f"  -> {report_path}")
    if stats.failed:
        print(f"NOTE: {stats.failed} file(s) failed processing -- their raw originals (when "
              f"recoverable) were saved to '{config.output_dir / 'recovered'}' so no media is lost. "
              f"See the per-file messages above.")
    if _run_messages:
        print("=" * 70)
        print("WARNINGS & NOTES RECAP (already shown above, repeated so they aren't missed)")
        print("=" * 70)
        for w in _run_messages:
            print(w)
            print("-" * 70)
