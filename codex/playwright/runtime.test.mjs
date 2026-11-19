import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Admission} from './admission.mjs';
import {evaluateBounded} from './payloads.mjs';
import {maintainStorage, batchConsole} from './storage.mjs';
import heartbeat from './heartbeat.cjs';
import {EventEmitter} from 'node:events';
import {withPageFocus} from './focus.mjs';
import {loadRuntime, installPerformanceAdapter} from './runtime.mjs';

test('focus restoration waits for dialog dismissal without blocking its tool', async () => {
  const page = new EventEmitter();
  const sent = [];
  let dialog = false;
  page.isClosed = () => false;
  page._connection = {toImpl: () => ({delegate: {_mainFrameSession: {_client: {send: async (_, {enabled}) => {
    assert(!dialog, 'A focus command was sent while a modal blocked CDP');
    sent.push(enabled);
  }}}}})};
  await withPageFocus(page, () => dialog, async () => { dialog = true; });
  assert.deepEqual(sent, [true]);
  await withPageFocus(page, () => dialog, async () => { dialog = false; page.emit('dialogclosed'); });
  assert.deepEqual(sent, [true, false]);
  assert.equal(page.listenerCount('dialogclosed'), 0);
});

test('evaluate and screenshot reject existing modals before page I/O', async () => {
  const runtime = loadRuntime();
  installPerformanceAdapter(runtime);
  const tab = {modalStates: () => [{type: 'dialog'}], page: new Proxy({}, {get: () => assert.fail('Unexpected page I/O')})};
  const context = {ensureTab: async () => tab};
  for (const name of ['browser_evaluate', 'browser_take_screenshot']) {
    const tool = runtime.tools.browserTools.find(tool => tool.schema.name === name);
    await assert.rejects(tool.handle(context, {}, {addResult() {}}), /dialog/);
  }
});

test('bounded admission preserves FIFO, rejects overflow and cancels queued work', async () => {
  const gate = new Admission(1, 1);
  let release;
  const first = gate.run(() => new Promise(resolve => { release = resolve; }));
  const abort = new AbortController();
  const queued = gate.run(() => assert.fail('cancelled operation ran'), abort.signal);
  await assert.rejects(gate.run(() => {}), /busy/);
  abort.abort(new Error('cancelled'));
  await assert.rejects(queued, /cancelled/);
  let secondRan = false;
  const second = gate.run(() => { secondRan = true; });
  assert.equal(secondRan, false);
  release();
  await Promise.all([first, second]);
  assert.equal(gate.active, 0);
  assert.equal(secondRan, true);
});

test('page-side serialization bounds large, deep and cyclic results', async () => {
  assert.equal(await evaluateBounded({expression: 'async () => ({value: await Promise.resolve(7)})'}), '{\n  "value": 7\n}');
  await assert.rejects(evaluateBounded({expression: '() => "x".repeat(1500000)'}), /budget/);
  await assert.rejects(evaluateBounded({expression: '() => { let a={}; for(let i=0;i<40;i++)a={a};return a; }'}), /levels/);
  assert.match(await evaluateBounded({expression: '() => { const a={};a.self=a;return a; }'}), /Circular/);
  await assert.rejects(evaluateBounded({expression: '() => Symbol("x".repeat(1500000))'}), /budget/);
  assert.match(await evaluateBounded({expression: '() => new Map([["key", 7]])'}), /key/);
  assert.match(await evaluateBounded({expression: '() => new Error("known error")'}), /known error/);
});

test('retention removes only stale artifacts and rotates the launchd log inode', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'pw-retention-'));
  try {
    const artifacts = path.join(root, 'artifacts');
    await fs.mkdir(artifacts);
    const old = path.join(artifacts, 'old');
    const recent = path.join(artifacts, 'recent');
    const userFile = path.join(root, 'report.html');
    const log = path.join(root, 'server.log');
    await fs.writeFile(old, 'old');
    await fs.utimes(old, 0, 0);
    await fs.writeFile(recent, 'recent');
    await fs.writeFile(userFile, 'keep');
    await fs.writeFile(log, Buffer.alloc(4 * 1024 * 1024 + 1));
    const inode = (await fs.stat(log)).ino;
    await maintainStorage(artifacts, log);
    await assert.rejects(fs.stat(old), {code: 'ENOENT'});
    assert.equal(await fs.readFile(recent, 'utf8'), 'recent');
    assert.equal(await fs.readFile(userFile, 'utf8'), 'keep');
    assert.equal((await fs.stat(log)).ino, inode);
    assert((await fs.stat(log)).size < 100);
  } finally { await fs.rm(root, {recursive: true}); }
});

test('console burst is batched, bounded and flushed before reading', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'pw-console-'));
  try {
    const file = path.join(root, 'console.log');
    const log = {_writeChain: Promise.resolve(), _line: 0, _entries: 0, _startTime: 0,
      _context: {outputFile: async () => file, redactSecrets: text => text}, _take: async () => fs.readFile(file, 'utf8')};
    batchConsole(log);
    for (let i = 0; i < 1200; i++) log.appendLine(i, 'warning ' + i);
    const output = await log._take();
    assert.match(output, /warning 999/);
    assert.doesNotMatch(output, /warning 1000/);
    assert.match(output, /200 console messages omitted/);
    log.stop();
  } finally { await fs.rm(root, {recursive: true}); }
});

test('heartbeat tolerates brief delay and stops scheduling after close', async () => {
  let closed = false, listener, pings = 0;
  const server = {ping: async () => { pings++; await new Promise(r => setTimeout(r, 5)); }, close: async () => { closed = true; listener(); }};
  heartbeat.start(server, fn => { listener = fn; }, 10, 50);
  await new Promise(r => setTimeout(r, 40));
  assert(!closed);
  await server.close();
  const count = pings;
  await new Promise(r => setTimeout(r, 30));
  assert.equal(pings, count);
});

test('heartbeat closes an unresponsive client', async () => {
  let listener, closed = false;
  heartbeat.start({ping: () => new Promise(() => {}), close: async () => { closed = true; listener(); }}, fn => { listener = fn; }, 10, 10);
  await new Promise(r => setTimeout(r, 30));
  assert(closed);
});
