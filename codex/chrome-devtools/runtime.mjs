import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

export const version = '1.12.0';
export const directory = process.env.CODEX_CHROME_RUNTIME || `/tmp/codex-chrome-${process.getuid()}`;
export const socketPath = path.join(directory, 'server.sock');
export const statusPath = path.join(directory, 'status.json');
export const lockPath = path.join(directory, 'daemon.pid');
export const serverArgs = ['--autoConnect', '--no-usage-statistics', '--no-performance-crux', '--redactNetworkHeaders'];

export function prepareDirectory() {
  fs.mkdirSync(directory, {recursive: true, mode: 0o700});
  const stat = fs.lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid() || (stat.mode & 0o077)) {
    throw new Error(`Unsafe Chrome runtime directory: ${directory}`);
  }
}

export function daemonAlive() {
  try {
    const pid = Number(fs.readFileSync(lockPath, 'utf8'));
    if (!Number.isSafeInteger(pid) || pid <= 0) return false;
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error.code === 'EPERM') return true;
    return false;
  }
}

export function acquireLock() {
  try {
    fs.writeFileSync(lockPath, String(process.pid), {flag: 'wx', mode: 0o600});
    return true;
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    // An empty file may belong to a competing process still writing its PID.
    if (daemonAlive() || Date.now() - fs.statSync(lockPath).mtimeMs < 30000) return false;
    fs.unlinkSync(lockPath);
    return acquireLock();
  }
}

export async function loadUpstream() {
  const executable = execFileSync('/opt/homebrew/bin/npx', [
    '--yes', `--package=chrome-devtools-mcp@${version}`, '--', 'which', 'chrome-devtools-mcp',
  ], {encoding: 'utf8', timeout: 45000, stdio: ['ignore', 'pipe', 'inherit']}).trim();
  const root = path.resolve(path.dirname(fs.realpathSync(executable)), '../../..');
  if (JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version !== version) {
    throw new Error('Unexpected chrome-devtools-mcp version');
  }
  const module = relative => import(pathToFileURL(path.join(root, 'build/src', relative)).href);
  const [{McpServer}, {BrowserManager}, {ConfigParser}, {StdioServerTransport}, {ServiceWorkerSubscriber}] = await Promise.all([
    module('index.js'), module('BrowserManager.js'), module('config/ConfigParser.js'), module('third_party/index.js'),
    module('collectors/ServiceWorkerCollector.js'),
  ]);
  // In 1.12.0 a destroyed extension worker can already have lost its CDP session.
  // Handle that completed cleanup here; unrelated failures must still propagate.
  const unsubscribe = ServiceWorkerSubscriber.prototype.unsubscribe;
  ServiceWorkerSubscriber.prototype.unsubscribe = async function () {
    try {
      await unsubscribe.call(this);
    } catch (error) {
      if (!(error instanceof Error) ||
          error.message !== 'Session already detached. Most likely the service_worker has been closed.') {
        throw error;
      }
    }
  };
  const config = new ConfigParser(version, [process.execPath, 'chrome-devtools-mcp', ...serverArgs], {
    ...process.env, CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY: '1',
  }).parseConfig();
  return {McpServer, BrowserManager, StdioServerTransport, config};
}
