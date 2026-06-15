"""Command-line argument parsing and configuration setup."""

import argparse
from pathlib import Path
from . import config
from .config import OverlayMode, OverlayNaming


def parse_args():
    """Parse command-line arguments and return parsed args."""
    parser = argparse.ArgumentParser(description="Download all your Snapchat memories")
    parser.add_argument(
        "json_file",
        type=str,
        help="Path to memories_history.json file from Snapchat data export",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="./downloads",
        help="Output directory for downloaded files (default: ./downloads)",
    )
    parser.add_argument(
        "--ffmpeg-path",
        default="ffmpeg",
        help="Path to ffmpeg executable (default: ffmpeg in PATH)",
    )
    parser.add_argument(
        "-c",
        "--concurrent",
        type=int,
        default=40,
        help="Number of concurrent downloads (default: 40)",
    )
    parser.add_argument(
        "--overlay",
        choices=["none", "with", "both"],
        default="none",
        help="Overlay handling: 'none'=no overlays, 'with'=only with overlays, 'both'=save both versions (default: none). "
        "Note: 'with'/'both' refer to merging the separate overlay file when one exists; "
        "older memories may have captions burned into the media itself and need no merging.",
    )
    parser.add_argument(
        "--overlay-naming",
        choices=["single-folder", "separate-folders"],
        default="separate-folders",
        help="How to organize overlaid vs non-overlaid files when --overlay=both (default: separate-folders). "
        "The 'with_overlays'/'without_overlays' folders mean a separate overlay file was/wasn't merged -- "
        "files in 'without_overlays' can still show captions if Snapchat burned them into the media itself "
        "(common for older memories).",
    )
    parser.add_argument(
        "--no-exif",
        action="store_true",
        help="Do not add metadata (faster, but loses location/timestamp info in files)",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-download and overwrite existing files instead of skipping them",
    )
    parser.add_argument(
        "--prefix", default="", help="Prefix to add to all downloaded filenames (e.g., 'SC_' creates 'SC_filename.ext')"
    )
    parser.add_argument(
        "--copy-overlays",
        action="store_true",
        help="Save a copy of overlay files to 'overlays' subfolder (requires --overlay=both)",
    )
    parser.add_argument(
        "--from-zips",
        metavar="DIR",
        help="Import media from bulk-export ZIPs in DIR instead of downloading. "
        "Use when your export bundles the media files and the JSON has empty download URLs.",
    )
    parser.add_argument(
        "--subset",
        type=int,
        default=0,
        metavar="N",
        help="Process only N curated items spread across media-type/GPS/overlay buckets "
        "(for a quick end-to-end test, e.g. before a Google Photos upload). Requires --from-zips.",
    )
    parser.add_argument(
        "--import-unlisted",
        action="store_true",
        help="Also import media files that are present in the export ZIPs but missing from "
        "the JSON, using each file's own timestamp (UTC, no GPS). Off by default so that a "
        "partial/filtered JSON doesn't pull in the whole archive. Requires --from-zips.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Export one representative of each scenario (photo/video x GPS x overlay, "
        "SCOF overlay, stitched-segment) plus TEST_EXPECTATIONS.txt describing what each "
        "should show in your photo app. For verifying metadata before a full run. Requires --from-zips.",
    )
    parser.add_argument(
        "--split",
        type=int,
        default=0,
        metavar="N",
        help="Write the media into numbered subfolders (batch_01/, batch_02/, ...) of N files "
        "each, so you can upload one folder at a time. Google Photos' web album upload tends to "
        "stall on huge batches; ~300-500 per folder uploads reliably. Reports and any "
        "recovered/orphan files stay in the output root. Requires --from-zips.",
    )
    return parser.parse_args()


def setup_config():
    """Parse arguments and apply them to config module."""
    args = parse_args()

    # Validate: copy-overlays only works in 'both' mode
    if args.copy_overlays and args.overlay != "both":
        print("Error: --copy-overlays requires --overlay=both mode.")
        print("Use --overlay=both to enable saving both versions.")
        exit(1)

    # Validate: subset/import-unlisted only work with from-zips
    if args.subset < 0:
        print("Error: --subset must be a non-negative integer.")
        exit(1)
    if args.subset and not args.from_zips:
        print("Error: --subset requires --from-zips mode.")
        exit(1)
    if args.import_unlisted and not args.from_zips:
        print("Error: --import-unlisted requires --from-zips mode.")
        exit(1)
    if args.test and not args.from_zips:
        print("Error: --test requires --from-zips mode.")
        exit(1)
    if args.split < 0:
        print("Error: --split must be a non-negative integer.")
        exit(1)
    if args.split and not args.from_zips:
        print("Error: --split requires --from-zips mode.")
        exit(1)
    if args.from_zips and not Path(args.from_zips).is_dir():
        print(f"Error: --from-zips directory not found: {args.from_zips}")
        exit(1)

    # Apply all args to config
    config.ffmpeg_path = args.ffmpeg_path
    config.overlay_mode = OverlayMode(args.overlay)
    config.overlay_naming = OverlayNaming(args.overlay_naming)
    config.output_dir = Path(args.output)
    config.max_concurrent = args.concurrent
    config.add_exif = not args.no_exif
    config.skip_existing = not args.no_skip_existing
    config.filename_prefix = args.prefix
    config.save_overlays_only = args.copy_overlays
    config.from_zips = Path(args.from_zips) if args.from_zips else None
    config.subset = args.subset
    config.import_unlisted = args.import_unlisted
    config.test = args.test
    config.split = args.split

    return Path(args.json_file)
