// DSH 0.2.1-rc.2: public theme/configForms APIs only. No DOM or credential access.
export const CUSTOM_ID = 'custom-light';
export const STORAGE_KEY = 'dsh-theme-custom-light/selection/v1';
const NATIVE = new Set(['light', 'dark', 'system']);
export function createThemeController({theme, nativeForm, onThemeChange, storage, enqueue = queueMicrotask}) {
  let disposed = false, queued = false, persistenceError = !storage;
  let custom = false;
  let fallback = NATIVE.has(theme.getTheme().preference) ? theme.getTheme().preference : 'system';
  try { const value = JSON.parse(storage?.getItem(STORAGE_KEY) || 'null');
    if (value?.version === 1 && value.custom === true && NATIVE.has(value.fallback)) {
      custom = true; fallback = value.fallback;
    }
  } catch { persistenceError = true; }
  const listeners = new Set();
  const notify = () => { for (const listener of [...listeners]) listener(); };
  const persist = () => {
    try { storage?.setItem(STORAGE_KEY, JSON.stringify({version:1, custom, fallback})); }
    catch { persistenceError = true; }
  };
  const restore = () => {
    queued = false;
    if (disposed || !custom) return;
    const current = theme.getTheme().preference;
    // A foreign registered custom theme has its own owner; never fight it.
    if (!NATIVE.has(current) && current !== CUSTOM_ID) { custom = false; persist(); notify(); return; }
    if (current !== CUSTOM_ID) theme.setTheme(CUSTOM_ID);
    notify();
  };
  const scheduleRestore = () => { if (!queued) { queued = true; enqueue(restore); } };
  const off = onThemeChange(() => {
    // Host settings adoption may restore its built-in id after fonts or initial load.
    // Defer so all subscribers finish the old event before the custom snapshot emits.
    if (custom && theme.getTheme().preference !== CUSTOM_ID) scheduleRestore();
    notify();
  });
  if (custom) scheduleRestore();
  return {
    getSnapshot: () => ({preference:theme.getTheme().preference, custom, persistenceError}),
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    choose(id) {
      if (disposed) throw new Error('theme controller is disposed');
      if (id !== CUSTOM_ID && !NATIVE.has(id)) throw new Error('unknown appearance option');
      if (id === CUSTOM_ID) {
        if (!custom) {
          const current = theme.getTheme().preference;
          if (NATIVE.has(current)) fallback = current;
        }
        custom = true;
      } else { custom = false; fallback = id; }
      persist(); theme.setTheme(id); notify();
    },
    dispose() {
      if (disposed) return;
      disposed = true; off(); listeners.clear();
      if (theme.getTheme().preference === CUSTOM_ID) {
        const native = nativeForm?.getSnapshot().value?.preference;
        theme.setTheme(NATIVE.has(native) ? native : fallback);
      }
    }
  };
}
