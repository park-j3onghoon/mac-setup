import {createRequire} from 'node:module';
import {loadRuntime, installPerformanceAdapter} from './runtime.mjs';

const require = createRequire(import.meta.url);
const runtime = loadRuntime();
installPerformanceAdapter(runtime);
const {program} = require('playwright-core/lib/utilsBundle');
const version = require('@playwright/mcp/package.json').version;
runtime.tools.decorateMCPCommand(program.version(version).name('Shared Playwright'), version);
await program.parseAsync(process.argv);
