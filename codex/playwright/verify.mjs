import assert from 'node:assert/strict';
import http from 'node:http';
import {createRequire} from 'node:module';
import {once} from 'node:events';

const require = createRequire(import.meta.url);
const {Client, StreamableHTTPClientTransport} = require('playwright-core/lib/utilsBundle');
const endpoint = new URL(process.argv[2] || 'http://127.0.0.1:8931/mcp');
const site = http.createServer((request, response) => {
  const name = request.url.slice(1);
  if (!/^session-[0-9]+$/.test(name)) {
    response.writeHead(404).end();
    return;
  }
  response.setHeader('Content-Type', 'text/html');
  response.end(`<title>${name}</title><h1>${name}</h1><input aria-label="Session value"><button id="click" onclick="this.textContent='clicked'">Click</button><input id="check" type="checkbox">`);
});
site.listen(0, '127.0.0.1');
await once(site, 'listening');
const origin = `http://127.0.0.1:${site.address().port}`;
const sessions = [];

async function call(session, name, args = {}) {
  const result = await session.client.callTool({name, arguments: args}, undefined, {timeout: 45000});
  assert(!result.isError, `${name} failed (page contents withheld)`);
  return result.content.filter(item => item.type === 'text').map(item => item.text).join('\n');
}

async function connect(index) {
  const transport = new StreamableHTTPClientTransport(endpoint);
  const client = new Client({name: `shared-playwright-verification-${index}`, version: '1'});
  const session = {client, transport, index, pageOpened: false, closed: false};
  sessions.push(session);
  await client.connect(transport);
  assert((await client.listTools()).tools.some(tool => tool.name === 'browser_tabs'));
  session.pageOpened = true;
  await call(session, 'browser_navigate', {url: `${origin}/session-${index}`});
  return session;
}

async function close(session) {
  if (session.closed) return;
  try {
    if (session.pageOpened) await call(session, 'browser_tabs', {action: 'close'});
  } finally {
    await session.transport.terminateSession().catch(() => {});
    await session.client.close();
    session.closed = true;
  }
}

try {
  const connected = await Promise.allSettled([0, 1, 2].map(connect));
  const failed = connected.find(result => result.status === 'rejected');
  if (failed) throw failed.reason;
  const clients = connected.map(result => result.value);
  assert.equal(new Set(clients.map(session => session.transport.sessionId)).size, 3);
  for (const session of clients) {
    const own = `session-${session.index}`;
    const tabs = await call(session, 'browser_tabs', {action: 'list'});
    assert(tabs.includes(`${origin}/${own}`), 'Own tab missing');
    for (const other of clients) {
      if (other !== session) assert(!tabs.includes(`${origin}/session-${other.index}`), 'Other client tab exposed');
    }
    await call(session, 'browser_click', {target: '#click'});
    await call(session, 'browser_click', {target: '#check'});
    const controls = await call(session, 'browser_evaluate', {
      function: '() => ({clicked: document.querySelector("#click").textContent, checked: document.querySelector("#check").checked})',
    });
    assert(controls.includes('clicked') && controls.includes('true'), 'Background input did not change the controls');
    await call(session, 'browser_evaluate', {
      function: `() => { document.querySelector('input').value = '${own}'; return document.title; }`,
    });
  }
  await close(clients[0]);
  for (const session of clients.slice(1)) {
    const value = await call(session, 'browser_evaluate', {function: '() => document.querySelector("input").value'});
    assert(value.includes(`session-${session.index}`), 'Another client disconnect disturbed the page');
  }
  await Promise.all(clients.slice(1).map(close));
  const reconnected = await connect(3);
  assert((await call(reconnected, 'browser_evaluate', {function: '() => document.title'})).includes('session-3'));
  await close(reconnected);
  console.log(JSON.stringify({concurrentClients: 3, tabIsolation: true, independentDisconnect: true, reconnect: true}));
} finally {
  const cleanup = await Promise.allSettled(sessions.map(close));
  site.close();
  assert(cleanup.every(result => result.status === 'fulfilled'), 'Some verification tabs could not be closed');
}
