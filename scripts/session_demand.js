'use strict';
// First come, first reserved. The gateway has no Kubernetes token: it only
// publishes which private runtimes signed-in users are actively using. The
// capacity controller starts a demanded runtime when resources allow and
// stops one after the idle timeout. Files and histories always stay.
const path = require('path');
const {readJSON, atomicJSON} = require('./capacity_policy');
const RUNTIME = /^dsh-u-[0-9a-f]{16}-(secure|internet)$/;
// Spawn stages published by the controller (capacity_session.STAGES plus failed).
const STAGES = ['queued', 'scheduling', 'preparing', 'pulling-image', 'starting-containers', 'starting-dsh', 'ready', 'failed'];
const STALE_MS = 90000;

function runtimeName(target) {
  const name = String(target?.host || '').split('.')[0];
  return RUNTIME.test(name) ? name : null;
}

function createSessionDemand({root, now = () => Date.now()}) {
  if (!path.isAbsolute(root)) throw Error('Invalid capacity root');
  const file = path.join(root, 'policy', 'demand.json');
  const demand = new Map();
  const sockets = new Set();
  let seeded = false;
  // Survive a gateway restart without stopping users who were working.
  try {
    const saved = readJSON(file);
    for (const [name, entry] of Object.entries(saved.runtimes || {})) {
      const requested = Date.parse(entry.requestedAt), active = Date.parse(entry.lastActivityAt);
      if (RUNTIME.test(name) && Number.isFinite(requested) && Number.isFinite(active)) demand.set(name, {requestedAt: requested, lastActivityAt: active});
    }
    seeded = true;
  } catch {}

  function touch(target) {
    const name = runtimeName(target);
    if (!name) return null;
    const t = now(), entry = demand.get(name);
    if (!entry) demand.set(name, {requestedAt: t, lastActivityAt: t});
    else entry.lastActivityAt = Math.max(entry.lastActivityAt, t);
    return name;
  }
  // Only bytes sent by the user's browser count as activity. Reading the
  // counter never changes how the proxied socket flows.
  function watch(socket, target) {
    if (runtimeName(target)) sockets.add({socket, target, read: socket.bytesRead || 0});
  }
  function release(targets) {
    for (const target of targets) {
      const name = runtimeName(target);
      if (name) demand.delete(name);
    }
  }
  function flush(idleMs) {
    for (const item of sockets) {
      if (item.socket.destroyed) { sockets.delete(item); continue; }
      const read = item.socket.bytesRead || 0;
      if (read > item.read) { item.read = read; touch(item.target); }
    }
    const t = now();
    for (const [name, entry] of demand) if (t - entry.lastActivityAt > idleMs) demand.delete(name);
    const iso = v => new Date(v).toISOString();
    atomicJSON(file, {version: 1, observedAt: iso(t),
      runtimes: Object.fromEntries([...demand].map(([n, e]) => [n, {requestedAt: iso(e.requestedAt), lastActivityAt: iso(e.lastActivityAt)}]))});
  }
  function snapshot() {
    try {
      const s = readJSON(path.join(root, 'inventory', 'sessions.json'), 262144);
      const age = now() - Date.parse(s.observedAt);
      if (s.available !== true || !Number.isFinite(age) || age < -5000 || age >= STALE_MS) return null;
      return s;
    } catch { return null; }
  }
  // 'unknown' and 'unmanaged' fail open: the gateway proxies as before, so a
  // controller outage never locks out a user whose runtime is already up.
  function state(target) {
    const name = runtimeName(target);
    if (!name) return {state: 'unmanaged'};
    const s = snapshot(), r = s?.runtimes?.[name];
    if (!r || typeof r.state !== 'string') return {state: 'unknown'};
    const out = {state: r.state};
    if (Number.isSafeInteger(r.position) && r.position > 0) out.position = r.position;
    const p = r.progress;
    if (p && STAGES.includes(p.stage) && Number.isSafeInteger(p.percent) && p.percent >= 0 && p.percent <= 100)
      out.progress = {stage: p.stage, percent: p.percent, detail: typeof p.detail === 'string' ? p.detail.slice(0, 120) : ''};
    return out;
  }
  return {touch, watch, release, flush, state, snapshot, seeded: () => seeded};
}

const finite = v => Number.isFinite(v) && v >= 0;
const percent = (part, whole) => finite(part) && finite(whole) && whole > 0 ? Math.min(100, Math.round(100 * part / whole)) : null;

// Aggregate only: no user names, hosts or runtime identities leave the gateway.
function publicStatus(sessions, capacityStatus, now = Date.now()) {
  const out = {observedAt: new Date(now).toISOString(), available: false,
    policy: 'Shared resources, first come first served. A workspace starts when you sign in and resources allow, and stops after a period without activity. Your files are always kept.'};
  if (sessions?.summary) {
    const s = sessions.summary;
    out.available = true;
    out.workspaces = {running: s.running, starting: s.starting, waiting: s.waiting, stopped: s.stopped};
    out.startsAvailableNow = s.startsAvailable;
    // Concurrent capacity right now: in use plus what can still start.
    if ([s.running, s.starting, s.startsAvailable].every(Number.isSafeInteger))
      out.workspaces.capacity = s.running + s.starting + s.startsAvailable;
    out.idleTimeoutMinutes = Number.isSafeInteger(s.idleTimeoutSeconds) ? Math.round(s.idleTimeoutSeconds / 60) : null;
  }
  const usage = capacityStatus?.capacity?.observedUsage, rows = capacityStatus?.capacity?.resources;
  const round = (v, d = 1) => finite(v) ? Math.round(v * 10 ** d) / 10 ** d : null;
  if (usage && Array.isArray(rows)) {
    const cpu = rows.find(r => r.resource === 'cpu'), memory = rows.find(r => r.resource === 'memoryGiB');
    if (cpu && memory) {
      const cpuTotal = finite(usage.cpuAllocatable) ? usage.cpuAllocatable : cpu.available + Math.max(usage.reservedCPU, usage.cpu);
      const memoryTotal = finite(usage.memoryGiBAllocatable) ? usage.memoryGiBAllocatable : memory.available + Math.max(usage.reservedMemoryGiB, usage.memoryGiB);
      out.cpu = {totalCores: round(cpuTotal), reservedCores: round(usage.reservedCPU), usedCores: round(usage.cpu),
        reservedPercent: percent(usage.reservedCPU, cpuTotal), usedPercent: percent(usage.cpu, cpuTotal)};
      out.memory = {totalGiB: round(memoryTotal, 0), reservedGiB: round(usage.reservedMemoryGiB, 0), usedGiB: round(usage.memoryGiB, 0),
        reservedPercent: percent(usage.reservedMemoryGiB, memoryTotal), usedPercent: percent(usage.memoryGiB, memoryTotal)};
    }
    if (finite(usage.gpuAllocatable) && usage.gpuAllocatable > 0 && finite(usage.gpuRequested))
      out.gpu = {total: usage.gpuAllocatable, allocated: usage.gpuRequested, allocatedPercent: percent(usage.gpuRequested, usage.gpuAllocatable)};
  }
  return out;
}

module.exports = {createSessionDemand, publicStatus, runtimeName};
