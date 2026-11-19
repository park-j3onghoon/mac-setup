export class Admission {
  constructor(activeLimit = 4, queueLimit = 32) {
    this.activeLimit = activeLimit;
    this.queueLimit = queueLimit;
    this.active = 0;
    this.queue = [];
  }
  async run(action, signal) {
    signal?.throwIfAborted();
    if (this.active >= this.activeLimit) {
      if (this.queue.length >= this.queueLimit) throw new Error('Shared browser is busy; retry after existing work finishes.');
      await new Promise((resolve, reject) => {
        const entry = {resolve, reject, signal};
        entry.abort = () => {
          const index = this.queue.indexOf(entry);
          if (index !== -1) this.queue.splice(index, 1);
          reject(signal.reason);
        };
        signal?.addEventListener('abort', entry.abort, {once: true});
        this.queue.push(entry);
      });
    } else this.active++;
    try {
      signal?.throwIfAborted();
      return await action();
    } finally {
      const next = this.queue.shift();
      if (next) {
        next.signal?.removeEventListener('abort', next.abort);
        next.resolve();
      } else this.active--;
    }
  }
}
