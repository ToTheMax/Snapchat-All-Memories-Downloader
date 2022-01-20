// IMPORTS
const https = require("https");
const fs = require("fs");
const Queue = require("./concurrency.js");
const Progress = require("./progress.js");
const moment = require("moment");
const utimes = require("utimes").utimes;
const { Command } = require("commander");
const { exit } = require("process");

// PARSE ARGUMENTS
const program = new Command();
program
    .description(
        "A script to download Snapchat Memories\n\nExample:\n  node main.js -c 50 -f ./json/memories_history.json -o Downloads"
    )
    .option("-c <number>", "Number of concurrent downloads", 30)
    .option(
        "-f <path>",
        "Filepath to memories_history.json",
        "./json/memories_history.json"
    )
    .option("-o <directory>", "Download directory", "Downloads");
program.parse();
const options = program.opts();

// CONFIG
const outputDir = options.o;
const maxConcurrentDownloads = options.c;
const progressBarLength = 20;
const jsonFile =
    !options.f.startsWith("/") && !options.f.startsWith("./")
        ? "./" + options.f
        : options.f;
var names = new Set();

// INIT
try {
    var downloads = require(jsonFile)["Saved Media"];
} catch (e) {
    if (e.code === "MODULE_NOT_FOUND") {
        console.log(
            `Couldn't find the file ${jsonFile}, did you provide the right filepath?`
        );
        exit();
    }
    throw e;
}
var queue = new Queue(maxConcurrentDownloads);
var progress = new Progress(downloads.length, progressBarLength);

function main() {
    // Create download directory
    if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir);

    // Start downloads
    for (let i = 0; i < downloads.length; i++) {
        let [url, body] = downloads[i]["Download Link"].split("?", 2);
        const fileTime = moment.utc(
            downloads[i]["Date"],
            "YYYY-MM-DD HH:mm:ss Z"
        );
        let fileName = getFileName(downloads[i], fileTime);

        // First get CDN download link
        queue
            .enqueue(() => getDownloadLink(url, body, fileName, fileTime))
            .then((result) => {
                progress.cdnLinkSucceeded(true);

                // Download the file
                queue
                    .enqueue(() =>
                        downloadMemory(result[0], result[1], result[2])
                    )
                    .then((success) => {
                        progress.downloadSucceeded(true);
                    })
                    .catch((err) => {
                        progress.downloadSucceeded(false);
                    });
            })
            .catch((err) => {
                progress.cdnLinkSucceeded(false);
            });
    }
}

function getFileName(download, fileTime) {
    var fileName = fileTime.format("YYYY-MM-DD_HH-mm-ss");

    if (download["Media Type"].toLowerCase() == "image" || download["Media Type"].toLowerCase() == "photo") fileName += ".jpg";
    else if (download["Media Type"].toLowerCase() == "video") fileName += ".mp4";

    return fileName;
}

const getDownloadLink = (url, body, fileName, fileTime) =>
    new Promise((resolve, reject) => {
        var parsedUrl = new URL(url);
        const options = {
            hostname: parsedUrl.hostname,
            path: parsedUrl.pathname,
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
            },
        };
        
        // Lambda function for getting link with retries
        const getLink = (maxRetries) => {
            var req = https.request(options, (res) => {
                data = "";
                res.on("data", (chunk) => {
                    data += chunk;
                });
                res.on("end", function () {
                    if (res.statusCode == 200) {
                        resolve([data, fileName, fileTime]);
                    } else {
                        if(maxRetries > 0) {
                            getLink(maxRetries - 1);
                        } else {
                            reject("status error");
                        }
                    }
                });
            });
            req.on("error", function () {
                req.destroy();
                if(maxRetries > 0) {
                    getLink(maxRetries - 1);
                } else {
                    reject("request error");
                }
            });
            req.write(body);
            req.end();
        }
        // Get Link with max retries of 3
        getLink(3);
    });

const downloadMemory = (downloadUrl, fileName, fileTime) =>
    new Promise((resolve, reject) => {
        // Check if there already exists a file with the same name/timestamp
        if (fs.existsSync(outputDir + "/" + fileName) || names.has(fileName)) {
            duplicates = 1;
            while (true) {
                var extensionPos = fileName.lastIndexOf(".");
                var newFilename =
                    fileName.substring(0, extensionPos) +
                    " (" +
                    duplicates +
                    ")" +
                    fileName.substring(extensionPos, fileName.length);
                if (fs.existsSync(outputDir + "/" + newFilename) || names.has(newFilename)) duplicates++;
                else {
                    fileName = newFilename;
                    break;
                }
            }
        }
        names.add(fileName);

        // Lambda function for downloading with retries
        const download = (maxRetries) => {
            var req = https.get(downloadUrl, function (res) {
                if (res.statusCode == 200) {
                    // Create the file and write to it
                    var file = fs.createWriteStream(outputDir + "/" + fileName);
                    res.pipe(file);
                    res.on("end", function () {
                        file.close();
                        // Update the file creation date
                        utimes(file.path, {
                            btime: fileTime.valueOf(), // birthtime (Windows & Mac)
                            mtime: fileTime.valueOf(), // modified time (Windows, Mac, Linux)
                        });
                        resolve(true);
                    });
                } else {
                    if(maxRetries > 0) {
                        download(maxRetries - 1);
                    } else {
                        reject("status error");
                    }
                }
            });
            req.on("error", function () {
                req.destroy();
                if(maxRetries > 0) {
                    download(maxRetries - 1);
                } else {
                    reject("request error");
                }
            });
            req.end();
        }
        // Download with max retries of 3
        download(3);
    });

main();
