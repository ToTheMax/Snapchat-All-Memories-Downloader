# Snapchat-All-Memories-Downloader
This script will download all your Snapchat memories in bulk, **including the timestamp and geolocation**.

![demo](./demo.gif)


## Getting your Data

> [!WARNING]
> **Before you export:** a single Snapchat export may not be 100% complete — it can omit media that's still in the app, and its contents vary between requests. See [The export may not be 100% complete](#the-export-may-not-be-100-complete).

- Login to Snapchat and request your data: https://accounts.snapchat.com/accounts/downloadmydata
- Select the `Export your Memories` and `Export JSON Files` option and continue
- Date Range: Select "All Time" to get all your memories
- You'll receive one or more ZIP files (e.g. `mydata~XXXXX.zip`, `mydata~XXXXX-2.zip`, …). **Download all of them into a single folder** — newer exports put your actual photos and videos inside these ZIPs, so you need the whole set, not just the first.

![export configuration](https://github.com/user-attachments/assets/dfcdb6a0-e554-46e8-bdba-77fe41c88a03)

## The export may not be 100% complete

It has been observed that an export may or may not include 100% of your memories. The index file (`memories_history.json`) lists them, but it isn't a guarantee that every memory has an actual photo/video in the ZIPs, and it has been found that the contents can differ between export requests. A few cases to be aware of:

- The index may list a memory whose photo/video isn't in the ZIPs — it's written to `missing_media.csv` (see Step 7).
- **My Eyes Only** probably won't be exported at all — save these from the app.
  - Observed: on a second export *after* unlocking My Eyes Only in the app, the index entries were present but no media. Whether the actual My Eyes Only media ever exports wasn't seen or tested.
- A memory whose `missing_media.csv` row has a **`duplicate_save_of`** value — its action reads *"footage already in archive (see duplicate_save_of); verify once in the app"* — is occasionally a distinct memory rather than a true copy, so give it a glance in the app. (Step 7 covers reviewing the CSV.)

This tool doesn't hide gaps in either direction. Every indexed memory with no media file is written to `missing_media.csv`, and every media file in the ZIPs that the index doesn't mention is written to `unmatched_files.csv` — so nothing is silently dropped. Indexed media is copied automatically; copying the unlisted media too is covered in step 6. Review the reports and save anything missing from the app.

> [!TIP]
> It was observed that a second export, requested a few days later, included media the first one was missing. If your first download has a lot of missing media, it's worth requesting another export — or waiting a few days and downloading again. An export's contents can vary between requests, so a later one may list memories or include media the first didn't (and may also be missing things the first had). To bring in only the memories your first run flagged as missing, make a JSON with just those entries and point `--from-zips` at the second export's ZIPs.

## Processing your export (media bundled in the ZIPs)

Recent Snapchat exports put the actual media **inside** the ZIPs and leave the download links in `memories_history.json` empty — so instead of downloading, this tool reads the media straight out of your ZIPs and writes the timestamps, GPS, and caption overlays onto them.

### 1. Install prerequisites
- **uv** — manages Python and the dependencies for you
- **ffmpeg** — required to merge video caption overlays and write video metadata
- **exiftool** *(optional but recommended)* — needed for **video GPS** to show up in Google Photos (location + correct local time). Without it, photo GPS still works.

### 2. Get the code and install dependencies
```
git clone https://github.com/ToTheMax/Snapchat-All-Memories-Downloader.git
cd Snapchat-All-Memories-Downloader
uv sync
```

### 3. Find your `memories_history.json`
It's inside the first ZIP, under `json/memories_history.json`. Extract just that one file (any unzip tool works).

### 4. Organize your files
Put **all** your ZIPs together in a folder by themselves, and keep `memories_history.json` outside it:

```
snapchat-export/
├── memories_history.json        <- extracted from the first ZIP
└── zips/                        <- ALL your mydata~*.zip files, and nothing else
    ├── mydata~1234567.zip
    ├── mydata~1234567-2.zip
    ├── mydata~1234567-3.zip
    └── …
```

### 5. (Recommended) Run a quick test first
Before processing thousands of files, run a small test export first:
```
uv run python main.py snapchat-export/memories_history.json --from-zips snapchat-export/zips -o test --test --overlay with
```
This command exports a small sample of your memories covering **every metadata scenario** (photo/video, with/without GPS, captions, and other edge cases), plus **`TEST_EXPECTATIONS.txt`** listing the **expected metadata for each one**. Upload the `test` folder to your photo app and **cross-check each file against `TEST_EXPECTATIONS.txt`**. When it all matches, continue.

### 6. Process everything
```
uv run python main.py snapchat-export/memories_history.json --from-zips snapchat-export/zips -o downloads --overlay with
```
- `--from-zips` points at the **folder containing all your ZIPs**.
- `--overlay with` merges caption/sticker overlays into the media (needs ffmpeg). Use `--overlay none` to skip overlays.
- `--split N` *(optional)* deals the media into numbered subfolders (`batch_01/`, `batch_02/`, …) of N files each, so you can upload **one folder at a time** — handy if your photo app has a hard time with lots of files at once. Reports and any recovered/orphan files stay in the output root.
- `--import-unlisted` *(optional)* imports media that's in the ZIPs but not listed in the index, using each file's own timestamp (UTC, no GPS). Off by default and not needed for a normal run. Example: your index is incomplete but you have all the ZIPs and want every file anyway. It imports *all* unlisted media, so avoid it when your index is intentionally a small subset (e.g. a test run) — it would pull in your whole archive.

> [!NOTE]
> You'll see a burst of warnings scroll by at the start (and a recap at the end). **This is expected — the job still completes.** They flag things like memories whose media isn't in the export or overlays without a matching photo. It's worth reading them so you know what, if anything, needs a manual save — see step 7.

### 7. Review `missing_media.csv` (important — don't skip)
Snapchat's index sometimes lists memories whose media is **not in the export**. Every such entry is written to `missing_media.csv` in your output folder. Open it (Excel, Numbers, or any text editor) — each row has an `action` column telling you what to do:

- **`duplicate_save_of` is filled in** → the named file is very likely the same memory already in your output. Still recommended to confirm in the app, since a flagged duplicate is occasionally a distinct memory rather than a true copy — see [The export may not be 100% complete](#the-export-may-not-be-100-complete).
- **action says "CHECK IN APP" / "SAVE MANUALLY"** → the export left this one out. Open the Snapchat app at that date/time; if the memory is still there, **save it by hand** before deleting your account.

> [!WARNING]
> **My Eyes Only:** may be listed in the index without its media — save these from the app. See [The export may not be 100% complete](#the-export-may-not-be-100-complete).

### 8. Upload
Upload your output folder to Google Photos (or your photo app of choice). Captions are merged in, dates and GPS are embedded. See `TEST_EXPECTATIONS.txt` from step 5 for exactly how each type appears.

> [!TIP]
> Upload into a **new, separate album** first. If anything looks off (wrong dates, missing location), you can delete the album's photos and re-upload without touching the rest of your library.

## Downloading your Memories
- Clone or [Download](https://github.com/ToTheMax/Snapchat-All-Memories-Downloader/archive/refs/heads/main.zip) this Repository
- (Recommended) Copy the memories_history.json to the extracted or cloned folder
- Run the script:
    - Requirements: Python3.10+
    - Install the required packages: 
	```
	pip install -r requirements.txt
	```
    - Run the script: 
    ```
    python main.py memories_history.json
    ```


### Optional Arguments
```
usage: main.py [-h] [-o OUTPUT] [--ffmpeg-path FFMPEG_PATH] [-c CONCURRENT]
               [--overlay {none,with,both}]
               [--overlay-naming {single-folder,separate-folders}] [--no-exif]
               [--no-skip-existing] [--prefix PREFIX] [--copy-overlays]
               [--from-zips DIR] [--subset N] [--import-unlisted] [--test]
               [--split N]
               json_file

Download all your Snapchat memories

positional arguments:
  json_file             Path to memories_history.json file from Snapchat data export

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output directory for downloaded files (default: ./downloads)
  --ffmpeg-path FFMPEG_PATH
                        Path to ffmpeg executable (default: ffmpeg in PATH)
  -c, --concurrent CONCURRENT
                        Number of concurrent downloads (default: 40)
  --overlay {none,with,both}
                        Overlay handling: 'none'=no overlays, 'with'=only with overlays,
                        'both'=save both versions (default: none). Note: 'with'/'both' refer to
                        merging the separate overlay file when one exists; older memories may
                        have captions burned into the media itself and need no merging.
  --overlay-naming {single-folder,separate-folders}
                        How to organize overlaid vs non-overlaid files when --overlay=both
                        (default: separate-folders).
  --no-exif             Do not add metadata (faster, but loses location/timestamp info)
  --no-skip-existing    Re-download and overwrite existing files instead of skipping them
  --prefix PREFIX       Prefix to add to all downloaded filenames (e.g. 'SC_')
  --copy-overlays       Save a copy of overlay files to 'overlays' subfolder (requires --overlay=both)
  --from-zips DIR       Import media from bulk-export ZIPs in DIR instead of downloading.
                        Use when your export bundles the media and the JSON has empty URLs.
  --subset N            Process only N curated items across media-type/GPS/overlay buckets
                        (quick end-to-end test). Requires --from-zips.
  --import-unlisted     Also import media present in the ZIPs but missing from the JSON,
                        using each file's own timestamp (UTC, no GPS). Off by default so a
                        partial/filtered JSON doesn't pull in the whole archive. Requires --from-zips.
  --test                Export one of each scenario plus TEST_EXPECTATIONS.txt describing what
                        each should show in your photo app. Requires --from-zips.
  --split N             Write the media into numbered subfolders (batch_01/, batch_02/, ...) of
                        N files each, so you can upload one folder at a time. Requires --from-zips.
```

## Requires ffmpeg

The following features require ffmpeg to be installed:

- **Video overlay merging** - Compositing stickers, text, and filters onto videos
- **Video metadata** - Adding timestamps and GPS location to video files

If ffmpeg is not installed, you can still:
- Download all memories without overlays (`--overlay none`, the default)
- Download images with full metadata (EXIF tags including GPS and timestamps)
- Download videos, but metadata (creation time, GPS location) will not be applied

### Install ffmpeg
Download and install ffmpeg from [https://www.ffmpeg.org/download.html](https://www.ffmpeg.org/download.html)


## Downloading with Overlays
To download Snapchat memories with their overlays (stickers, text, filters), you'll need ffmpeg installed on your system.


### Download with overlays
Once ffmpeg is installed, you can download memories with overlays:

```bash
# Download only memories with overlays
python main.py memories_history.json --overlay with

# Download both overlayed and non-overlayed versions in separate folders
python main.py memories_history.json --overlay both

# Download both versions in a single folder with '_overlayed' suffix for overlaid files
python main.py memories_history.json --overlay both --overlay-naming single-folder
```


### Limitations
Works best on basic captions and location filters. Limited support for large/artistic fonts, blended text, and complex overlays.

### Examples

```bash
# Basic usage
python main.py memories_history.json --overlay both
```

## Troubleshooting
1. Make sure you get a fresh zip-file from Snapchat before running the script, links will expire over time
2. If you are missing the `memories_history.json` file, make sure you selected the right options in the export configuration
3. Still problems? Please open a new [issue](https://github.com/ToTheMax/Snapchat-All-Memories-Downloader/issues) 
