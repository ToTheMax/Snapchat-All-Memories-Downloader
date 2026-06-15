"""Statistics tracking for downloads."""

from pydantic import BaseModel
from . import config
from .config import OverlayMode


class Stats(BaseModel):
    """Track download statistics."""
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    overlay_failed: int = 0
    mb: float = 0
    # Media type counters
    total_images: int = 0
    total_videos: int = 0
    images_with_overlay: int = 0
    images_without_overlay: int = 0
    videos_with_overlay: int = 0
    videos_without_overlay: int = 0
    # Both mode extra copies (separate files without overlay)
    extra_images_without_overlay: int = 0
    extra_videos_without_overlay: int = 0
    # Duplicate timestamp groups (number of unique timestamps with >1 occurrence)
    duplicate_timestamp_groups: int = 0

    def print_summary(self, elapsed_time: float) -> None:
        """Print comprehensive download statistics summary."""
        mb_per_sec = self.mb / elapsed_time if elapsed_time > 0 else 0
        
        # Print comprehensive statistics
        print(f"\n{'='*70}")
        print("DOWNLOAD SUMMARY")
        print(f"{'='*70}")
        print(f"Downloaded: {self.downloaded} | Skipped: {self.skipped} | Failed: {self.failed}")
        print(f"Total Size: {self.mb:.1f} MB @ {mb_per_sec:.2f} MB/s")
        print(f"{'='*70}")
        print("MEDIA BREAKDOWN")
        print(f"{'='*70}")
        # "overlay merged" = a separate overlay file was composited onto the media.
        # "no separate overlay" does NOT mean no caption: older memories can have
        # captions burned into the media itself, which need no merging.
        print(f"Images:  {self.total_images:4d} total | {self.images_with_overlay:4d} overlay merged | {self.images_without_overlay:4d} no separate overlay")
        print(f"Videos:  {self.total_videos:4d} total | {self.videos_with_overlay:4d} overlay merged | {self.videos_without_overlay:4d} no separate overlay")
        print(f"{'='*70}")
        print("DUPLICATE TIMESTAMPS")
        print(f"{'='*70}")
        print(f"Timestamps with multiple occurrences: {self.duplicate_timestamp_groups}")
        if config.overlay_mode == OverlayMode.BOTH and (self.extra_images_without_overlay > 0 or self.extra_videos_without_overlay > 0):
            print(f"{'='*70}")
            print("BOTH MODE EXTRA COPIES")
            print(f"{'='*70}")
            print(f"Extra images (without overlay): {self.extra_images_without_overlay}")
            print(f"Extra videos (without overlay): {self.extra_videos_without_overlay}")
        if self.overlay_failed > 0:
            print(f"{'='*70}")
            print("OVERLAY FAILURES")
            print(f"{'='*70}")
            print(f"Overlay merge failed: {self.overlay_failed}")
        print(f"{'='*70}")
