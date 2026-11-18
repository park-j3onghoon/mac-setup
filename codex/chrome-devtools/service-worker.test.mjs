import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync, spawnSync} from 'node:child_process';
import {test} from 'node:test';
import {pathToFileURL} from 'node:url';
import {version} from './runtime.mjs';

const executable = execFileSync('/opt/homebrew/bin/npx', [
  '--yes', `--package=chrome-devtools-mcp@${version}`, '--', 'which', 'chrome-devtools-mcp',
], {encoding: 'utf8', timeout: 45000}).trim();
const collectorUrl = pathToFileURL(path.resolve(
  path.dirname(fs.realpathSync(executable)), '../collectors/ServiceWorkerCollector.js',
)).href;
const runtimeUrl = new URL('./runtime.mjs', import.meta.url).href;

function scenario(name) {
  return spawnSync(process.execPath, ['--input-type=module', '-e', `
    import assert from 'node:assert/strict';
    import {EventEmitter} from 'node:events';
    import {setImmediate} from 'node:timers/promises';
    import {loadUpstream} from ${JSON.stringify(runtimeUrl)};
    import {ServiceWorkerSubscriber, ServiceWorkerConsoleCollector} from ${JSON.stringify(collectorUrl)};

    await loadUpstream();
    const name = process.argv[1];
    const worker = new EventEmitter();
    let detached = false;
    let finishSubscribe;
    const subscribed = new Promise(resolve => { finishSubscribe = resolve; });
    const failure = new Error('Unexpected transport failure');
    const session = Object.assign(new EventEmitter(), {
      async send() {},
      async detach() {
        if (name === 'unexpected_error') throw failure;
        if (detached) {
          throw new Error('Session already detached. Most likely the service_worker has been closed.');
        }
        detached = true;
      },
    });
    const target = {
      url: () => 'chrome-extension://test-extension/worker.js',
      type: () => 'service_worker',
      createCDPSession: async () => session,
      async worker() { finishSubscribe(); return worker; },
    };

    if (name === 'destroyed_target') {
      const browser = new EventEmitter();
      const collector = new ServiceWorkerConsoleCollector(browser);
      await collector.init([]);
      browser.emit('targetcreated', target);
      await subscribed;
      await setImmediate();
      assert.equal(worker.listenerCount('console'), 1);

      detached = true;
      browser.emit('targetdestroyed', target);
      await setImmediate();

      assert.equal(worker.listenerCount('console'), 0);
      collector.dispose();
    } else {
      const subscriber = new ServiceWorkerSubscriber(target, () => {});
      await subscriber.subscribe();
      if (name === 'unexpected_error') {
        await assert.rejects(subscriber.unsubscribe(), error => error === failure);
      } else {
        await subscriber.unsubscribe();
        if (name === 'repeated_unsubscribe') await subscriber.unsubscribe();
        assert.equal(detached, true);
        assert.equal(worker.listenerCount('console'), 0);
      }
    }
  `, name], {encoding: 'utf8', timeout: 60000});
}

for (const name of ['destroyed_target', 'repeated_unsubscribe', 'live_session', 'unexpected_error']) {
  test(name, () => {
    const result = scenario(name);
    assert.equal(result.status, 0, result.error?.message ?? result.stderr);
  });
}
