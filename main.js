// IMPORTS
import { request, get } from "https";
import { existsSync, mkdirSync, createWriteStream } from "fs";
import Queue from "./concurrency.js";
import Progress from "./progress.js";
import moment from "moment";
const { utc } = moment;
import { utimes } from "utimes";
import { Command } from "commander";
import { exit } from "process";
import { exiftool } from "exiftool-vendored";
import { readFileSync } from "fs";
import path from "path";

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
  .option("-o <directory>", "Download directory", "Downloads")

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
let exiftoolProcess = exiftool;


// INIT
let downloads = [];
try {
  downloads = JSON.parse(readFileSync(jsonFile))["Saved Media"];
} catch (e) {
  console.log(e);
  console.log(
    `Couldn't find the file ${jsonFile}, did you provide the right filepath?`
  );
  exit();
}

var queue = new Queue(maxConcurrentDownloads);
var progress = new Progress(downloads.length, progressBarLength);

function main() {
  // Create download directory
  if (!existsSync(outputDir)) mkdirSync(outputDir);

  // Start downloads
  for (let i = 0; i < downloads.length; i++) {
    let [url, body] = downloads[i]["Download Link"].split("?", 2);
    const fileTime = utc(downloads[i]["Date"], "YYYY-MM-DD HH:mm:ss Z");
    let fileName = getFileName(downloads[i], fileTime);

    // Parse "Location": "Latitude, Longitude: <lat>, <long>"
    let [lat, long] = downloads[i]["Location"].split(": ")[1].split(", ");

    // First get CDN download link
    queue
      .enqueue(() => getDownloadLink(url, body, fileName, fileTime))
      .then((result) => {
        progress.cdnLinkSucceeded(true);

        // Download the file
        queue
          .enqueue(() =>
            downloadMemory(result[0], result[1], result[2], lat, long)
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

  // Check if there already exists a file with the same name/timestamp
  if (names.has(fileName)) {
    var duplicates = 1;
    while (names.has(fileName + ` (${duplicates})`)) {
      duplicates++;
    }
    fileName += ` (${duplicates})`;
  }
  names.add(fileName);

  if (
    download["Media Type"].toLowerCase() == "image" ||
    download["Media Type"].toLowerCase() == "photo"
  )
    fileName += ".jpg";
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
      var req = request(options, (res) => {
        let data = "";
        res.on("data", (chunk) => {
          data += chunk;
        });
        res.on("end", function () {
          if (res.statusCode == 200) {
            resolve([data, fileName, fileTime]);
          } else {
            if (maxRetries > 0) {
              getLink(maxRetries - 1);
            } else {
              reject("status error");
            }
          }
        });
      });
      req.on("error", function () {
        req.destroy();
        if (maxRetries > 0) {
          getLink(maxRetries - 1);
        } else {
          reject("request error");
        }
      });
      req.write(body);
      req.end();
    };
    // Get Link with max retries of 3
    getLink(3);
  });

const downloadMemory = (downloadUrl, fileName, fileTime, lat = "", long = "") =>
  new Promise((resolve, reject) => {
    // Check if there already exists a file with the same name
    if (existsSync(outputDir + "/" + fileName)) {
      resolve(true);
    }
    else {
      // Lambda function for downloading with retries
      const download = (maxRetries) => {
        var req = get(downloadUrl, (res) => {
          if (res.statusCode == 200) {
            // Create the file and write to it
            const filepath = path.join(outputDir, fileName);
            var file = createWriteStream(filepath);
            res.pipe(file);

            res.on("end", async () => {
              file.close();

              // Update the file location metadata
              await exiftoolProcess.write(filepath, {
                AllDates: fileTime.format("YYYY-MM-DDTHH:mm:ss"),
                GPSLatitude: parseFloat(lat),
                GPSLongitude: parseFloat(long),
                GPSLatitudeRef: parseFloat(lat) > 0 ? "N" : "S",
                GPSLongitudeRef: parseFloat(long) > 0 ? "E" : "W"
              }, ['-overwrite_original']);

              // Update system file timestamps
              await utimes(file.path, {
                btime: fileTime.valueOf(), // birthtime (Windows & Mac)
                mtime: fileTime.valueOf(), // modified time (Windows, Mac, Linux)
                atime: fileTime.valueOf()  // access time (Linux)
              });

              resolve(true);
            });
          } else {
            console.log("download error", res.statusCode, res.statusMessage);
            if (maxRetries > 0) {
              download(maxRetries - 1);
            } else {
              reject("status error");
            }
          }
        });

        req.on("error", function () {
          console.log("request error");
          req.destroy();
          if (maxRetries > 0) {
            download(maxRetries - 1);
          } else {
            reject("request error");
          }
        });

        req.end();
      };
      // Download with max retries of 3
      download(3);
    }
  });

main();
