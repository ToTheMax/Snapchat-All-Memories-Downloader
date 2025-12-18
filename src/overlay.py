"""Image and video overlay merging functionality."""

import asyncio
import io
import tempfile
from pathlib import Path
from PIL import Image

from . import config
from .memory import Memory


def merge_image_overlay(output_path: Path, main_data: bytes, overlay_data: bytes | None, memory: Memory | None = None) -> None:
    """Merge image with optional overlay using PIL."""
    try:
        with Image.open(io.BytesIO(main_data)).convert("RGBA") as main_img:
            if overlay_data:
                try:
                    with Image.open(io.BytesIO(overlay_data)).convert("RGBA") as overlay_img:
                        overlay_resized = overlay_img.resize(main_img.size, Image.LANCZOS)
                        main_img.alpha_composite(overlay_resized)
                except Exception as e:
                    if memory:
                        print(f"Failed to load overlay for {memory.get_filename(occurrence=memory.occurrence)}: {e}")
                    else:
                        print(f"Failed to load overlay image: {e}")
                    memory.fix_paths_on_merge_failure(config.overlay_mode)
                    memory.path_without_overlay.write_bytes(main_data)
                    print(f"Saved version without overlay: {memory.path_without_overlay}")
                    raise
            merged_img = main_img.convert("RGB")
            merged_img.save(output_path, "JPEG", quality=95, optimize=False)
    except Exception as e:
        if memory:
            print(f"Failed to process image {memory.get_filename(occurrence=memory.occurrence)}: {e}")
        else:
            print(f"Failed to process image: {e}")
        raise


async def _try_ffmpeg_merge(
    ffmpeg_path: str, main_path: Path, overlay_path: Path, merged_path: Path, overlay_bytes: bytes
) -> bool:
    """Attempt ffmpeg merge with given overlay bytes. Returns True if successful."""
    overlay_path.write_bytes(overlay_bytes)
    process = await asyncio.create_subprocess_exec(
        ffmpeg_path,
        "-y",
        "-i",
        str(main_path),
        "-i",
        str(overlay_path),
        "-filter_complex",
        "[1][0]scale2ref=w=iw:h=ih[overlay][base];[base][overlay]overlay=(W-w)/2:(H-h)/2",
        "-codec:a",
        "copy",
        str(merged_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, _ = await process.communicate()
    return process.returncode == 0


async def merge_video_overlay(
    output_path: Path, main_data: bytes, overlay_data: bytes | None, memory: Memory
) -> None:
    """Merge video with optional overlay using ffmpeg."""
    with tempfile.TemporaryDirectory() as tmpdir:
        main_path = Path(tmpdir) / "main.mp4"
        merged_path = Path(tmpdir) / "merged.mp4"
        main_path.write_bytes(main_data)

        if overlay_data:
            # Detect overlay format and apply correct extension
            is_webp = overlay_data.startswith(b'RIFF') and b'WEBP' in overlay_data[:12]
            if is_webp:
                overlay_path = Path(tmpdir) / "overlay.webp"
            else:
                overlay_path = Path(tmpdir) / "overlay.png"
            
            try:
                # First attempt: try with original overlay
                if await _try_ffmpeg_merge(config.ffmpeg_path, main_path, overlay_path, merged_path, overlay_data):
                    output_path.write_bytes(merged_path.read_bytes())
                else:
                    # Second attempt: try PIL re-encode fallback
                    print(f"ffmpeg merge failed for {memory.get_filename(has_overlay=True, occurrence=memory.occurrence)}, attempting PIL re-encode fix...")
                    try:
                        img = Image.open(io.BytesIO(overlay_data))
                        # Re-save to clean up corruption
                        with tempfile.NamedTemporaryFile(suffix='.webp' if is_webp else '.png', delete=False) as tmp:
                            img.save(tmp.name, 'WEBP' if is_webp else 'PNG')
                            cleaned_overlay_data = Path(tmp.name).read_bytes()
                            Path(tmp.name).unlink()
                        
                        # Retry merge with cleaned overlay
                        if await _try_ffmpeg_merge(config.ffmpeg_path, main_path, overlay_path, merged_path, cleaned_overlay_data):
                            output_path.write_bytes(merged_path.read_bytes())
                        else:
                            raise RuntimeError("ffmpeg merge failed even with cleaned overlay")
                    except Exception as e:
                        print(f"Warning: PIL re-encode fallback failed: {e}")
                        raise
            except Exception:
                error_msg = "ffmpeg overlay merge failed"
                print(f"{error_msg} for {memory.get_filename(has_overlay=True, occurrence=memory.occurrence)}")
                memory.fix_paths_on_merge_failure(config.overlay_mode)
                memory.path_without_overlay.write_bytes(main_data)
                print(f"Saved version without overlay: {memory.path_without_overlay}")
                raise RuntimeError(error_msg)
        else:
            output_path.write_bytes(main_data)
