
[![Node](http://img.shields.io/badge/Node-%E2%89%A5%2010-brightgreen.svg)](https://nodejs.org/en/download/releases/)
[![Donate](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.me/mraams)

# Snapchat-All-Memories-Downloader
This script will download each memory in bulk so you don't have to click the download links one by one.

## Requirements
1. Node.js version 10 or higher (https://nodejs.org/)  

## How to run
1. Download your Snapchat data: https://support.snapchat.com/en-US/a/download-my-data
2. Extract the zip-file
3. Place all the scripts in this folder OR set the `-f` flag pointing to the `memories_history.json` file
4. Run the script: `node main.js`

## Optional Arguments
```
node main.js 
    -c number of concurrent connections
    -f filepath to memories_history.json
    
    Example: node main.js -c 50 -f ./json/memories_history.json
```

## Example
![Alt Text](https://i.imgur.com/QVvh3I4.gif)

## Trouble Shooting
1. Make sure you get a fresh zip-file before running the script, links will expire over time
2. Still problems? please make an [issue](https://github.com/ToTheMax/Snapchat-All-Memories-Downloader/issues)
