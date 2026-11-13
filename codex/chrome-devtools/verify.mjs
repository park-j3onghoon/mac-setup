import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
import {statusPath} from './runtime.mjs';

function client() {
  const child = spawn(process.execPath, [path.join(import.meta.dirname, 'bridge.mjs')], {
    stdio: ['pipe', 'pipe', 'inherit'], env: process.env,
  });
  const pending = new Map();
  let nextId = 0;
  readline.createInterface({input: child.stdout}).on('line', line => {
    const message = JSON.parse(line);
    if (message.method === 'roots/list') {
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', id: message.id, result: {roots: []}}) + '\n');
    } else if (pending.has(message.id)) {
      const {resolve, reject, timer} = pending.get(message.id);
      clearTimeout(timer);
      pending.delete(message.id);
      if (message.error) reject(new Error(JSON.stringify(message.error)));
      else resolve(message.result);
    }
  });
  const exited = new Promise(resolve => child.once('exit', resolve));
  const request = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => reject(new Error(`Timeout: ${method}`)), 65000);
    pending.set(id, {resolve, reject, timer});
    child.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
  });
  return {
    request,
    async initialize() {
      const result = await request('initialize', {
        protocolVersion: '2025-06-18', capabilities: {roots: {listChanged: true}},
        clientInfo: {name: 'shared-chrome-verification', version: '1'},
      });
      assert.equal(result.serverInfo.name, 'chrome_devtools');
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', method: 'notifications/initialized'}) + '\n');
      const {tools} = await request('tools/list');
      assert(tools.some(tool => tool.name === 'list_pages'));
      assert(tools.find(tool => tool.name === 'evaluate_script').inputSchema.required.includes('pageId'));
      return tools.length;
    },
    async close() {
      child.stdin.end();
      const exitCode = await exited;
      assert.equal(exitCode, 0);
    },
  };
}

const initial = [client(), client(), client()];
const counts = await Promise.all(initial.map(item => item.initialize()));
const before = JSON.parse(fs.readFileSync(statusPath, 'utf8'));
assert.equal(before.clients, 3);
console.log(JSON.stringify({phase: 'concurrent_clients', tools: counts, pid: before.pid}));
if (process.argv.includes('--browser')) {
  const result = await initial[0].request('tools/call', {name: 'list_pages', arguments: {}});
  assert(!result.isError, JSON.stringify(result));
  console.log('First browser read succeeded (page contents omitted).');
}
await Promise.all(initial.map(item => item.close()));
await delay(200);
const idle = JSON.parse(fs.readFileSync(statusPath, 'utf8'));
assert.equal(idle.clients, 0);
assert.equal(idle.pid, before.pid);

const later = client();
await later.initialize();
if (process.argv.includes('--browser')) {
  const result = await later.request('tools/call', {name: 'list_pages', arguments: {}});
  assert(!result.isError, JSON.stringify(result));
}
await later.close();
await delay(200);
const after = JSON.parse(fs.readFileSync(statusPath, 'utf8'));
assert.equal(after.pid, before.pid);
assert.equal(after.connections, idle.connections);
if (process.argv.includes('--browser')) assert.equal(after.connected, true);
console.log(JSON.stringify({phase: 'reused_after_all_clients_exited', ...after}));
