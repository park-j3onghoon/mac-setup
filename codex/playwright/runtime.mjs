import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
export function loadRuntime() {
  const file = require.resolve('playwright-core/lib/coreBundle');
  const source = readFileSync(file);
  if (createHash('sha256').update(source).digest('hex') !== '9d3260b17408501ba46ca708fa870a7c95e1e3f6e9cc34d799465f17b7d78c50')
    throw new Error('Playwright runtime changed: review the performance adapter before upgrading.');
  return require(file);
}

export function installPerformanceAdapter({tools}) {
  const callTool = tools.BrowserBackend.prototype.callTool;
  tools.BrowserBackend.prototype.callTool = async function (...args) {
    const page = this._context?.currentTab()?.page;
    // Extension mode omits default focus emulation. Use its already authorized
    // page session; attaching to the browser target is intentionally forbidden.
    const client = page && !page.isClosed() && page._connection.toImpl(page).delegate._mainFrameSession._client;
    try {
      if (client) await client.send('Emulation.setFocusEmulationEnabled', {enabled: true});
      return await callTool.apply(this, args);
    } finally {
      if (client && !page.isClosed()) {
        try {
          await client.send('Emulation.setFocusEmulationEnabled', {enabled: false});
        } catch (error) {
          if (!page.isClosed() && this._browserContext.browser()?.isConnected()) throw error;
        }
      }
    }
  };
}
