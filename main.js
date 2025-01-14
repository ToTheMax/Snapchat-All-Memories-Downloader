// Node.js built-in modules
import { existsSync, mkdirSync, createWriteStream, readFileSync } from "fs";
import fs from "fs";
import { request, get } from "https";
import path from "path";
import { exit } from "process";

// Third-party modules
import { Command } from "commander";
import { fileTypeFromBuffer } from 'file-type';
import moment from "moment";
import { exiftool } from "exiftool-vendored";

// Local modules
import Progress from "./progress.js";
import Queue from "./concurrency.js";

const { utc } = moment;

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
let completedDownloads = 0;

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

const totalDownloads = downloads.length;

var queue = new Queue(maxConcurrentDownloads);
var progress = new Progress(downloads.length, progressBarLength);
var failedDownloads = [];

function handleDownloadComplete(success, downloadInfo = null) {
  completedDownloads++;
  if (!success && downloadInfo) {
    failedDownloads.push(downloadInfo);
  }

  progress.downloadSucceeded(success);

  if (completedDownloads === totalDownloads) {
    exiftoolProcess.end().then(() => {
      const successCount = totalDownloads - failedDownloads.length;
      console.log(`\n✓ ${successCount} files successfully downloaded`);

      if (failedDownloads.length > 0) {
        fs.writeFileSync(
          "memories_failed.json",
          JSON.stringify({ "Saved Media": failedDownloads }, null, 2)
        );
        console.log(`✗ ${failedDownloads.length} files failed (see memories_failed.json)`);
        console.log(`Retry failed downloads: node main.js -f memories_failed.json`);
      }
      exit(0);
    });
  }
}

function main() {
  // Create download directory
  if (!existsSync(outputDir)) mkdirSync(outputDir);

  // Start downloads
  for (let i = 0; i < downloads.length; i++) {
    const downloadInfo = downloads[i];
    let [url, body] = downloadInfo["Download Link"].split("?", 2);
    const fileTime = utc(downloadInfo["Date"], "YYYY-MM-DD HH:mm:ss Z");
    let fileName = getFileName(downloadInfo, fileTime);

    // Parse "Location": "Latitude, Longitude: <lat>, <long>"
    let [lat, long] = downloadInfo["Location"].split(": ")[1].split(", ");

    // First get CDN download link
    queue
      .enqueue(() => getDownloadLink(url, body, fileName, fileTime))
      .then((result) => {
        progress.cdnLinkSucceeded(true);

        // Download the file
        queue
          .enqueue(() =>
            downloadMemory(result[0], result[1], result[2], lat, long, downloadInfo)
          )
          .then((success) => {
            handleDownloadComplete(success);
          })
          .catch((err) => {
            handleDownloadComplete(false, downloadInfo);
          });
      })
      .catch((err) => {
        progress.cdnLinkSucceeded(false);
        handleDownloadComplete(false, downloadInfo);
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

const downloadMemory = (downloadUrl, fileName, fileTime, lat = "", long = "", downloadInfo) =>
  new Promise((resolve, reject) => {
    // Check if there already exists a file with the same name
    if (existsSync(outputDir + "/" + fileName)) {
      resolve(true);
      return;
    }

    // Lambda function for downloading with retries
    const download = (maxRetries) => {
      var req = get(downloadUrl, async (res) => {
        if (res.statusCode == 200) {
          try {
            // Get the first chunk to detect file type
            const firstChunk = await new Promise((resolve) => {
              res.once('data', (chunk) => resolve(chunk));
            });

            // Detect file type and set path
            let filepath = path.join(outputDir, fileName);
            const fileType = await fileTypeFromBuffer(firstChunk);
            if (fileType) {
              filepath = path.join(outputDir, fileName + "." + fileType.ext);
            }

            // Create the file and write to it
            const file = createWriteStream(filepath);
            file.write(firstChunk);
            res.pipe(file);

            // Wait for file to be completely written
            await new Promise((resolve, reject) => {
              file.on('finish', async () => {
                file.close();

                try {
                  await exiftoolProcess.write(filepath, {
                    AllDates: fileTime.format("YYYY-MM-DDTHH:mm:ss"),
                    GPSLatitude: parseFloat(lat),
                    GPSLongitude: parseFloat(long),
                    GPSLatitudeRef: parseFloat(lat) > 0 ? "N" : "S",
                    GPSLongitudeRef: parseFloat(long) > 0 ? "E" : "W"
                  }, ['-overwrite_original']);

                  // Update file system timestamps
                  const timestamp = fileTime.valueOf() / 1000;
                  fs.utimesSync(filepath, timestamp, timestamp);
                  resolve();
                } catch (error) {
                  reject(error);
                }
              });

              file.on('error', (error) => reject(error));
            });

            resolve(true);
          } catch (error) {
            if (maxRetries > 0) {
              download(maxRetries - 1);
            } else {
              reject(error);
            }
          }
        } else {
          if (maxRetries > 0) {
            download(maxRetries - 1);
          } else {
            reject(new Error(`HTTP ${res.statusCode}: ${res.statusMessage}`));
          }
        }
      });

      req.on("error", function (error) {
        req.destroy();
        if (maxRetries > 0) {
          download(maxRetries - 1);
        } else {
          reject(error);
        }
      });

      req.end();
    };
    // Download with max retries of 3
    download(3);
  });

main();
