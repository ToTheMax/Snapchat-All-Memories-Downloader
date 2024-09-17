import fs from 'fs';

export default class Progress {
    constructor(total, progressBarLength, verbose) {
        this.total = total;
        this.verbose = verbose;
        this.progressBarLength = progressBarLength;
        this.cdnLinks = { success: 0, fails: 0 };
        this.downloads = { success: 0, fails: 0 };
        this.printProgress(true);
        let progressFile = './progress.json';
        let logfile = './progress.txt';
        if(verbose) {
            let counter = 1;
            while (fs.existsSync(progressFile)) {
                progressFile = `./progress${counter}.json`;
                counter++;
            }
            fs.writeFileSync(progressFile, JSON.stringify(this, null, 2));
            let logCounter = 1;
            while (fs.existsSync(logfile)) {
                logfile = `./progress${logCounter}.txt`;
                logCounter++;
            }
        }
        this.logFile = logfile;
        this.processFile = progressFile;
    }

    cdnLinkSucceeded(didSucceed, url) {
        if(this.verbose){
            if (didSucceed) {
                const progressData = JSON.parse(fs.readFileSync(this.processFile));
                if (!progressData.cdnLinks.CDNSuccessUrls) {
                    progressData.cdnLinks.CDNSuccessUrls = [];
                }
                progressData.cdnLinks.CDNSuccessUrls.push(url);
                progressData.cdnLinks.success++;
                fs.writeFileSync(this.processFile, JSON.stringify(progressData, null, 2));
    
            } else {
                const progressData = JSON.parse(fs.readFileSync(this.processFile));
                if (!progressData.cdnLinks.CDNFailedUrls) {
                    progressData.cdnLinks.CDNFailedUrls = [];
                }
                progressData.cdnLinks.CDNFailedUrls.push(url);
                progressData.cdnLinks.fails++;
                fs.writeFileSync(this.processFile, JSON.stringify(progressData, null, 2));
            }
        }
        didSucceed ? this.cdnLinks.success++ : this.cdnLinks.fails++;
        this.printProgress();
    }

    downloadSucceeded(didSucceed, url) {
        if(this.verbose){
            if (didSucceed) {
                const progressData = JSON.parse(fs.readFileSync(this.processFile));
                if (!progressData.downloads.downloadSuccessUrls) {
                    progressData.downloads.downloadSuccessUrls = [];
                }
                progressData.downloads.downloadSuccessUrls.push(url);
                progressData.downloads.success++;
                fs.writeFileSync(this.processFile, JSON.stringify(progressData, null, 2));
            } else {
                const progressData = JSON.parse(fs.readFileSync(this.processFile));
                if (!progressData.downloads.downloadFailedUrls) {
                    progressData.downloads.downloadFailedUrls = [];
                }
                progressData.downloads.downloadFailedUrls.push(url);
                progressData.downloads.fails++;
                fs.writeFileSync(this.processFile, JSON.stringify(progressData, null, 2));
            }
        }
        didSucceed ? this.downloads.success++ : this.downloads.fails++;
        this.printProgress();
    }

    logError(message) {
        const time = new Date().toISOString();
        const logMessage = `${time}: ${message}\n`;
        fs.appendFileSync(this.logFile, logMessage);        
    }

    printProgress(firstRun) {
        if (!firstRun) process.stdout.moveCursor(0, -2);

        process.stdout.clearLine();
        process.stdout.cursorTo(0);

        this.printBar(
            "CDN-LINKS: ",
            this.cdnLinks.success,
            this.cdnLinks.fails
        );
        this.printBar(
            "DOWNLOADS: ",
            this.downloads.success,
            this.downloads.fails
        );
    }

    printBar(name, success, fails) {
        process.stdout.write(name);

        var progress = (success + fails) / this.total;

        var bar = Math.floor(this.progressBarLength * progress);
        process.stdout.write("[");
        process.stdout.write(
            "=".repeat(bar) + "-".repeat(this.progressBarLength - bar)
        );
        process.stdout.write("] ");

        //process.stdout.write((progress * 100).toFixed(2) + "% ")
        process.stdout.write("" + success + "/" + this.total);
        process.stdout.write("\tFailed: " + fails);
        process.stdout.write("\n");
    }
};
