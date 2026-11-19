const states = new WeakMap();
const clientFor = page => !page.isClosed() && page._connection.toImpl(page).delegate._mainFrameSession._client;

export function releasePageFocus(page) {
  states.get(page)?.cancel?.();
  states.delete(page);
}

export async function withPageFocus(page, hasDialog, action) {
  if (!page || page.isClosed()) return action();
  const state = states.get(page) || {active: 0};
  states.set(page, state);
  state.active++;
  const restore = async () => {
    if (state.active || page.isClosed()) return;
    try { await clientFor(page)?.send('Emulation.setFocusEmulationEnabled', {enabled: false}); }
    catch (error) {
      if (!page.isClosed() && page.context().browser()?.isConnected()) throw error;
    }
  };
  try {
    if (!hasDialog()) await clientFor(page)?.send('Emulation.setFocusEmulationEnabled', {enabled: true});
    return await action();
  } finally {
    state.active--;
    if (hasDialog() && !page.isClosed()) {
      if (!state.deferred) {
        const cancel = () => { page.off('dialogclosed', finish); page.off('close', cancel); state.deferred = false; state.cancel = undefined; };
        const finish = () => {
          cancel();
          void restore().catch(error => console.error('Deferred focus restore failed:', error.name));
        };
        state.deferred = true;
        state.cancel = cancel;
        page.once('dialogclosed', finish);
        page.once('close', cancel);
      }
    } else await restore();
  }
}
