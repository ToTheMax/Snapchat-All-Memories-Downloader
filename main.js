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
    .description("A script to download Snapchat Memories\n\nExample:\n  node main.js -c 50 -f ./json/memories_history.json -o Downloads")
    .option("-c <number>", "Number of concurrent downloads", 30)
    .option("-f <path>", "Filepath to memories_history.json", "./json/memories_history.json")
    .option("-o <directory>", "Download directory", "Downloads");
program.parse();
const options = program.opts();

// CONFIG
const outputDir = options.o;
const maxConcurrentDownloads = options.c;
const jsonFile = (!options.f.startsWith("/") && !options.f.startsWith("./")) ? "./" + options.f : options.f;
const progressBarLength = 20;

// INIT
try {
    var downloads = require(jsonFile)["Saved Media"];
} catch (e) {
    if (e.code === 'MODULE_NOT_FOUND') {
        console.log("Couldn't find the file " + jsonFile + ", did you provide the right filepath?");
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

        let [url, body] = downloads[i]["Download Link"].split('?', 2);
        const fileTime = moment.utc(downloads[i]["Date"], "YYYY-MM-DD HH:mm:ss Z")
        let fileName = getFileName(downloads[i], fileTime);

        // First get CDN download link
        queue.enqueue(() => getDownloadLink(url, body, fileName, fileTime))
            .then((result) => {
                progress.cdnLinkSucceeded(true);

                // Download the file
                queue.enqueue(() => downloadMemory(result[0], result[1], result[2]))
                    .then((success) => {
                        progress.downloadSucceeded(true);
                    })
                    .catch((err) => {
                        progress.downloadSucceeded(false);
                    })
            })
            .catch((err) => {
                progress.cdnLinkSucceeded(false);
            })
    }
}

function getFileName(download, fileTime) {
    var filename = fileTime.format("YYYY-MM-DD_HH-mm-ss")

    if (download["Media Type"] == "PHOTO")
        filename += ".jpg";
    else if (download["Media Type"] == "VIDEO")
        filename += ".mp4";

    return filename
}

const getDownloadLink = (url, body, filename, fileTime) => new Promise(resolve => {
    var parsedUrl = new URL(url);
    const options = {
        hostname: parsedUrl.hostname,
        path: parsedUrl.pathname,
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
        },
    };

    var req = https.request(options, (res) => {

        data = "";
        res.on("data", (chunk) => {
            data += chunk;
        });
        res.on("error", function () {
            reject("request error");
        })
        res.on("end", function () {
            if (res.statusCode == 200) {
                resolve([data, filename, fileTime]);
            }
            else {
                reject("status error");
            }
        });
    });
    req.write(body);
    req.end();
});


const downloadMemory = (downloadUrl, filename, fileTime) => new Promise(resolve => {

    // Check if there already exists a file with the same name/timestamp
    if (fs.existsSync(outputDir + "/" + filename)) {
        duplicates = 1;
        while (true) {
            var extensionPos = filename.lastIndexOf('.');
            var newFilename = filename.substring(0, extensionPos) + " (" + duplicates + ")" + filename.substring(extensionPos, filename.length);
            if (fs.existsSync(outputDir + "/" + newFilename))
                duplicates++;
            else {
                filename = newFilename;
                break;
            }
        }
    }

    // Create the file and write to it
    var file = fs.createWriteStream(outputDir + "/" + filename);

    https.get(downloadUrl, function (res) {
        res.pipe(file);
        res.on("error", function () {
            reject("request error");
        })
        res.on("end", function () {
            file.close();
            if (res.statusCode == 200) {
                // Update the file creation date
                utimes(file.path, {
                    btime: fileTime.valueOf(), // birthtime (Windows & Mac)
                    mtime: fileTime.valueOf() // modified time (Windows, Mac, Linux)
                }).then(() => {
                    resolve(true)
                }).catch(err => {
                    reject("failed to set file creation date:", err)
                })
            }
            else {
                reject("status error");
            }
        });
    });
});

main();


// Don"t look at this
process.on("uncaughtException", function (err) {
    if (err.code == "ECONNRESET")
        progress.downloadSucceeded(false);
    else{
        console.error(err, 'Uncaught Exception thrown');
        process.exit(1);
    }
});
