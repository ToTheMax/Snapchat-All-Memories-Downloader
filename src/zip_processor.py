"""ZIP file processing, overlay merging, and overlay OCR."""

import io
import zipfile
from pathlib import Path

from .ocr import extract_overlay_text_easy

from . import config
from .config import OverlayMode, OverlayNaming
from .memory import Memory, MediaType
from .stats import Stats
from .overlay import merge_image_overlay, merge_video_overlay

async def process_zip_with_overlays(output_path: Path, zip_content: bytes, memory: Memory, stats: Stats) -> None:
    """Extract and merge media from ZIP file with overlays.
    
    Handles different overlay modes:
    - 'with': Save only merged version with overlays to output_path
    - 'both': Save merged version to 'with_overlays' subfolder and main-only to 'without_overlays' subfolder
    
    If merge fails, saves the unextracted ZIP to an error folder for manual inspection.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            files = zf.namelist()
            main_file = next((f for f in files if "-main" in f), None)
            overlay_file = next((f for f in files if "-overlay" in f), None)

            if not main_file:
                raise ValueError("No main media file found in ZIP.")

            main_data = zf.read(main_file)
            overlay_data = zf.read(overlay_file) if overlay_file else None

            # If overlay exists and OCR is enabled, extract caption text (WebP/PNG)
            if overlay_data and config.ocr_metadata:
                memory.extracted_ocr_text = extract_overlay_text_easy(overlay_data)

            if config.overlay_mode == OverlayMode.BOTH:
                if config.overlay_naming == OverlayNaming.SINGLE_FOLDER:
                    overlay_memory_path = config.output_dir / memory.get_filename(has_overlay=True, occurrence=memory.occurrence)
                    no_overlay_memory_path = config.output_dir / memory.get_filename(has_overlay=False, occurrence=memory.occurrence)
                elif config.overlay_naming == OverlayNaming.SEPARATE_FOLDERS:
                    overlay_dir = config.output_dir / config.WITH_OVERLAYS_DIR
                    no_overlay_dir = config.output_dir / config.WITHOUT_OVERLAYS_DIR
                    overlay_memory_path = overlay_dir / memory.get_filename(has_overlay=True, occurrence=memory.occurrence)
                    no_overlay_memory_path = no_overlay_dir / memory.get_filename(has_overlay=False, occurrence=memory.occurrence)
                # Save version with overlays
                memory.path_with_overlay = overlay_memory_path
                memory.path_without_overlay = no_overlay_memory_path
                if memory.media_type == MediaType.IMAGE:
                    merge_image_overlay(overlay_memory_path, main_data, overlay_data, memory)
                    stats.total_images += 1
                    stats.images_with_overlay += 1
                elif memory.media_type == MediaType.VIDEO:
                    await merge_video_overlay(overlay_memory_path, main_data, overlay_data, memory)
                    stats.total_videos += 1
                    stats.videos_with_overlay += 1
                else:
                    raise ValueError(f"Unsupported media type: {memory.media_type}")

                # Save version without overlays (main only - no merge needed)
                no_overlay_memory_path.write_bytes(main_data)
                # Count the extra copy
                if memory.media_type == MediaType.IMAGE:
                    stats.extra_images_without_overlay += 1
                else:
                    stats.extra_videos_without_overlay += 1
                
                # Optionally save a copy of the overlay file to overlays folder
                if config.save_overlays_only and overlay_data:
                    overlays_dir = config.output_dir / config.overlays_dir
                    overlays_dir.mkdir(parents=True, exist_ok=True)
                    overlay_copy_path = overlays_dir / memory.get_overlay_filename(occurrence=memory.occurrence)
                    overlay_copy_path.write_bytes(overlay_data)
            else:
                # 'with' mode: save only merged version with overlays to output_path
                memory_path = output_path / memory.get_filename(has_overlay=True, occurrence=memory.occurrence)
                memory.path_with_overlay = memory_path
                if memory.media_type == MediaType.IMAGE:
                    merge_image_overlay(memory_path, main_data, overlay_data, memory)
                    stats.total_images += 1
                    stats.images_with_overlay += 1
                elif memory.media_type == MediaType.VIDEO:
                    await merge_video_overlay(memory_path, main_data, overlay_data, memory)
                    stats.total_videos += 1
                    stats.videos_with_overlay += 1
                else:
                    raise ValueError(f"Unsupported media type: {memory.media_type}")
    except Exception as e:
        stats.overlay_failed += 1
        print(f"Error processing ZIP for {memory.get_filename(occurrence=memory.occurrence)}: {e}")
        print("Saving extracted files to error folder for manual inspection.")
        
        # Extract and save files to error subfolder
        error_dir = config.output_dir / "error_zips" / memory.get_filename(occurrence=memory.occurrence).rsplit('.', 1)[0]
        error_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
                for file_info in zf.filelist:
                    file_data = zf.read(file_info.filename)
                    
                    # Check if this is an overlay file that's actually WebP
                    filename_to_save = file_info.filename
                    if "-overlay" in file_info.filename and file_info.filename.endswith('.png'):
                        if file_data.startswith(b'RIFF') and b'WEBP' in file_data[:12]:
                            # Rename from .png to .webp
                            filename_to_save = file_info.filename.replace('.png', '.webp')
                    
                    error_file_path = error_dir / filename_to_save
                    error_file_path.parent.mkdir(parents=True, exist_ok=True)
                    error_file_path.write_bytes(file_data)
                    print(f"  Saved: {error_file_path.relative_to(config.output_dir)}")
        except Exception as extract_error:
            print(f"Could not extract ZIP contents, saving raw ZIP file instead: {extract_error}")
            error_zip_path = error_dir.parent / f"{memory.get_filename(occurrence=memory.occurrence).rsplit('.', 1)[0]}.zip"
            error_zip_path.write_bytes(zip_content)
            print(f"  Saved ZIP ({len(zip_content)} bytes) to: {error_zip_path.relative_to(config.output_dir)}")
