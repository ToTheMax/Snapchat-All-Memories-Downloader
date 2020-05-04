# Snapchat-All-Memories-Downloader
This script will download each memory in bulk so you don't have to click the download links one by one.

## Requirements
1. Node.js version 10 or higher (https://nodejs.org/)  

## How to run
1. Download your Snapchat data: https://support.snapchat.com/en-US/a/download-my-data
2. Extract the zip-file
3. Place `main.js` in the folder OR change the config variables
4. Run the script: `node main.js`

# Optional Arguments
<pre>
node main.js 
    -c <number of concurrent connections>
    -f <filepath to memories_history.json>
<pre>
