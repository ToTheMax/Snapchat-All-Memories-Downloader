# Snapchat-All-Memories-Downloader
This script will download all your Snapchat memories in bulk, **including the timestamp and geolocation**.

![demo](./demo.gif)


## Getting your Data
- Login to Snapchat and request your data: https://accounts.snapchat.com/accounts/downloadmydata
- Select the `Export your Memories` and `Export JSON Files` option and continue
- Date Range: Select "All Time" to get all your memories
- Important: If you have many memories, you will receive multiple ZIP files. Only download the first ZIP file (usually named something like mydata~XXXXX.zip)
- Inside this ZIP, you will find a json/ folder containing memories_history.json. This is the only file you need for this tool to work

![export configuration](https://github.com/user-attachments/assets/dfcdb6a0-e554-46e8-bdba-77fe41c88a03)

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
    python main.py
    ```


### Optional Arguments
```
usage: main.py [-h] [-o OUTPUT] [-c CONCURRENT] [--no-exif] [--no-skip-existing] 
               [--overlay {none,with,both}] [--overlay-naming {single-folder,separate-folders}]
               [--ffmpeg-path FFMPEG_PATH] [--prefix PREFIX] [--ocr-metadata] [--copy-overlays]
               [json_file]

Download Snapchat memories from data export

positional arguments:
  json_file             Path to memories_history.json (default: json/memories_history.json)

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output directory (default: ./downloads)
  -c, --concurrent CONCURRENT
                        Max concurrent downloads (default: 40)
  --no-exif             Disable metadata writing (no location, time or other metadata)
  --no-skip-existing    Re-download existing files
  --overlay {none,with,both}
                        Overlay handling mode:
                          - none: Skip overlays entirely (fast, default)
                          - with: Download only files with overlays
                          - both: Download both overlayed and non-overlayed versions (organization controlled by --overlay-naming)
  --overlay-naming {single-folder,separate-folders}
                        When using --overlay both:
                          - separate-folders: Split into 'with_overlays' and 'without_overlays' folders (default)
                          - single-folder: Keep all in one folder, overlayed files get '_overlayed' suffix
  --ffmpeg-path FFMPEG_PATH
                        Path to ffmpeg executable (default: ffmpeg in system PATH)
                        Required only when using --overlay with or --overlay both for video overlay merging
  --prefix PREFIX       Prefix to add to all downloaded filenames (e.g., 'SC_' creates 'SC_filename.ext')
  --copy-overlays       Save a copy of overlay files to 'overlays' subfolder
                        Requires: --overlay both
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
python main.py --overlay with

# Download both overlayed and non-overlayed versions in separate folders
python main.py --overlay both

# Download both versions in a single folder with '_overlayed' suffix for overlaid files
python main.py --overlay both --overlay-naming single-folder
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
