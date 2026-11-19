import fs from 'node:fs/promises';
import path from 'node:path';

export async function maintainStorage(directory, log, now = Date.now()) {
  const entries = await fs.readdir(directory, {recursive: true, withFileTypes: true}).catch(error => {
    if (error.code === 'ENOENT') return [];
    throw error;
  });
  const files = [];
  for (const entry of entries.filter(entry => entry.isFile())) {
    const file = path.join(entry.parentPath, entry.name);
    const stat = await fs.stat(file).catch(() => null);
    if (stat) files.push({file, size: stat.size, modified: stat.mtimeMs});
  }
  let size = files.reduce((sum, file) => sum + file.size, 0);
  for (const file of files.sort((a, b) => a.modified - b.modified)) {
    // Recent files may still be being written or consumed by another client.
    if (now - file.modified < 60000) continue;
    if (size <= 64 * 1024 * 1024 && now - file.modified < 7 * 86400000) continue;
    await fs.unlink(file.file).catch(error => { if (error.code !== 'ENOENT') throw error; });
    size -= file.size;
  }
  for (const entry of entries.filter(entry => entry.isDirectory()).reverse())
    await fs.rmdir(path.join(entry.parentPath, entry.name)).catch(error => {
      if (!['ENOTEMPTY', 'ENOENT'].includes(error.code)) throw error;
    });
  if (log) {
    const handle = await fs.open(log, 'a+', 0o600);
    try {
      if ((await handle.stat()).size > 4 * 1024 * 1024) {
        // launchd keeps this inode open; renaming would leave the old fd growing.
        await handle.truncate(0);
        await handle.write('[log rotated at 4 MiB]\n');
      }
    } finally { await handle.close(); }
  }
}

export function batchConsole(log) {
  if (log.flush) return;
  let pending = [], dropped = 0, timer, totalBytes = 0, writing = false, capped = false;
  log.flush = () => {
    clearTimeout(timer);
    timer = undefined;
    if (writing) return log._writeChain;
    const batch = pending;
    pending = [];
    if (dropped) batch.push({wallTime: Date.now(), text: `[${dropped} console messages omitted by log limit]`});
    dropped = 0;
    if (!batch.length) return log._writeChain;
    writing = true;
    log._writeChain = log._writeChain.then(async () => {
      log._file ??= await log._context.outputFile({prefix: 'console', ext: 'log', date: new Date(log._startTime)}, {origin: 'code'});
      const data = batch.map(({wallTime, text}) => `[${Math.round(wallTime - log._startTime)}ms] ${log._context.redactSecrets(text)}\n`).join('');
      let output = data;
      if (totalBytes + Buffer.byteLength(data) > 8 * 1024 * 1024) {
        if (capped) return;
        capped = true;
        output = '[Console log reached 8 MiB; subsequent messages omitted]\n';
      }
      await fs.appendFile(log._file, output, {mode: 0o600});
      totalBytes += Buffer.byteLength(output);
      log._line += output.split('\n').length - 1;
      log._entries += batch.length;
    }).catch(error => console.error('Console log write failed:', error.code || error.name)).finally(() => {
      writing = false;
      if (pending.length || dropped) timer ??= setTimeout(log.flush, 100).unref();
    });
    return log._writeChain;
  };
  log.appendLine = (wallTime, text) => {
    if (log._stopped || capped) return;
    if (pending.length >= 1000) dropped++;
    else pending.push({wallTime, text: text.length > 8192 ? text.slice(0, 8192) + ' [truncated]' : text});
    timer ??= setTimeout(log.flush, 100).unref();
  };
  const take = log._take.bind(log);
  log._take = async () => {
    await log.flush();
    return take();
  };
  log.close = async () => {
    log._stopped = true;
    do { await log.flush(); } while (pending.length || dropped);
  };
  log.stop = () => { void log.close(); };
}
