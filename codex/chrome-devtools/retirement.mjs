// Stop accepting connections only after the existing ones have drained. Closing
// the listener before shutdown also covers an accept racing with getConnections.
export function retireWhenIdle(server, shutdown, interval = 60000) {
  let checking = false, retiring = false;
  const timer = setInterval(() => {
    if (checking || retiring || !server.listening) return;
    checking = true;
    server.getConnections((error, count) => {
      checking = false;
      if (error || count !== 0) return;
      retiring = true;
      clearInterval(timer);
      server.close(() => { void shutdown(); });
    });
  }, interval);
  timer.unref();
  return {cancel: () => clearInterval(timer)};
}
