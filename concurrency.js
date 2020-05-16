module.exports = class Queue {

    constructor(maxPendingPromises) {
        this.queue = [];
        this.pendingPromises = 0;
        this.maxPendingPromises = maxPendingPromises;
    }

    enqueue(promise) {
        return new Promise((resolve, reject) => {
            this.queue.push({
                promise,
                resolve,
                reject,
            });
            this.dequeue();
        });
    }

    dequeue() {
        if (this.pendingPromises >= this.maxPendingPromises) {
            return false;
        }
        const item = this.queue.shift();
        if (!item) {
            return false;
        }
        try {
            this.pendingPromises++;
            item.promise()
                .then((value) => {
                    this.pendingPromises--;
                    item.resolve(value);
                    this.dequeue();
                })
                .catch(err => {
                    this.pendingPromises--;
                    item.reject(err);
                    this.dequeue();
                })
        } catch (err) {
            this.pendingPromises--;
            item.reject(err);
            this.dequeue();
        }
        return true;
    }
}