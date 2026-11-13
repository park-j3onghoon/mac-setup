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
process.stdout.on('error', () => socket.destroy());

// Pages opened with new_page stay in the user's Chrome after the session is done with them,
// so the bridge closes the background pages its session opened after this browser idle time and at session end.
const IDLE_CLOSE_MS = 5 * 60 * 1000;
const EXIT_CLOSE_TIMEOUT_MS = 5000;
const openedPages = new Set();
const newPageCalls = new Set();
const closeCalls = new Map();
let idleTimer;
let ending = false;

function onLines(stream, handle) {
  let rest = '';
  stream.setEncoding('utf8');
  stream.on('data', chunk => {
    const lines = (rest + chunk).split('\n');
    rest = lines.pop();
    for (const line of lines) handle(`${line}\n`);
  });
}

function closeOpenedPages() {
  const closed = [...openedPages].map(pageId => new Promise(resolve => {
    const id = `bridge-close-${pageId}`;
    closeCalls.set(id, resolve);
    socket.write(`${JSON.stringify({jsonrpc: '2.0', id, method: 'tools/call', params: {name: 'close_page', arguments: {pageId}}})}\n`);
  }));
  openedPages.clear();
  return Promise.all(closed);
}

onLines(process.stdin, line => {
  if (line.includes('"tools/call"')) {
    const message = JSON.parse(line);
    if (message.method === 'tools/call') {
      const {name, arguments: args} = message.params;
      // A page opened in or brought to the foreground was shown to the user, who closes it.
      if (name === 'new_page' && args.background) newPageCalls.add(message.id);
      if (name === 'close_page' || (name === 'select_page' && args.bringToFront)) openedPages.delete(args.pageId);
      clearTimeout(idleTimer);
      idleTimer = setTimeout(closeOpenedPages, IDLE_CLOSE_MS);
    }
  }
  socket.write(line);
});

onLines(socket, line => {
  if (newPageCalls.size || closeCalls.size) {
    const message = JSON.parse(line);
    // Server requests such as roots/list share the id space with Codex requests, so only responses count.
    if (message.method === undefined) {
      if (closeCalls.has(message.id)) {
        closeCalls.get(message.id)();
        closeCalls.delete(message.id);
        return;
      }
      if (newPageCalls.delete(message.id) && message.result && !message.result.isError) {
        // new_page selects the page it opened: "## Pages\n12: Title (https://example.com) [selected]"
        const text = message.result.content.map(item => item.text).join('\n');
        const selected = /^(\d+): .* \[selected\]/m.exec(text);
        if (selected) openedPages.add(Number(selected[1]));
        else console.error('new_page result has no selected page, so the bridge cannot close it');
      }
    }
  }
  process.stdout.write(line);
});

async function end() {
  if (ending) return;
  ending = true;
  clearTimeout(idleTimer);
  await Promise.race([closeOpenedPages(), delay(EXIT_CLOSE_TIMEOUT_MS)]);
  socket.end();
}
process.stdin.on('end', end);
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, async () => { await end(); process.exit(0); });
}
