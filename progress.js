module.exports = class Progress {

    constructor(total, progressBarLength) {
        this.total = total;
        this.progressBarLength = progressBarLength;
        this.cdnLinks = { success: 0, fails: 0 }
        this.downloads = { success: 0, fails: 0 }
        this.printProgress(true);
    }

    cdnLinkSucceeded(didSucceed) {
        didSucceed ? this.cdnLinks.success++ : this.cdnLinks.fails++;
        this.printProgress();
    }

    downloadSucceeded(didSucceed) {
        didSucceed ? this.downloads.success++ : this.downloads.fails++;
        this.printProgress();
    }

    printProgress(firstRun) {

        if (!firstRun)
            process.stdout.moveCursor(0, -2);

        process.stdout.clearLine();
        process.stdout.cursorTo(0);

        this.printBar("CDN-LINKS: ", this.cdnLinks.success, this.cdnLinks.fails);
        this.printBar("DOWNLOADS: ", this.downloads.success, this.downloads.fails);
    }

    printBar(name, success, fails) {

        process.stdout.write(name)

        var progress = (success + fails) / this.total;

        var bar = Math.floor(this.progressBarLength * progress);
        process.stdout.write("[")
        process.stdout.write("=".repeat(bar) + "-".repeat(this.progressBarLength - bar))
        process.stdout.write("] ")

        //process.stdout.write((progress * 100).toFixed(2) + "% ")
        process.stdout.write("" + success + "/" + this.total)
        process.stdout.write("\tFailed: " + fails)
        process.stdout.write("\n")
    }
}


