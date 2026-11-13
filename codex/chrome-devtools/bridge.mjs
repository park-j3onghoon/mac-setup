import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
import {prepareDirectory, directory, socketPath, statusPath, daemonAlive} from './runtime.mjs';

prepareDirectory();
if (process.argv.includes('--status')) {
  console.log(daemonAlive() && fs.existsSync(statusPath) ? fs.readFileSync(statusPath, 'utf8') : '{"running":false}');
  process.exit(0);
}

function connect() {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    socket.once('error', reject);
    socket.once('connect', () => {
      socket.off('error', reject);
      resolve(socket);
    });
  });
}

let socket;
let spawned = false;
const deadline = Date.now() + 55000;
while (!socket) {
  try {
    socket = await connect();
  } catch (error) {
    if (!['ENOENT', 'ECONNREFUSED'].includes(error.code) || Date.now() > deadline) throw error;
    if (!spawned && !daemonAlive()) {
      const log = fs.openSync(path.join(directory, 'daemon.log'), 'a', 0o600);
      const child = spawn(process.execPath, [path.join(import.meta.dirname, 'daemon.mjs')], {
        detached: true, stdio: ['ignore', log, log], env: process.env,
      });
      child.on('error', failure => { console.error(failure); process.exit(1); });
      child.unref();
      fs.closeSync(log);
      spawned = true;
    }
    await delay(100);
  }
}
socket.on('error', error => { console.error(error.message); process.exitCode = 1; });
socket.on('close', () => process.exit(process.exitCode || 0));
process.stdin.pipe(socket);
socket.pipe(process.stdout);
process.stdin.on('end', () => socket.end());
process.stdout.on('error', () => socket.destroy());
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => { socket.destroy(); process.exit(0); });
}
