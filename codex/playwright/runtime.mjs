import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createRequire, Module} from 'node:module';
import {fileURLToPath} from 'node:url';
import {batchConsole} from './storage.mjs';
import {evaluateBounded} from './payloads.mjs';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
import fs from 'node:fs/promises';
import {Admission} from './admission.mjs';
import {withPageFocus} from './focus.mjs';

const require = createRequire(import.meta.url);
async function withDeadline(promise, milliseconds) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Evaluation timed out; page-side effects may still be pending.')), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}
export function loadRuntime({maxSessions = 16} = {}) {
  if (!Number.isInteger(maxSessions) || maxSessions < 1 || maxSessions > 16) throw new Error('Session limit must be 1..16.');
  const file = require.resolve('playwright-core/lib/coreBundle');
  let source = readFileSync(file, 'utf8');
  if (createHash('sha256').update(source).digest('hex') !== '9d3260b17408501ba46ca708fa870a7c95e1e3f6e9cc34d799465f17b7d78c50')
    throw new Error('Playwright runtime changed: review the performance adapter before upgrading.');
  const replace = (before, after) => {
    if (source.split(before).length !== 2) throw new Error('Playwright adapter patch did not match exactly once.');
    source = source.replace(before, after);
  };
  // Admission must happen before an extension relay or Chrome tab is created.
  replace('        clientCount++;\n        const promise = sharedBrowserPromise;',
    `        if (clientCount >= ${maxSessions}) throw new Error("Active browser session limit (${maxSessions}) reached; close or wait for idle sessions.");\n        clientCount++;\n        const promise = sharedBrowserPromise;`);
  const heartbeatStart = source.indexOf('    startHeartbeat = (server) => {');
  const heartbeatEnd = source.indexOf('\n    };', heartbeatStart) + '\n    };'.length;
  if (heartbeatStart < 0 || heartbeatEnd <= heartbeatStart) throw new Error('Heartbeat patch boundary missing.');
  const heartbeatFile = fileURLToPath(new URL('./heartbeat.cjs', import.meta.url));
  replace(source.slice(heartbeatStart, heartbeatEnd),
    `    startHeartbeat = server => require(${JSON.stringify(heartbeatFile)}).start(server, listener => addServerListener(server, "close", listener));`);
  const loaded = new Module(file);
  loaded.filename = file;
  loaded.paths = Module._nodeModulePaths(path.dirname(file));
  require.cache[file] = loaded;
  try { loaded._compile(source, file); loaded.loaded = true; }
  catch (error) { delete require.cache[file]; throw error; }
  return loaded.exports;
}

export function installPerformanceAdapter({tools}, {idleMs = 30 * 60 * 1000} = {}) {
  if (!Number.isInteger(idleMs) || idleMs < 1000 || idleMs > 30 * 60 * 1000) throw new Error('Idle timeout must be 1000..1800000 ms.');
  const {z} = require('playwright-core/lib/utilsBundle');
  const unsafeIndex = tools.browserTools.findIndex(tool => tool.schema.name === 'browser_run_code_unsafe');
  if (unsafeIndex !== -1) tools.browserTools.splice(unsafeIndex, 1);
  const evaluate = tools.browserTools.find(tool => tool.schema.name === 'browser_evaluate');
  evaluate.schema.inputSchema = evaluate.schema.inputSchema.extend({
    waitForSettled: z.boolean().default(false).describe('Wait for additional navigation/network settling. Normally await the required promise inside the expression instead.'),
  });
  evaluate.handle = async (context, params, response, signal) => {
    const tab = await context.ensureTab();
    if (tab.modalStates().length) throw new Error('Close the page dialog/file chooser with its dedicated tool before evaluating JavaScript.');
    const target = params.target && await tab.targetLocator({target: params.target, element: params.element || 'element'});
    context.skipCompletionWait = !params.waitForSettled;
    try {
      await tab.waitForCompletion(async () => {
        const expression = params.function;
        const text = await withDeadline(target
          ? target.locator.evaluate(`(element, params) => (${evaluateBounded.toString()})(params, element)`, {expression})
          : tab.page.evaluate(evaluateBounded, {expression}), 40000);
        await response.addResult('Evaluation result', text, {prefix: 'result', ext: 'json', suggestedFilename: params.filename});
      });
    }
    finally { context.skipCompletionWait = false; }
  };
  const waitForCompletion = tools.Tab.prototype.waitForCompletion;
  tools.Tab.prototype.waitForCompletion = async function (callback) {
    if (!this.context.skipCompletionWait) return waitForCompletion.call(this, callback);
    await this._initializedPromise;
    return this._raceAgainstModalStates(callback);
  };
  const addRequest = tools.Tab.prototype._addRequest;
  tools.Tab.prototype._addRequest = function (request) {
    addRequest.call(this, request);
    const excess = this._requests.length - 500;
    if (excess > 0) {
      this._requests.splice(0, excess);
      this.droppedRequests = (this.droppedRequests || 0) + excess;
    }
  };
  const addLogEntry = tools.Tab.prototype._addLogEntry;
  tools.Tab.prototype._addLogEntry = function (entry) {
    addLogEntry.call(this, entry);
    if (this._recentEventEntries.length > 1000) {
      this._recentEventEntries.shift();
      this.droppedEvents = (this.droppedEvents || 0) + 1;
    }
  };
  const captureSnapshot = tools.Tab.prototype.captureSnapshot;
  tools.Tab.prototype.captureSnapshot = async function (...args) {
    const result = await captureSnapshot.apply(this, args);
    const snapshot = result.ariaSnapshotJSON ? JSON.stringify(result.ariaSnapshotJSON) : result.ariaSnapshot;
    if (Buffer.byteLength(snapshot) > 8 * 1024 * 1024) throw new Error('Snapshot exceeds 8 MiB; use target and depth.');
    if (Buffer.byteLength(snapshot) > 65536) {
      const file = await this.context.outputFile({prefix: 'snapshot', ext: result.ariaSnapshotJSON ? 'json' : 'yml'}, {origin: 'code'});
      await fs.writeFile(file, this.context.redactSecrets(snapshot), {mode: 0o600});
      result.ariaSnapshot = `Large snapshot saved to ${file}. Use target/depth for inline output.`;
      if (result.ariaSnapshotJSON) result.ariaSnapshotJSON = {file};
    }
    return result;
  };
  const initializeTab = tools.Tab.prototype._initialize;
  tools.Tab.prototype._initialize = function (...args) {
    batchConsole(this._consoleLog);
    return initializeTab.apply(this, args);
  };
  const resetLogs = tools.Tab.prototype._resetLogs;
  tools.Tab.prototype._resetLogs = function () {
    resetLogs.call(this);
    batchConsole(this._consoleLog);
  };
  const disposeTab = tools.Tab.prototype.dispose;
  tools.Tab.prototype.dispose = async function () {
    await this._consoleLog.close?.();
    return disposeTab.call(this);
  };
  const headerSnapshot = tools.Tab.prototype.headerSnapshot;
  tools.Tab.prototype.headerSnapshot = function () {
    if (!this.isCurrentTab() && this.context._runningToolName !== 'browser_tabs')
      return Promise.resolve({...this._lastHeader, url: this.page.url(), current: false, crashed: this.crashed, changed: false});
    return headerSnapshot.call(this);
  };
  for (const tool of tools.browserTools.filter(tool => tool.schema.name.startsWith('browser_network'))) {
    const handle = tool.handle;
    tool.handle = async (context, params, response, signal) => {
      await handle(context, params, response, signal);
      const dropped = context.currentTab()?.droppedRequests;
      if (dropped) response.addTextResult(`Request history limited to 500 entries; ${dropped} older entries discarded.`);
    };
  }
  const initialize = tools.BrowserBackend.prototype.initialize;
  const dispose = tools.BrowserBackend.prototype.dispose;
  tools.BrowserBackend.prototype.initialize = async function (...args) {
    await initialize.apply(this, args);
    const context = this._context;
    // Config is shared by the upstream factory; each session gets its own copy.
    context.config = {...context.config, snapshot: {...context.config.snapshot, mode: 'none'}, webmcp: false,
      timeouts: {...context.config.timeouts, navigation: 45000},
      outputDir: path.join(context.config.outputDir || path.resolve('artifacts'), randomUUID())};
    context.options = {...context.options, config: context.config};
    context.workPages = new Set();
    context.keptPages = new Set();
    const track = page => {
      if (context.workPages.has(page)) return;
      context.workPages.add(page);
      page.once('close', () => { context.workPages.delete(page); context.keptPages.delete(page); });
    };
    const isStarter = page => page.url() === 'about:blank' || page.url().startsWith('chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html');
    this._browserContext.pages().filter(isStarter).forEach(track);
    const ensureTab = context.ensureTab.bind(context);
    let firstTab = true;
    context.ensureTab = async (...args) => {
      const tab = await ensureTab(...args);
      if (firstTab && isStarter(tab.page)) track(tab.page);
      firstTab = false;
      return tab;
    };
    const newTab = context.newTab.bind(context);
    context.newTab = async (...args) => {
      const tab = await newTab(...args);
      track(tab.page);
      return tab;
    };
    this._trackPopup = page => {
      page.opener().then(opener => {
        if (context.workPages.has(opener)) track(page);
      }).catch(error => {
        if (!page.isClosed()) console.error('Cannot track popup:', error.message);
      });
    };
    this._browserContext.on('page', this._trackPopup);
  };
  tools.BrowserBackend.prototype.dispose = async function () {
    if (this._cleanupPromise) return this._cleanupPromise;
    clearTimeout(this._performanceIdleTimer);
    this._cleanupPromise = (async () => {
      if (this._trackPopup) this._browserContext.off('page', this._trackPopup);
      const context = this._context;
      const pages = [...(context?.workPages || [])].filter(page => !page.isClosed() && !context.keptPages.has(page));
      await Promise.allSettled(pages.map(page => page.close({runBeforeUnload: false})));
      await dispose.call(this);
      context?.workPages.clear();
      context?.keptPages.clear();
    })();
    return this._cleanupPromise;
  };
  tools.browserTools.push({
    capability: 'core-tabs',
    schema: {
      name: 'browser_keep_tab', title: 'Keep a report tab', type: 'action',
      description: 'Preserve the current tab after session cleanup or idle expiration. Use for tabs shown to the user. Set keep=false to restore automatic cleanup.',
      inputSchema: z.object({keep: z.boolean().default(true)}),
    },
    handle: async (context, {keep}, response) => {
      const page = (await context.ensureTab()).page;
      if (keep) context.keptPages.add(page);
      else context.keptPages.delete(page);
      response.addTextResult(keep ? 'Current tab will be preserved.' : 'Current work tab will be cleaned up.');
    },
  });
  for (const tool of tools.browserTools) {
    const handle = tool.handle;
    if (tool.schema.type === 'input' || tool.schema.type === 'action') {
      tool.schema.inputSchema = tool.schema.inputSchema.extend({
        waitForSettled: z.boolean().default(false).describe('Opt in to upstream network settling. Prefer an explicit browser_wait_for or awaited promise for required completion.'),
      });
    }
    tool.handle = async (context, params, response, signal) => {
      context.skipCompletionWait = !params.waitForSettled;
      const addResult = response.addResult.bind(response);
      response.addResult = async (title, data, file) => {
        const bytes = typeof data === 'string' ? Buffer.byteLength(data) : data?.length || 0;
        if (bytes > 8 * 1024 * 1024) throw new Error('Result exceeds 8 MiB; narrow the requested data.');
        if (typeof data === 'string' && bytes > 65536 && !file.suggestedFilename) {
          const resolved = await response.resolveClientOutputFile(file, title);
          await response.addFileResult(resolved, data);
          response.addTextResult('Large result saved to file; use a narrower query for inline output.');
        } else await addResult(title, data, file);
      };
      try {
        if (tool.schema.name === 'browser_take_screenshot') {
          const tab = await context.ensureTab();
          if (tab.modalStates().length) throw new Error('Close the page dialog/file chooser before taking a screenshot.');
          const target = params.target && await tab.targetLocator({target: params.target, element: params.element || 'element'});
          const size = target ? await target.locator.boundingBox() : await tab.page.evaluate(full => ({
            width: full ? Math.max(document.documentElement.scrollWidth, innerWidth) : innerWidth,
            height: full ? Math.max(document.documentElement.scrollHeight, innerHeight) : innerHeight,
          }), !!params.fullPage);
          const scale = params.scale === 'device' ? await tab.page.evaluate(() => devicePixelRatio) : 1;
          if (size && size.width * size.height * scale * scale > 8e6)
            throw new Error('Screenshot exceeds 8 million pixels; use a target element or viewport at CSS scale.');
        }
        await handle(context, params, response, signal);
        const tab = context.currentTab();
        if (tab?.droppedEvents) {
          response.addTextResult(`${tab.droppedEvents} older events omitted (limit: 1000).`);
          tab.droppedEvents = 0;
        }
      } finally { context.skipCompletionWait = false; }
    };
  }
  const callTool = tools.BrowserBackend.prototype.callTool;
  const admission = new Admission();
  tools.BrowserBackend.prototype.callTool = async function (...args) {
    if (this._busy) return {isError: true, content: [{type: 'text', text: 'This session already has a running tool; wait for it to finish.'}]};
    this._busy = true;
    clearTimeout(this._performanceIdleTimer);
    try {
      return await admission.run(() => callWithFocus.call(this, ...args), args[2]);
    } catch (error) {
      return {isError: true, content: [{type: 'text', text: error.message || 'Tool cancelled'}]};
    } finally {
      this._busy = false;
      if (!this._disposed) this._performanceIdleTimer = setTimeout(() => {
        void this.dispose().catch(error => console.error('Idle cleanup failed:', error.name));
      }, idleMs).unref();
    }
  };
  async function callWithFocus(...args) {
    const page = this._context?.currentTab()?.page;
    // Extension mode omits default focus emulation. Use its already authorized
    // page session; attaching to the browser target is intentionally forbidden.
    return withPageFocus(page, () => this._context.currentTab()?.modalStates().some(state => state.type === 'dialog'),
      () => callTool.apply(this, args));
  }
}
