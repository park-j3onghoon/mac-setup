import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import http from 'node:http';
import {once} from 'node:events';
const require = createRequire(import.meta.url);
const {Client, StreamableHTTPClientTransport} = require('playwright-core/lib/utilsBundle');
const endpoint = new URL(process.argv[2]);
const activeTab = () => execFileSync('/usr/bin/osascript', ['-e', 'tell application "Google Chrome" to get id of active tab of window 1'], {encoding: 'utf8'}).trim();
const chromeURLs = () => execFileSync('/usr/bin/osascript', ['-e', 'tell application "Google Chrome" to get URL of every tab of every window'], {encoding: 'utf8'});
const initialTab = activeTab();
const site = http.createServer((request, response) => {
  if (request.url === '/slow') return setTimeout(() => response.end('done'), 1000);
  if (request.url.startsWith('/request-')) return response.end('ok');
  response.setHeader('Content-Type', 'text/html');
  response.end('<title>Performance verification</title><button id="button" onclick="this.textContent=\'clicked\'">Click</button><div id="small">small target</div>');
});
site.listen(0, '127.0.0.1');
await once(site, 'listening');
const origin = `http://127.0.0.1:${site.address().port}`;
const transport = new StreamableHTTPClientTransport(endpoint);
const client = new Client({name: 'performance-regression', version: '1'});
async function call(name, args = {}) {
  const result = await client.callTool({name, arguments: args}, undefined, {timeout: 60000});
  assert(!result.isError, `${name}: ${JSON.stringify(result)}`);
  return result.content.filter(item => item.type === 'text').map(item => item.text).join('\n');
}
try {
  await client.connect(transport);
  await call('browser_navigate', {url: origin + '/work'});
  await call('browser_click', {target: '#button'});
  assert.equal(activeTab(), initialTab);
  const start = performance.now();
  await call('browser_evaluate', {function: '() => document.title'});
  const evaluateMs = performance.now() - start;
  assert(evaluateMs < 450, `Read evaluation still waits: ${evaluateMs}ms`);
  console.log(JSON.stringify({evaluateMs: Math.round(evaluateMs)}));
  const nonblocking = performance.now();
  await call('browser_evaluate', {function: '() => { fetch("/slow"); return "started"; }'});
  assert(performance.now() - nonblocking < 800, 'Unrelated fetch delayed read response');
  const awaited = performance.now();
  const completed = await call('browser_evaluate', {function: 'async () => await (await fetch("/slow")).text()'});
  assert(completed.includes('done') && performance.now() - awaited >= 950);
  await call('browser_evaluate', {function: '() => { document.body.insertAdjacentHTML("beforeend", Array.from({length: 3000}, (_, i) => `<a href="#${i}">Link ${i}</a>`).join("")); }'});
  const snapshot = await call('browser_snapshot');
  assert(snapshot.includes('Large snapshot saved'), 'Large snapshot was not moved to a file');
  assert((await call('browser_snapshot', {target: '#small'})).includes('small target'));
  assert((await call('browser_evaluate', {function: '() => "x".repeat(100000)'})).includes('Large result saved'));
  const rejected = await client.callTool({name: 'browser_evaluate', arguments: {function: '() => "x".repeat(1500000)'}});
  assert(rejected.isError, 'Oversized evaluation crossed CDP');
  const screenshot = await client.callTool({name: 'browser_take_screenshot', arguments: {type: 'png'}});
  assert(!screenshot.isError && screenshot.content.some(item => item.type === 'image'));
  await call('browser_evaluate', {function: '() => { document.body.style.height="20000px"; }'});
  const largeScreenshot = await client.callTool({name: 'browser_take_screenshot', arguments: {fullPage: true}});
  assert(largeScreenshot.isError, 'Oversized screenshot was accepted');
  await call('browser_evaluate', {function: `async () => {
    for (let base = 0; base < 520; base += 20)
      await Promise.all(Array.from({length: 20}, (_, i) => fetch('/request-' + (base + i))));
    return 'requests complete';
  }`});
  const requests = await call('browser_network_requests');
  assert(requests.includes('Request history limited to 500'), 'Missing request eviction notice');
  assert(requests.includes('/request-519'), 'Newest request was lost');
  assert(!requests.includes('/request-0 '), 'Old request retained beyond cap');
  await call('browser_tabs', {action: 'new', url: origin + '/kept'});
  await call('browser_keep_tab');
  await call('browser_tabs', {action: 'select', index: 0});
  await transport.terminateSession();
  for (let i = 0; i < 50 && chromeURLs().includes(origin + '/work'); i++)
    await new Promise(resolve => setTimeout(resolve, 100));
  assert(!chromeURLs().includes(origin + '/work'), 'Session work tab leaked');
  assert(chromeURLs().includes(origin + '/kept'), 'Preserved tab was closed');
  console.log(JSON.stringify({foregroundPreserved: true, workTabCleaned: true, keptTabPreserved: true}));
} finally {
  await transport.terminateSession().catch(() => {});
  await client.close();
  // Only close this test's retained tab, never an unrelated tab or window.
  execFileSync('/usr/bin/osascript', ['-e', `tell application "Google Chrome"
    repeat with w in windows
      repeat with i from (count tabs of w) to 1 by -1
        if URL of tab i of w starts with "${origin}/" then close tab i of w
      end repeat
    end repeat
  end tell`]);
  site.close();
  assert.equal(activeTab(), initialTab, 'User active tab changed');
}
