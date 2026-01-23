import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import exif
import httpx
from pydantic import BaseModel, Field, field_validator
from tqdm.asyncio import tqdm


class Memory(BaseModel):
    date: datetime = Field(alias="Date")
    mediaType: str = Field(alias="Media Type")
    download_link: str = Field(alias="Download Link")
    location: str = Field(default="", alias="Location")
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, str):
            return datetime.strptime(v, "%Y-%m-%d %H:%M:%S UTC")
        return v

    def model_post_init(self, __context):
        if self.location and not self.latitude:
            if match := re.search(r"([-\d.]+),\s*([-\d.]+)", self.location):
                self.latitude = float(match.group(1))
                self.longitude = float(match.group(2))

    @property
    def filename(self) -> str:
        return self.date.strftime("%Y-%m-%d_%H-%M-%S")


class Stats(BaseModel):
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    mb: float = 0


def load_memories(json_path: Path) -> list[Memory]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Memory(**item) for item in data["Saved Media"]]


async def get_cdn_url(download_link: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            download_link,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.text.strip()


def add_exif_data(image_path: Path, memory: Memory):
    try:
        with open(image_path, "rb") as f:
            img = exif.Image(f)

        dt_str = memory.date.strftime("%Y:%m:%d %H:%M:%S")
        img.datetime_original = dt_str
        img.datetime_digitized = dt_str
        img.datetime = dt_str

        if memory.latitude is not None and memory.longitude is not None:
            # Convert decimal degrees to degrees, minutes, seconds
            def decimal_to_dms(decimal):
                degrees = int(abs(decimal))
                minutes_decimal = (abs(decimal) - degrees) * 60
                minutes = int(minutes_decimal)
                seconds = (minutes_decimal - minutes) * 60
                return (degrees, minutes, seconds)
            
            lat_dms = decimal_to_dms(memory.latitude)
            lon_dms = decimal_to_dms(memory.longitude)
            
            img.gps_latitude = lat_dms
            img.gps_latitude_ref = "N" if memory.latitude >= 0 else "S"
            img.gps_longitude = lon_dms
            img.gps_longitude_ref = "E" if memory.longitude >= 0 else "W"

        with open(image_path, "wb") as f:
            f.write(img.get_file())
    except:
        pass


async def download_memory(
    memory: Memory, idx: int, to_download: list[Memory], output_dir: Path, add_exif: bool, semaphore: asyncio.Semaphore
) -> tuple[bool, int]:
    async with semaphore:
        try:
            cdn_url = await get_cdn_url(memory.download_link)
            ext = memory.mediaType.lower() == "video" and ".mp4" or ".jpg"
            if(idx > 0 and to_download[idx-1].date == memory.date):
                for i in range(2, 30):
                    if(idx >= i and to_download[idx-i].date == memory.date):
                        continue
                    output_path = output_dir / f"{memory.filename}_{i}{ext}"
                    break
            else:
                output_path = output_dir / f"{memory.filename}{ext}"

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(cdn_url)
                response.raise_for_status()

                output_path.write_bytes(response.content)

                timestamp = memory.date.timestamp()
                os.utime(output_path, (timestamp, timestamp))

                if add_exif and ext == ".jpg":
                    add_exif_data(output_path, memory)

                return True, len(response.content)
        except Exception as e:
            print(f"\nError: {e}")
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
        jpg_path = output_dir / f"{memory.filename}.jpg"
        mp4_path = output_dir / f"{memory.filename}.mp4"
        if skip_existing and (jpg_path.exists() or mp4_path.exists()):
            stats.skipped += 1
        else:
            to_download.append(memory)

    if not to_download:
        print("All files already downloaded!")
        return
    
    to_download = list(reversed(to_download))

    progress_bar = tqdm(
        total=len(to_download),
        desc="Downloading",
        unit="file",
        disable=False,
    )

    async def process_and_update(memory, idx, to_download):
        success, bytes_downloaded = await download_memory(
            memory, idx, to_download, output_dir, add_exif, semaphore
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

    await asyncio.gather(*[process_and_update(m, idx, to_download) for (idx, m) in enumerate(to_download)])

    progress_bar.close()
    elapsed = time.time() - start_time
    mb_total = stats.mb
    mb_per_sec = mb_total / elapsed if elapsed > 0 else 0
    print(
        f"\n{'='*50}\nDownloaded: {stats.downloaded} ({mb_total:.1f} MB @ {mb_per_sec:.2f} MB/s) | Skipped: {stats.skipped} | Failed: {stats.failed}\n{'='*50}"
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Download Snapchat memories from data export"
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
    parser.add_argument("--no-exif", action="store_true", help="Disable EXIF metadata")
    parser.add_argument(
        "--no-skip-existing", action="store_true", help="Re-download existing files"
    )
    args = parser.parse_args()

    json_path = Path(args.json_file)
    output_dir = Path(args.output)

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
