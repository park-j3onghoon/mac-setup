import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {directory, socketPath, statusPath, prepareDirectory} from './runtime.mjs';

prepareDirectory();
const status = JSON.parse(fs.readFileSync(statusPath, 'utf8'));
const command = execFileSync('/bin/ps', ['-p', String(status.pid), '-o', 'command='], {encoding: 'utf8'});
if (!command.includes('/codex/chrome-devtools/daemon.mjs')) throw new Error('Legacy daemon identity did not match.');
// SIGUSR1 opens Node's loopback inspector without stopping the event loop.
let openedInspector = false;
let targets;
try { targets = await (await fetch('http://127.0.0.1:9229/json/list')).json(); }
catch {
  process.kill(status.pid, 'SIGUSR1');
  openedInspector = true;
  for (let i = 0; i < 50; i++) {
    await new Promise(resolve => setTimeout(resolve, 100));
    try { targets = await (await fetch('http://127.0.0.1:9229/json/list')).json(); break; } catch {}
  }
}
if (!targets?.[0]?.webSocketDebuggerUrl) throw new Error('Node inspector unavailable. Legacy daemon was left running.');
const ws = new WebSocket(targets[0].webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let sequence = 0;
const pending = new Map();
ws.onmessage = event => {
  const message = JSON.parse(event.data);
  if (message.id) { pending.get(message.id)?.(message); pending.delete(message.id); }
};
async function evaluate(expression) {
  const id = ++sequence;
  const response = new Promise(resolve => pending.set(id, resolve));
  ws.send(JSON.stringify({id, method: 'Runtime.evaluate', params: {expression, awaitPromise: true, returnByValue: true}}));
  let timer;
  let message;
  try {
    message = await Promise.race([response, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Node inspector response timed out.')), 5000);
    })]);
  } finally { clearTimeout(timer); pending.delete(id); }
  if (message.error || message.result.exceptionDetails) throw new Error('Retirement registration failed; daemon was left running.');
  return message.result.result.value;
}
let verified = false;
try {
  if (await evaluate('process.pid') !== status.pid) throw new Error('Inspector belongs to another process.');
  verified = true;
  const moduleURL = pathToFileURL(`${import.meta.dirname}/retirement.mjs`).href;
  const armed = await evaluate(`(async () => {
    if (globalThis.__codexChromeRetirement) return true;
    const server = process._getActiveHandles().find(handle => handle.listening && handle.address?.() === ${JSON.stringify(socketPath)});
    if (!server) return false;
    const {retireWhenIdle} = await import(${JSON.stringify(moduleURL)});
    globalThis.__codexChromeRetirement = retireWhenIdle(server, () => process.emit('SIGTERM'));
    return true;
  })()`);
  if (!armed) throw new Error('Legacy listener not found.');
  fs.writeFileSync(`${directory}/retire-when-idle`, `${status.pid}\n`, {mode: 0o600});
  console.log(JSON.stringify({pid: status.pid, retirementArmed: true, clientsAtRegistration: status.clients}));
} finally {
  if (verified && openedInspector)
    await evaluate("import('node:inspector').then(inspector => { setTimeout(() => inspector.close(), 100); return true; })");
  ws.close();
}
