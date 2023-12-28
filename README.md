# Snapchat-All-Memories-Downloader
This script will download all your Snapchat memories in bulk, **including the timestamp**.

![Example](https://i.imgur.com/QVvh3I4.gif)


## Getting your Data
- Login to Snapchat: https://accounts.snapchat.com/
- Request your data: https://accounts.snapchat.com/accounts/downloadmydata
- Select the options shown in the image

> ❗ If you don't care about timestamps, you don't need this tool and can just enable the top option ❗
<img src="https://github.com/ToTheMax/Snapchat-All-Memories-Downloader/assets/21971014/242117ef-aad0-45ec-85a7-dada98c46762" width="600">


## Downloading your Memories
- Clone or [Download](https://github.com/ToTheMax/Snapchat-All-Memories-Downloader/archive/refs/heads/master.zip) this Repository
- Extract the zip-file received from Snapchat in the same folder
- Run the script:

    ### OPTION 1: Run locally
    - Requirements: Node.js 10+
    - Install the required modules: `npm install`
    - Run the script: 
    ```
    node main.js
    ```

    ### OPTION 2: Run with Docker
    - Requirements: Docker
    - Build the docker container: `docker build -t snapchat-all-memories-downloader .`
    - Run the script
    ```bash
    # Mounts a Downloads folder and memories_history.json with current directory
    docker run -it --rm \
        -v $PWD/Downloads/:/app/Downloads/ \
        -v $PWD/memories_history.json:/app/json/memories_history.json \
        snapchat-all-memories-downloader -o ./Downloads/
    ```


    ### Optional Arguments
    ```
    Usage: main [options]

    A script to download Snapchat Memories

    Example:
      node main.js -c 50 -f ./json/memories_history.json -o Downloads

    Options:
      -c <number>     Number of concurrent downloads (default: 30)
      -f <path>       Filepath to memories_history.json (default: "./json/memories_history.json")
      -o <directory>  Download directory (default: "Downloads")
      -h, --help      display help for command
    ```


## Trouble Shooting
1. Make sure you get a fresh zip-file before running the script, links will expire over time
2. `Syntax Compilation Error` -> please have a look at [this](https://github.com/ToTheMax/Snapchat-All-Memories-Downloader/issues/4#issuecomment-664035581) issue
3. `node-gyp` errors when running `npm install` on Windows -> install [this](https://github.com/nodejs/node-gyp#on-windows)
4. Still problems? please make a new [issue](https://github.com/ToTheiMax/Snapchat-All-Memories-Downloader/issues) 


<br>
<a href="https://www.buymeacoffee.com/tothemax" target="_blank">
<img src="https://github.com/appcraftstudio/buymeacoffee/raw/master/Images/snapshot-bmc-button.png" width="300">
</a>

