import {createRequire} from 'node:module';
import {loadRuntime, installPerformanceAdapter} from './runtime.mjs';
import {maintainStorage} from './storage.mjs';
import path from 'node:path';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const runtime = loadRuntime({maxSessions: Number(process.env.SHARED_PLAYWRIGHT_MAX_SESSIONS || 16)});
installPerformanceAdapter(runtime, {idleMs: Number(process.env.SHARED_PLAYWRIGHT_IDLE_MS || 1800000)});
const {program} = require('playwright-core/lib/utilsBundle');
const version = require('@playwright/mcp/package.json').version;
runtime.tools.decorateMCPCommand(program.version(version).name('Shared Playwright'), version);
const artifacts = path.resolve('artifacts');
await fs.mkdir(artifacts, {recursive: true, mode: 0o700});
let maintaining = false;
const maintain = async () => {
  if (maintaining) return;
  maintaining = true;
  try { await maintainStorage(artifacts, process.env.SHARED_PLAYWRIGHT_LOG); }
  catch (error) { console.error('Storage maintenance failed:', error.code || error.name); }
  finally { maintaining = false; }
};
await maintain();
setInterval(maintain, 60000).unref();
await program.parseAsync([...process.argv, '--output-dir', artifacts]);
