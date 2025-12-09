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

import streamlit as st


# -----------------------------
# Data models
# -----------------------------
class Memory(BaseModel):
    date: datetime = Field(alias="Date")
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
    mb: float = 0.0


# -----------------------------
# Helpers
# -----------------------------
def load_memories_from_file(file_obj) -> list[Memory]:
    """Load memories from an uploaded JSON file-like object."""
    data = json.load(file_obj)
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
            def decimal_to_dms(decimal: float):
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
    except Exception:
        pass


async def download_memory(
    memory: Memory,
    output_dir: Path,
    add_exif: bool,
    semaphore: asyncio.Semaphore,
) -> tuple[bool, int]:
    async with semaphore:
        try:
            cdn_url = await get_cdn_url(memory.download_link)
            ext = Path(cdn_url.split("?")[0]).suffix or ".jpg"
            output_path = output_dir / f"{memory.filename}{ext}"

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(cdn_url)
                response.raise_for_status()

                output_path.write_bytes(response.content)

                timestamp = memory.date.timestamp()
                os.utime(output_path, (timestamp, timestamp))

                if add_exif and ext.lower() == ".jpg":
                    add_exif_data(output_path, memory)

                return True, len(response.content)
        except Exception as e:
            # Streamlit will show errors via st.error in the caller instead of print
            return False, 0


async def download_all_streamlit(
    memories: list[Memory],
    output_dir: Path,
    max_concurrent: int,
    add_exif: bool,
    skip_existing: bool,
    progress_bar,
    status_placeholder,
    log_placeholder,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrent)
    stats = Stats()
    start_time = time.time()

    # Filter memories to download
    to_download: list[Memory] = []
    for memory in memories:
        jpg_path = output_dir / f"{memory.filename}.jpg"
        mp4_path = output_dir / f"{memory.filename}.mp4"
        if skip_existing and (jpg_path.exists() or mp4_path.exists()):
            stats.skipped += 1
        else:
            to_download.append(memory)

    if not to_download:
        status_placeholder.info("All files already downloaded!")
        return

    total = len(to_download)
    progress_bar.progress(0)
    status_placeholder.text(f"Starting downloads... (0 / {total})")

    # Inner function to process a single memory and update UI
    async def process_and_update(i: int, memory: Memory):
        success, bytes_downloaded = await download_memory(
            memory, output_dir, add_exif, semaphore
        )
        if success:
            stats.downloaded += 1
        else:
            stats.failed += 1

        stats.mb += bytes_downloaded / (1024 * 1024)

        # Update progress
        completed = stats.downloaded + stats.failed
        elapsed = time.time() - start_time
        mb_per_sec = stats.mb / elapsed if elapsed > 0 else 0.0

        progress_bar.progress(completed / total)
        status_placeholder.text(
            f"Downloading... {completed} / {total} | "
            f"{stats.mb:.1f} MB total @ {mb_per_sec:.2f} MB/s"
        )

    # Launch downloads concurrently, but still update progress
    await asyncio.gather(
        *[process_and_update(i, m) for i, m in enumerate(to_download)]
    )

    elapsed = time.time() - start_time
    mb_total = stats.mb
    mb_per_sec = mb_total / elapsed if elapsed > 0 else 0.0

    log_placeholder.success(
        f"Downloaded: {stats.downloaded} files "
        f"({mb_total:.1f} MB @ {mb_per_sec:.2f} MB/s) | "
        f"Skipped: {stats.skipped} | Failed: {stats.failed}"
    )


# -----------------------------
# Streamlit UI
# -----------------------------
def main():
    st.title("Snapchat Memories Downloader")
    st.write(
        "Upload your `memories_history.json` from a Snapchat data export and "
        "this app will download all the photos and videos for you."
    )

    st.markdown("#### Step 1: Upload `memories_history.json`")
    uploaded_json = st.file_uploader(
        "Choose your `memories_history.json` file",
        type=["json"],
        help="From Snapchat: Settings → My Data → request data → download → memories_history.json",
    )

    st.markdown("#### Step 2: Choose download options")

    output_dir_str = st.text_input(
        "Output folder on this computer",
        value="downloads",
        help="Files will be saved here. Use an absolute path if you prefer.",
    )

    max_concurrent = st.slider(
        "Max concurrent downloads",
        min_value=1,
        max_value=60,
        value=40,
        help="Higher values are faster but may be harder on your network.",
    )

    add_exif = st.checkbox(
        "Add EXIF metadata (date + GPS when available) to JPGs",
        value=True,
    )

    skip_existing = st.checkbox(
        "Skip files that already exist in the output folder",
        value=True,
    )

    start_button = st.button("Start Download")

    # Placeholders for progress + log
    progress_bar = st.progress(0)
    status_placeholder = st.empty()
    log_placeholder = st.empty()

    if start_button:
        if not uploaded_json:
            st.error("Please upload your `memories_history.json` file first.")
            return

        # Resolve and create output directory
        output_dir = Path(output_dir_str).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load memories from uploaded JSON
        try:
            with st.spinner("Reading JSON and parsing memories..."):
                memories = load_memories_from_file(uploaded_json)
        except Exception as e:
            st.error(f"Failed to read JSON: {e}")
            return

        st.info(f"Found {len(memories)} memories in the file.")

        # Run the async download logic
        try:
            asyncio.run(
                download_all_streamlit(
                    memories,
                    output_dir,
                    max_concurrent,
                    add_exif,
                    skip_existing,
                    progress_bar,
                    status_placeholder,
                    log_placeholder,
                )
            )
        except RuntimeError as e:
            # Fallback if there's already an event loop running
            st.error(
                "Asyncio event loop error. If you see this in some environments "
                " (e.g., Jupyter), run this as `streamlit run streamlit_app.py` "
                f"from a terminal.\n\nDetails: {e}"
            )


if __name__ == "__main__":
    main()
