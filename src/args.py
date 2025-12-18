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
        help="Overlay handling: 'none'=no overlays, 'with'=only with overlays, 'both'=save both versions (default: none)",
    )
    parser.add_argument(
        "--overlay-naming",
        choices=["single-folder", "separate-folders"],
        default="separate-folders",
        help="How to organize overlaid vs non-overlaid files when --overlay=both (default: separate-folders)",
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
        "--ocr-metadata",
        action="store_true",
        help="Run OCR on overlays and embed extracted text into metadata (disabled by default)",
    )
    parser.add_argument(
        "--copy-overlays",
        action="store_true",
        help="Save a copy of overlay files to 'overlays' subfolder (requires --overlay=both)",
    )
    return parser.parse_args()


def setup_config():
    """Parse arguments and apply them to config module."""
    args = parse_args()

    # Validate: OCR only works when overlays are being processed
    if args.ocr_metadata and args.overlay == "none":
        print("Error: --ocr-metadata requires overlays to be enabled.")
        print("Use --overlay with or both instead of none.")
        exit(1)

    # Validate: copy-overlays only works in 'both' mode
    if args.copy_overlays and args.overlay != "both":
        print("Error: --copy-overlays requires --overlay=both mode.")
        print("Use --overlay=both to enable saving both versions.")
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
    config.ocr_metadata = args.ocr_metadata
    config.save_overlays_only = args.copy_overlays

    return Path(args.json_file)
