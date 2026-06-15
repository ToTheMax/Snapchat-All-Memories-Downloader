"""Metadata and timestamp handling for media files."""

import os
import subprocess
import piexif
from pathlib import Path
from datetime import timezone
import shutil

from . import config
from .memory import Memory, MediaType


def _to_deg(value):
    """Convert decimal degrees to (deg, min, sec)."""
    d = int(abs(value))
    m_float = (abs(value) - d) * 60
    m = int(m_float)
    s = round((m_float - m) * 60, 6)
    return d, m, s


def _deg_to_rational(dms):
    """Convert (deg, min, sec) tuple to EXIF rational format."""
    d, m, s = dms
    return [
        (int(d), 1),
        (int(m), 1),
        (int(s * 100), 100)
    ]


def add_exif_data(image_path: Path, memory: Memory):
    """Add EXIF metadata to an image file.

    Embeds the following EXIF data into the image:
    - DateTime fields (legacy): Local capture time without timezone (EXIF does not store TZ)
    - EXIF 2.31 offsets: `OffsetTime`, `OffsetTimeOriginal`, `OffsetTimeDigitized` as ±HH:MM
    - Software/Make tags: Identify "Snapchat" as source
    - GPS data: Latitude/Longitude (DMS) and UTC `GPSDateStamp`/`GPSTimeStamp` when available

    Filesystem timestamps (mtime/atime) are NOT set here; they are applied centrally
    in `_apply_metadata_to_path(...)` and are forced to UTC.

    Args:
        image_path: Path to the image file to modify
        memory: Memory containing date (tz-aware), and optional latitude/longitude

    Gracefully handles missing EXIF by creating a new structure when needed. Errors during
    EXIF embedding are logged but do not stop the download process.
    """
    try:
        # Load existing EXIF if any
        try:
            exif_dict = piexif.load(str(image_path))
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        # Date/time in local timezone (memory.date is already timezone-aware)
        # EXIF classic DateTime fields don't store timezone info, so we use local time
        dt_local = memory.date
        dt_str = dt_local.strftime("%Y:%m:%d %H:%M:%S")
        # DateTime: File modification time (general timestamp field)
        exif_dict["0th"][piexif.ImageIFD.DateTime] = dt_str
        # DateTimeOriginal: When photo was taken (original capture time)
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_str
        # DateTimeDigitized: When photo was digitized (same as original for digital photos)
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_str
        
        # Add EXIF 2.31 timezone offset fields if available
        try:
            utc_offset = dt_local.utcoffset()
            # NOTE: timedelta(0) is falsy -- a plain truthiness check would skip
            # the +00:00 offset for UTC datetimes, leaving no-GPS photos with a
            # naive timestamp that Google Photos misreads as local time.
            offset_total_minutes = utc_offset.total_seconds() / 60 if utc_offset is not None else None
        except Exception:
            offset_total_minutes = None
        if offset_total_minutes is not None:
            sign = '+' if offset_total_minutes >= 0 else '-'
            abs_min = int(abs(offset_total_minutes))
            offset_str = f"{sign}{abs_min // 60:02d}:{abs_min % 60:02d}"
            # OffsetTime (for DateTime), OffsetTimeOriginal, OffsetTimeDigitized
            exif_dict["Exif"][piexif.ExifIFD.OffsetTime] = offset_str
            exif_dict["Exif"][piexif.ExifIFD.OffsetTimeOriginal] = offset_str
            exif_dict["Exif"][piexif.ExifIFD.OffsetTimeDigitized] = offset_str

        # Set GPSDateStamp/GPSTimeStamp in UTC when GPS available later

        # Add application source (Snapchat) - must be bytes
        # Software: Identifies the app that created/processed the image
        exif_dict["0th"][piexif.ImageIFD.Software] = b"Snapchat"
        # Make: Camera device manufacturer/app
        exif_dict["0th"][piexif.ImageIFD.Make] = b"Snapchat"

        # GPS if available
        if memory.latitude is not None and memory.longitude is not None:
            lat_ref = "N" if memory.latitude >= 0 else "S"
            lon_ref = "E" if memory.longitude >= 0 else "W"
            lat_dms = _deg_to_rational(_to_deg(memory.latitude))
            lon_dms = _deg_to_rational(_to_deg(memory.longitude))

            # GPSLatitudeRef: Direction (N=North, S=South)
            exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref.encode()
            # GPSLongitudeRef: Direction (E=East, W=West)
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref.encode()
            # GPSLatitude: Latitude as (degrees, minutes, seconds)
            exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = lat_dms
            # GPSLongitude: Longitude as (degrees, minutes, seconds)
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = lon_dms
            # GPSVersionID: GPS IFD version (2.3.0.0)
            exif_dict["GPS"][piexif.GPSIFD.GPSVersionID] = (2, 3, 0, 0)

            # GPSDateStamp and GPSTimeStamp: always UTC per EXIF spec
            dt_utc = dt_local.astimezone(timezone.utc)
            exif_dict["GPS"][piexif.GPSIFD.GPSDateStamp] = dt_utc.strftime("%Y:%m:%d")
            # GPSTimeStamp is array of rationals: [hour, minute, second]
            h, m, s = dt_utc.hour, dt_utc.minute, dt_utc.second
            exif_dict["GPS"][piexif.GPSIFD.GPSTimeStamp] = [
                (h, 1), (m, 1), (s, 1)
            ]

        # Dump and insert
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(image_path))


    except Exception as e:
        print(f"Failed to set EXIF data for {image_path.name}: {e}")


# exiftool is optional: only needed to write the GPSCoordinates (©xyz) atom that
# Google Photos reads for video location. Crucially it must go in the ItemList
# container (moov/udta/meta/ilst/©xyz) -- the same place iPhones write it and the
# only one Google Photos reads. Writing ©xyz to raw UserData (moov/udta/©xyz) is
# ignored by Google Photos. ffmpeg's own Keys 'location'/loci tags are ignored too.
# Google Photos ALSO derives the video's display timezone from this GPS: a GPS
# video shows the correct local time of its location, while a no-GPS video falls
# back to the viewer's account timezone (QuickTime creation_time is UTC-only and
# carries no zone). So this one atom fixes both the map pin and the shown time.
# Verified with iPhone videos and fresh A/B web uploads (location + a Tokyo-GPS
# clip that displayed in JST, not the account zone). Resolved once at import time.
_EXIFTOOL_PATH = shutil.which("exiftool")
_warned_no_exiftool = False


def _add_video_gps_xyz(video_path: Path, latitude: float, longitude: float) -> None:
    """Write the GPSCoordinates (©xyz) atom into the ItemList container via exiftool
    -- the location format/place Google Photos reads for videos."""
    global _warned_no_exiftool
    if not _EXIFTOOL_PATH:
        if not _warned_no_exiftool:
            print("Note: exiftool not found -- video GPS will NOT show in Google Photos "
                  "(only the ffmpeg-written tags are present). Install exiftool for "
                  "Google Photos video GPS support.")
            _warned_no_exiftool = True
        return
    try:
        subprocess.run(
            [_EXIFTOOL_PATH, "-n", "-overwrite_original", "-q",
             f"-ItemList:GPSCoordinates={latitude} {longitude} 0",
             str(video_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"Failed to write video GPS atom for {video_path.name}: {e}")


def set_video_metadata(video_path: Path, memory: Memory):
    """
    Set video metadata using ffmpeg without re-encoding.

    - Timestamps: Written in UTC using ISO 8601 `YYYY-MM-DDTHH:MM:SSZ` for
        `creation_time` and a generic `date` tag to maximize cross-platform compatibility.
    - Software/Make: Identify "Snapchat" as source using common tags (©too/software/Make).
    - Location: When available, writes Apple Photos-compatible `location` and `location-eng`
        in ISO 6709 format (±lat±lon+alt/).

    Filesystem timestamps (mtime/atime) are NOT set here; they are applied centrally
    in `_apply_metadata_to_path(...)` and are forced to UTC.
    """
    try:
        # Prepare creation time in UTC (force timezone-aware -> UTC)
        # Use ISO 8601 with explicit UTC designator 'Z'
        dt_utc = memory.date.astimezone(timezone.utc)
        iso_time = dt_utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        # Base metadata arguments with application source using ©too tag (QuickTime software tag)
        metadata_args = [
            "-metadata", f"creation_time={iso_time}",
            "-metadata", f"date={iso_time}",  # Generic date in UTC for cross-platform compatibility
            "-metadata", "©too=Snapchat",  # QuickTime software tag - standardized for app identification
            "-metadata", "software=Snapchat",  # Generic software tag for non-Apple players
            "-metadata", "Make=Snapchat",  # Camera device/source
        ]

        # No description/comment tag is written; the caption is merged into the video frames via the overlay pipeline.

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
                "-movflags", "use_metadata_tags",
                str(temp_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Replace original file
        temp_path.replace(video_path)

        # Add the ©xyz GPS atom for Google Photos (ffmpeg cannot write it to mp4)
        if memory.latitude is not None and memory.longitude is not None:
            _add_video_gps_xyz(video_path, memory.latitude, memory.longitude)

    except Exception as e:
        print(f"Failed to set video metadata for {video_path.name}: {e}")


def _apply_metadata_to_path(file_path: Path, memory: Memory, timestamp: float) -> None:
    """Helper function to apply metadata to a single file path."""
    if not file_path.exists():
        return
    

    if not config.add_exif:
        return
    
    if memory.media_type == MediaType.IMAGE:
        add_exif_data(file_path, memory)
    elif memory.media_type == MediaType.VIDEO and config.ffmpeg_available:
        set_video_metadata(file_path, memory)


    # Ensure filesystem timestamp is UTC
    ts_utc = memory.date.astimezone(timezone.utc).timestamp()
    os.utime(file_path, (ts_utc, ts_utc))
    

def apply_metadata_and_timestamps(memory: Memory) -> None:
    """Apply metadata and timestamps to downloaded media files."""
    # Use UTC timestamp for filesystem mtime/atime
    timestamp = memory.date.astimezone(timezone.utc).timestamp()
    
    # Apply to path_with_overlay if set
    if memory.path_with_overlay is not None:
        _apply_metadata_to_path(memory.path_with_overlay, memory, timestamp)
    
    # Apply to path_without_overlay if set
    if memory.path_without_overlay is not None:
        _apply_metadata_to_path(memory.path_without_overlay, memory, timestamp)
