import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import http from 'node:http';
import {once} from 'node:events';
const require = createRequire(import.meta.url);
const {Client, StreamableHTTPClientTransport} = require('playwright-core/lib/utilsBundle');
const endpoint = new URL(process.argv[2]);
const site = http.createServer((request, response) => {
  response.setHeader('Content-Type', 'text/html');
  response.end('<title>Lifecycle verification</title>');
});
site.listen(0, '127.0.0.1');
await once(site, 'listening');
const origin = `http://127.0.0.1:${site.address().port}`;
const sessions = [];
async function connect() {
  const transport = new StreamableHTTPClientTransport(endpoint);
  const client = new Client({name: 'lifecycle-verification', version: '1'});
  const session = {client, transport};
  sessions.push(session);
  await client.connect(transport);
  return session;
}
async function call(session, name, args = {}) { return session.client.callTool({name, arguments: args}, undefined, {timeout: 10000}); }
try {
  const a = await connect(), b = await connect(), c = await connect();
  assert(!(await call(a, 'browser_navigate', {url: origin + '/a'})).isError);
  assert(!(await call(b, 'browser_navigate', {url: origin + '/b'})).isError);
  assert((await call(c, 'browser_navigate', {url: origin + '/c'})).isError, 'Session cap was bypassed');
  const active = call(a, 'browser_evaluate', {function: 'async () => { await new Promise(resolve => setTimeout(resolve, 2700)); return "completed"; }'});
  assert(!(await active).isError, 'Idle timeout interrupted an active tool');
  assert(!(await call(c, 'browser_navigate', {url: origin + '/c'})).isError, 'Idle session did not release capacity');
  await new Promise(resolve => setTimeout(resolve, 2300));
  assert(!(await call(a, 'browser_navigate', {url: origin + '/reconnected'})).isError, 'Idle client could not reconnect');
  console.log(JSON.stringify({sessionCap: true, idleReclaimed: true, activeWorkPreserved: true, idleReconnect: true}));
} finally {
  for (const {transport, client} of sessions) {
    await transport.terminateSession().catch(() => {});
    await client.close();
  }
  site.close();
}
