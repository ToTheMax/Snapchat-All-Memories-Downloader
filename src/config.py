"""Global configuration and defaults for Snapchat memories downloader."""

from enum import Enum
from pathlib import Path


class OverlayMode(Enum):
    """Overlay processing mode."""
    NONE = "none"
    WITH = "with"
    BOTH = "both"


class OverlayNaming(Enum):
    """Overlay file naming strategy when overlay_mode is 'both'."""
    SINGLE_FOLDER = "single-folder"
    SEPARATE_FOLDERS = "separate-folders"


# FFmpeg configuration
ffmpeg_path: str = "ffmpeg"
ffmpeg_available: bool = False

# Overlay settings
overlay_mode: OverlayMode = OverlayMode.NONE
overlay_naming: OverlayNaming = OverlayNaming.SEPARATE_FOLDERS

# Folder names for separate-folders mode
WITH_OVERLAYS_DIR: str = "with_overlays"
WITHOUT_OVERLAYS_DIR: str = "without_overlays"

# Output settings
output_dir: Path = Path("./downloads")
filename_prefix: str = ""

# Download settings
max_concurrent: int = 40
add_exif: bool = True
skip_existing: bool = True

# Overlay extraction settings
save_overlays_only: bool = False
overlays_dir: str = "overlays"

# Local import settings (bulk exports with inline media instead of download URLs)
from_zips: Path | None = None
subset: int = 0
import_unlisted: bool = False
test: bool = False
split: int = 0  # write media into numbered batch_NN/ subfolders of this many files (0 = off)
