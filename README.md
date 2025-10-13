# Snapchat All Memories Downloader

This script allows you to **download all your Snapchat memories in bulk**, including **timestamps and geolocation metadata**.  

![demo](./demo.gif)

---

## 🗂️ Getting Your Data

1. Log in to your Snapchat account:  
   🔗 [https://accounts.snapchat.com/](https://accounts.snapchat.com/)

2. Request your data export:  
   🔗 [https://accounts.snapchat.com/accounts/downloadmydata](https://accounts.snapchat.com/accounts/downloadmydata)

3. Choose the **"Export JSON Files"** option and continue.

> ⚠️ Make sure to wait until Snapchat notifies you by email that your data export is ready.

![export configuration](https://github.com/user-attachments/assets/a037e6a0-e75b-42be-92a6-c5162f103891)

---

## 💾 Downloading Your Memories

1. **Download or clone this repository**  
   - Clone with Git:  
     ```bash
     git clone https://github.com/ToTheMax/Snapchat-All-Memories-Downloader.git
     ```
   - Or download the ZIP:  
     [📦 Download Repository](https://github.com/ToTheMax/Snapchat-All-Memories-Downloader/archive/refs/heads/main.zip)

2. **Extract your Snapchat data**  
   - You’ll receive a ZIP file from Snapchat (usually named `mydata~.zip`).  
   - Extract both **your Snapchat ZIP** and the **repository ZIP** into separate folders using [7-Zip](https://www.7-zip.org/) or any other extraction tool.

3. **Move the script files**  
   - Copy all files from the `Snapchat-All-Memories-Downloader-master` folder  
     (you should see files like `main.py`, `requirements.txt`, etc.)  
     into your **mydata** folder.

4. **Open a terminal inside the `mydata` folder**  
   - Hold **Shift** and **Right-click** inside the folder  
   - Select **“Open PowerShell window here”**
- or
   - In the address bar, type:
     ```bash
     cmd
     ```

---

## 🚀 Running the Script

### Requirements
- **Python 3** must be installed on your system. ➡️ [Download here](https://www.python.org/downloads/)

### Installation
Install the required Python packages:
```bash
pip install -r requirements.txt
````

### Run the Script

Once dependencies are installed, run:

```bash
python main.py
```

---

## ⚙️ Optional Arguments

You can customize how the script runs by using command-line arguments:

```
usage: main.py [-h] [-o OUTPUT] [-c CONCURRENT] [--no-exif] [--no-skip-existing] json_file

Download Snapchat memories from data export

positional arguments:
  json_file             Path to memories_history.json

options:
  -h, --help            Show this help message and exit
  -o, --output OUTPUT   Output directory
  -c, --concurrent CONCURRENT
                        Max concurrent downloads
  --no-exif             Disable EXIF metadata
  --no-skip-existing    Re-download existing files
```

---

## 🧩 Troubleshooting

1. **Download links expired?**
   → Request a new Snapchat data export before running the script again.

2. **Missing `memories_history.json` file?**
   → Ensure you selected **“Export JSON Files”** in the Snapchat export settings.

3. **Command not recognized?**
   → Verify that Python and pip are correctly installed by running:

   ```bash
   python --version
   pip --version
   ```

4. Still having issues?
   → Open a new issue here: [Report a problem](https://github.com/ToTheMax/Snapchat-All-Memories-Downloader/issues)

---

## ✅ Done!

Once everything is set up, the script will automatically start downloading your Snapchat memories, complete with metadata.
Make sure the folder structure stays intact and that Python 3 is correctly installed.

---

📘 *Created and maintained with ❤️ by [ToTheMax](https://github.com/ToTheMax)*

---
