"""FFmpeg availability checking and management."""

import subprocess
import shutil

from . import config
from .config import OverlayMode


def check_ffmpeg(ffmpeg_path: str, overlay_mode: OverlayMode) -> bool:
    """
    Check if ffmpeg is available at the given path.
    
    Args:
        ffmpeg_path: Path to ffmpeg executable
        overlay_mode: Overlay mode ('none', 'with', or 'both')
    
    Returns:
        True if ffmpeg is available and check passes, False otherwise.
    """
    try:
        subprocess.run(
            [ffmpeg_path, "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Resolve the actual path (especially for commands in PATH)
        resolved_path = shutil.which(ffmpeg_path) or ffmpeg_path
        print(f"ffmpeg found at: {resolved_path}")
        config.ffmpeg_available = True
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        if overlay_mode in (OverlayMode.WITH, OverlayMode.BOTH):
            print(f"Error: ffmpeg not found at '{ffmpeg_path}'")
            print("ffmpeg is required for overlay merging.")
            print("Please install ffmpeg or specify correct path with --ffmpeg-path")
            return False
        else:
            print(f"Warning: ffmpeg not found at '{ffmpeg_path}'")
            print("ffmpeg is recommended for video metadata (timestamps, GPS, source tag).")
            print("Without ffmpeg, video metadata will NOT be applied.")
            response = input("Continue without ffmpeg? (y/n): ").strip().lower()
            if response != 'y':
                return False
            config.ffmpeg_available = False
            return True
