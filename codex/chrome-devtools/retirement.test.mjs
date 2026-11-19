import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import {once} from 'node:events';
import {retireWhenIdle} from './retirement.mjs';

test('retirement keeps active connections alive and shuts down after drain', async () => {
  const server = net.createServer(socket => socket.on('data', data => socket.write(data)));
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const client = net.connect(server.address().port, '127.0.0.1');
  await once(client, 'connect');
  let stopped = false;
  const watcher = retireWhenIdle(server, () => { stopped = true; }, 10);
  try {
    await new Promise(resolve => setTimeout(resolve, 30));
    assert(!stopped);
    client.write('still working');
    assert.equal((await once(client, 'data'))[0].toString(), 'still working');
    client.end();
    await once(server, 'close');
    await new Promise(resolve => setImmediate(resolve));
    assert(stopped);
  } finally { watcher.cancel(); client.destroy(); if (server.listening) server.close(); }
});
