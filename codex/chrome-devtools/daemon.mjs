import fs from 'node:fs';
import net from 'node:net';
import {retireWhenIdle} from './retirement.mjs';
import {prepareDirectory, acquireLock, directory, socketPath, statusPath, lockPath, loadUpstream, version} from './runtime.mjs';

prepareDirectory();
if (!acquireLock()) process.exit(0);
const clients = new Set();
let browser;
let browserManager;
let server;
let stopping = false;
const status = {pid: process.pid, version, startedAt: new Date().toISOString(), clients: 0, connections: 0, connected: false};
function saveStatus() {
  status.clients = clients.size;
  const temporary = `${statusPath}.new`;
  fs.writeFileSync(temporary, JSON.stringify(status), {mode: 0o600});
  fs.renameSync(temporary, statusPath);
}
async function shutdown() {
  if (stopping) return;
  stopping = true;
  server?.close();
  for (const client of clients) client.socket.destroy();
  await Promise.allSettled([...clients].map(client => client.mcp?.close()));
  await browserManager?.close();
  for (const file of [socketPath, statusPath, lockPath]) fs.rmSync(file, {force: true});
  process.exit(0);
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

try {
  const {McpServer, BrowserManager, StdioServerTransport, config} = await loadUpstream();
  browserManager = new BrowserManager(config);
  // A client's MCP context can close without disconnecting the shared browser.
  const sharedManager = {
    async ensureBrowser() {
      const current = await browserManager.ensureBrowser();
      if (current !== browser) {
        browser = current;
        status.connections++;
        status.connected = true;
        current.once('disconnected', () => {
          if (browser === current) {
            status.connected = false;
            if (!stopping) saveStatus();
          }
        });
        saveStatus();
      }
      return current;
    },
    abandonPendingAttempt: () => browserManager.abandonPendingAttempt(),
    async close() {},
  };
  fs.rmSync(socketPath, {force: true});
  server = net.createServer(socket => {
    socket.pause();
    const client = {socket, mcp: null};
    clients.add(client);
    saveStatus();
    socket.on('error', error => console.error(error.message));
    socket.once('close', () => {
      clients.delete(client);
      void client.mcp?.close().catch(error => console.error(error.message));
      if (!stopping) saveStatus();
    });
    void (async () => {
      // Keep MCP capabilities, roots, tool schemas and validation per client.
      client.mcp = await McpServer.from(config, {browserManager: sharedManager});
      if (socket.destroyed) {
        await client.mcp.close();
        return;
      }
      await client.mcp.connect(new StdioServerTransport(socket, socket));
      socket.resume();
    })().catch(error => {
      console.error(error);
      socket.destroy();
    });
  });
  server.on('error', error => {
    console.error(error);
    void shutdown();
  });
  server.listen(socketPath, () => {
    fs.chmodSync(socketPath, 0o600);
    saveStatus();
    if (fs.existsSync(`${directory}/retire-when-idle`)) retireWhenIdle(server, shutdown);
    console.error(`Shared Chrome DevTools ${version} ready in ${directory}`);
  });
} catch (error) {
  console.error(error);
  await shutdown();
}
