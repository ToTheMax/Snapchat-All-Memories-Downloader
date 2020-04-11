// IMPORTS
const https = require('https');
const fs = require('fs');

// CONFIG
const jsonFile = "./json/memories_history.json";
const dir = "Downloads3";
const progressBarLength = 25

// INIT
var counter = 0;
var retries = 0;

downloads = require(jsonFile)["Saved Media"];
if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir);
}

function main() {


    for (var i = 0; i < downloads.length; i++) {

        var link = downloads[i]["Download Link"];
        var [url, body] = link.split('?', 2)

        var [date, time, tz] = downloads[i]["Date"].split(' ', 3);
        time = time.split(':').join('.'); // Windows doesn't like ":" in filename

        var filename = date + "_" + time;

        if (downloads[i]["Media Type"] == "PHOTO")
            filename += ".jpg";
        else if (downloads[i]["Media Type"] == "VIDEO")
            filename += ".mp4";

        downloadMemory(url, body, filename);
    }
}

function downloadMemory(url, body, filename) {

    // First we need to get CDN download url
    getDownloadLink(url, body, filename, function (downloadUrl) {

        // Create the file and write to it
        var file = fs.createWriteStream(dir + "/" + filename);

        const request = https.get(downloadUrl, function (res) {
            res.pipe(file);
            res.on("error", function () {
                downloadMemory(url, body, filename)
                retries++;
            })
            res.on("end", function () {
                file.close();
                counter++;
                updateProgress();
            });
        });
    });
}

function getDownloadLink(url, body, filename, callback) {

    var parsedUrl = new URL(url);

    const options = {
        hostname: parsedUrl.hostname,
        path: parsedUrl.pathname,
        method: "POST",
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    };

    var req = https.request(options, (res) => {

        data = "";

        res.on("data", (chunk) => {
            data += chunk;
        });
        res.on("error", function () {
            downloadMemory(url, body, filename)
            retries++;
        })
        res.on("end", function () {
            if (res.statusCode == 200) {
                callback(data);
            }
            else {
                downloadMemory(url, body, filename)
                retries++;
            }
        });
    });
    req.write(body);
    req.end();
}

function updateProgress() {

    process.stdout.clearLine();
    process.stdout.cursorTo(0);

    var progress = counter / downloads.length;

    // Print progressbar
    var bar = Math.floor(progressBarLength * progress);
    process.stdout.write("[")
    process.stdout.write("=".repeat(bar) + "-".repeat(progressBarLength - bar))
    process.stdout.write("] ")

    // Print percentage
    process.stdout.write((progress * 100).toFixed(2) + "% ")

    // Print stats
    process.stdout.write("| DONE: " + counter + "/" + downloads.length)
    process.stdout.write(" | RETRIES: " + retries);

    if (counter == downloads.length)
        console.log("\nDone!");
}

main();