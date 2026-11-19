exports.start = function (server, onClose, interval = 15000, timeout = 30000) {
  let closed = false, next, deadline;
  onClose(() => {
    closed = true;
    clearTimeout(next);
    clearTimeout(deadline);
  });
  async function beat() {
    if (closed) return;
    try {
      await Promise.race([
        server.ping(),
        new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('ping timeout')), timeout); }),
      ]);
      if (!closed) next = setTimeout(beat, interval);
    } catch {
      if (!closed) await server.close().catch(() => {});
    } finally { clearTimeout(deadline); }
  }
  void beat();
};
