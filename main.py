import argparse
import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path
import io
import zipfile
from PIL import Image
import tempfile
from zoneinfo import ZoneInfo
import piexif
import httpx
from pydantic import BaseModel, Field, field_validator
from tqdm.asyncio import tqdm
from tzlocal import get_localzone


class Memory(BaseModel):
    date: datetime = Field(alias="Date")
    media_type: str = Field(alias="Media Type")
    download_link: str = Field(alias="Media Download Url")
    location: str = Field(default="", alias="Location")
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, str):
            # Parse from UTC (Snapchat JSON is always UTC)
            dt = datetime.strptime(v, "%Y-%m-%d %H:%M:%S UTC")
            dt = dt.replace(tzinfo=timezone.utc)
            # Convert to local Pacific Time (handles PST/PDT automatically)
            local_tz = get_localzone()
            return dt.astimezone(local_tz)
        return v


    def model_post_init(self, __context):
        if self.location and not self.latitude:
            if match := re.search(r"([-\d.]+),\s*([-\d.]+)", self.location):
                self.latitude = float(match.group(1))
                self.longitude = float(match.group(2))

    @property
    def filename(self) -> str:
        ext = ".jpg" if self.media_type.lower() == "image" else ".mp4"
        return f"{self.date.strftime('%Y-%m-%d_%H-%M-%S')}{ext}"


class Stats(BaseModel):
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    mb: float = 0


def load_memories(json_path: Path) -> list[Memory]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Memory(**item) for item in data["Saved Media"]]

def add_exif_data(image_path: Path, memory: Memory):
    def to_deg(value):
        """Convert decimal degrees to (deg, min, sec)."""
        d = int(abs(value))
        m_float = (abs(value) - d) * 60
        m = int(m_float)
        s = round((m_float - m) * 60, 6)
        return d, m, s

    def deg_to_rational(dms):
        """Convert (deg, min, sec) tuple to EXIF rational format."""
        d, m, s = dms
        return [
            (int(d), 1),
            (int(m), 1),
            (int(s * 100), 100)
        ]

    try:
        # Load existing EXIF if any
        try:
            exif_dict = piexif.load(str(image_path))
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        # Date/time
        dt_str = memory.date.strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["0th"][piexif.ImageIFD.DateTime] = dt_str
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_str
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_str

        # GPS if available
        if memory.latitude is not None and memory.longitude is not None:
            lat_ref = "N" if memory.latitude >= 0 else "S"
            lon_ref = "E" if memory.longitude >= 0 else "W"
            lat_dms = deg_to_rational(to_deg(memory.latitude))
            lon_dms = deg_to_rational(to_deg(memory.longitude))

            exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
            exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = lat_dms
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = lon_dms
            exif_dict["GPS"][piexif.GPSIFD.GPSVersionID] = (2, 3, 0, 0)

        # Dump and insert
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(image_path))

        # Update filesystem timestamp
        ts = memory.date.timestamp()
        os.utime(image_path, (ts, ts))

    except Exception as e:
        print(f"Failed to set EXIF data for {image_path.name}: {e}")



def set_video_metadata(video_path: Path, memory: Memory):
    """
    Sets video creation time and Apple Photos-compatible GPS metadata.
    Uses ffmpeg via subprocess to inject metadata without re-encoding.
    """
    try:
        # Prepare UTC creation time in ISO 8601
        dt_utc = memory.date.astimezone(timezone.utc)
        iso_time = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        # Base metadata arguments
        metadata_args = ["-metadata", f"creation_time={iso_time}"]

        # Add location if available
        if memory.latitude is not None and memory.longitude is not None:
            lat = f"{memory.latitude:+.4f}"
            lon = f"{memory.longitude:+.4f}"
            alt = getattr(memory, "altitude", 0.0)
            iso6709 = f"{lat}{lon}+{alt:.3f}/"

            # Apple Photos-compatible fields
            metadata_args += [
                "-metadata", f"location={iso6709}",
                "-metadata", f"location-eng={iso6709}",
            ]

        # Temporary output file
        temp_path = video_path.with_suffix(".temp.mp4")

        # Run ffmpeg: copy streams, inject metadata
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", str(video_path),
                *metadata_args,
                "-codec", "copy",
                str(temp_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Replace original file
        temp_path.replace(video_path)

        # Update filesystem timestamp
        os.utime(video_path, (memory.date.timestamp(), memory.date.timestamp()))

    except Exception as e:
        print(f"Failed to set video metadata for {video_path.name}: {e}")

async def download_memory(
    memory: Memory, output_dir: Path, add_exif: bool, semaphore: asyncio.Semaphore
) -> tuple[bool, int]:
    async with semaphore:
        try:
            url = memory.download_link
            output_path = output_dir / memory.filename

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content

                # Detect ZIP (overlay)
                is_zip = response.headers.get("Content-Type", "").lower().startswith("application/zip")

                if is_zip:
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        files = zf.namelist()
                        main_file = next((f for f in files if "-main" in f), None)
                        overlay_file = next((f for f in files if "-overlay" in f), None)

                        if not main_file:
                            raise ValueError("No main media file found in ZIP.")

                        main_data = zf.read(main_file)
                        overlay_data = zf.read(overlay_file) if overlay_file else None

                        if memory.media_type.lower() == "image":
                            # === IMAGE MERGE ===
                            with Image.open(io.BytesIO(main_data)).convert("RGBA") as main_img:
                                if overlay_data:
                                    with Image.open(io.BytesIO(overlay_data)).convert("RGBA") as overlay_img:
                                        overlay_resized = overlay_img.resize(main_img.size, Image.LANCZOS)
                                        main_img.alpha_composite(overlay_resized)
                                merged_img = main_img.convert("RGB")
                                merged_img.save(output_path, "JPEG")

                        elif memory.media_type.lower() == "video":
                            # === VIDEO MERGE ===
                            with tempfile.TemporaryDirectory() as tmpdir:
                                main_path = Path(tmpdir) / "main.mp4"
                                merged_path = Path(tmpdir) / "merged.mp4"
                                with open(main_path, "wb") as f:
                                    f.write(main_data)

                                if overlay_data:
                                    overlay_path = Path(tmpdir) / "overlay.png"
                                    with open(overlay_path, "wb") as f:
                                        f.write(overlay_data)
                                    try:
                                        subprocess.run(
                                            [
                                                "ffmpeg", "-y",
                                                "-i", str(main_path),
                                                "-i", str(overlay_path),
                                                "-filter_complex",
                                                (
                                                    "[1][0]scale2ref=w=iw:h=ih[overlay][base];"
                                                    "[base][overlay]overlay=(W-w)/2:(H-h)/2"
                                                ),
                                                "-codec:a", "copy",
                                                str(merged_path),
                                            ],
                                            check=True,
                                            stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL,
                                        )
                                        # Copy merged output to final location
                                        output_path.write_bytes(merged_path.read_bytes())
                                    except subprocess.CalledProcessError as e:
                                        print(f"ffmpeg overlay merge failed for {memory.filename}, saving main only.")
                                        output_path.write_bytes(main_data)
                                else:
                                    # No overlay file
                                    output_path.write_bytes(main_data)

                        else:
                            raise ValueError(f"Unsupported media type: {memory.media_type}")

                        bytes_downloaded = len(content)

                else:
                    # === NORMAL DOWNLOAD (not ZIP) ===
                    output_path.write_bytes(content)
                    bytes_downloaded = len(content)

                # Set timestamps
                timestamp = memory.date.timestamp()
                os.utime(output_path, (timestamp, timestamp))

                # Apply metadata
                if add_exif:
                    if memory.media_type.lower() == "image":
                        add_exif_data(output_path, memory)
                    elif memory.media_type.lower() == "video":
                        set_video_metadata(output_path, memory)

                # ✅ Always return success + byte count
                return True, bytes_downloaded

        except Exception as e:
            print(f"\nError downloading {memory.filename}: {e}")
            return False, 0



async def download_all(
    memories: list[Memory],
    output_dir: Path,
    max_concurrent: int,
    add_exif: bool,
    skip_existing: bool,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrent)
    stats = Stats()
    start_time = time.time()

    to_download = []
    for memory in memories:
        output_path = output_dir / memory.filename
        if skip_existing and output_path.exists():
            stats.skipped += 1
        else:
            to_download.append(memory)

    if not to_download:
        print("All files already downloaded!")
        return

    progress_bar = tqdm(
        total=len(to_download),
        desc="Downloading",
        unit="file",
        disable=False,
    )

    async def process_and_update(memory):
        success, bytes_downloaded = await download_memory(
            memory, output_dir, add_exif, semaphore
        )
        if success:
            stats.downloaded += 1
        else:
            stats.failed += 1
        stats.mb += bytes_downloaded / 1024 / 1024

        elapsed = time.time() - start_time
        mb_per_sec = (stats.mb) / elapsed if elapsed > 0 else 0
        progress_bar.set_postfix({"MB/s": f"{mb_per_sec:.2f}"}, refresh=False)
        progress_bar.update(1)

    await asyncio.gather(*[process_and_update(m) for m in to_download])

    progress_bar.close()
    elapsed = time.time() - start_time
    mb_total = stats.mb
    mb_per_sec = mb_total / elapsed if elapsed > 0 else 0
    print(
        f"\n{'='*50}\nDownloaded: {stats.downloaded} ({mb_total:.1f} MB @ {mb_per_sec:.2f} MB/s) | "
        f"Skipped: {stats.skipped} | Failed: {stats.failed}\n{'='*50}"
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Download Snapchat memories from data export (new JSON format)"
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        default="json/memories_history.json",
        help="Path to memories_history.json",
    )
    parser.add_argument(
        "-o", "--output", default="./downloads", help="Output directory"
    )
    parser.add_argument(
        "-c", "--concurrent", type=int, default=40, help="Max concurrent downloads"
    )
    parser.add_argument("--no-exif", action="store_true", help="Disable metadata writing")
    parser.add_argument(
        "--no-skip-existing", action="store_true", help="Re-download existing files"
    )
    args = parser.parse_args()

    json_path = Path(args.json_file)
    output_dir = Path(args.output)

    print(f"Detected local timezone: {get_localzone()}")

    memories = load_memories(json_path)

    await download_all(
        memories,
        output_dir,
        args.concurrent,
        not args.no_exif,
        not args.no_skip_existing,
    )


if __name__ == "__main__":
    asyncio.run(main())
