'use strict';
// Admin "GPU reset" = a REQUEST for the operator's engine restart procedure
// (outputs/ENGINE_RESTART_PROCEDURE_20261110.md). This module never restarts anything:
// it has no cluster client, no child process and no network call. It only
//  - reads a drain snapshot that a separately approved, read-only exporter writes, and
//  - appends an audited request record that the operator reads.
// A restart still needs the user's typed order, the drain check, a notice and a quiet window.
// It addresses only the engine abort leak (a rank's state cache stuck at 100 percent with nothing
// running); it does not fix the 15 s cache-handoff error or the long-context lease wedge, and a
// restart cuts every live session.
//
// Drain snapshot v2 (per rank, from the engine stats lines, NOT /deepinfer/metrics, which counts a
// pending request as running):
//   {version:2, observedAt, ranks:[{rank, running, pending, stateCacheUsagePercent, stateCacheFullSince?}],
//    activeLongRequests:[{requestId, startedAt, lastProgressAt?, promptTokens?}]}
// A rank is STUCK when running 0, pending >= 1, state cache >= 99 percent, and full for >= 10 minutes.
// The stuck rank is left out of the drain check. Every other (healthy) rank must have running 0 and
// pending 0. A long request in flight blocks the request, unless it has made no progress for >= 10
// minutes while a rank is stuck (then it is the request held by the stuck rank, already lost). That exemption needs
// lastProgressAt from the exporter: a long request without it always blocks.
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');

const CONFIRM_PHRASE = 'REQUEST ENGINE RESTART';
const MAX_SNAPSHOT_AGE_MS = 60_000;
const STUCK_MIN_MS = 10 * 60_000;
const STUCK_CACHE_PERCENT = 99;
const REQUEST_TTL_MS = 15 * 60_000;  // a request is a pointer for the operator, never a standing order
// Wed 11 Nov 2026 17:00-20:30 ICT (UTC+7) = 10:00-13:30 UTC: no restart, so no request either.
const DEFAULT_BLACKOUTS = [['2026-11-11T10:00:00Z', '2026-11-11T13:30:00Z']];

function blackouts(env = process.env) {
  if (!env.DSH_ENGINE_RESTART_BLACKOUTS) return DEFAULT_BLACKOUTS;
  const value = JSON.parse(env.DSH_ENGINE_RESTART_BLACKOUTS);
  if (!Array.isArray(value) || !value.every(w => Array.isArray(w) && w.length === 2 && w.every(x => Number.isFinite(Date.parse(x)))))
    throw Error('Invalid restart blackout windows');
  return value;
}

function readSnapshot(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

// The snapshot plus the sha256 of the exact bytes evaluated, so a request names the drain evidence it was made on.
function readSnapshotWithHash(file) {
  try {
    const raw = fs.readFileSync(file);
    return {snapshot: JSON.parse(raw.toString('utf8')), sha256: crypto.createHash('sha256').update(raw).digest('hex')};
  } catch { return {snapshot: null, sha256: null}; }
}

const count = v => Number.isInteger(v) && v >= 0;
const time = v => typeof v === 'string' && Number.isFinite(Date.parse(v)) ? Date.parse(v) : null;

function parseRanks(list) {
  if (!Array.isArray(list) || !list.length || list.length > 64) return null;
  const seen = new Set(), ranks = [];
  for (const r of list) {
    if (!r || !count(r.rank) || seen.has(r.rank) || !count(r.running) || !count(r.pending)) return null;
    const cache = r.stateCacheUsagePercent;
    if (typeof cache !== 'number' || !Number.isFinite(cache) || cache < 0 || cache > 100) return null;
    if (r.stateCacheFullSince !== undefined && time(r.stateCacheFullSince) === null) return null;
    seen.add(r.rank);
    ranks.push({rank: r.rank, running: r.running, pending: r.pending, stateCacheUsagePercent: cache,
      stateCacheFullSince: r.stateCacheFullSince === undefined ? null : new Date(time(r.stateCacheFullSince)).toISOString()});
  }
  return ranks.sort((a, b) => a.rank - b.rank);
}

function parseLong(list) {
  if (!Array.isArray(list) || list.length > 200) return null;
  const out = [];
  for (const r of list) {
    if (!r || typeof r.requestId !== 'string' || time(r.startedAt) === null) return null;
    if (r.lastProgressAt !== undefined && time(r.lastProgressAt) === null) return null;
    out.push({requestId: r.requestId.slice(0, 80), startedAt: new Date(time(r.startedAt)).toISOString(),
      lastProgressAt: r.lastProgressAt === undefined ? null : new Date(time(r.lastProgressAt)).toISOString(),
      promptTokens: count(r.promptTokens) ? r.promptTokens : null});
  }
  return out;
}

// Returns {allowed, reason, observedAt, ranks, stuckRanks, activeLongRequests, stalledLongRequests}; refuses on any doubt.
function evaluate(snapshot, now = Date.now(), windows = DEFAULT_BLACKOUTS) {
  const base = {allowed: false, observedAt: null, ranks: [], stuckRanks: [], activeLongRequests: [], stalledLongRequests: []};
  const blocked = windows.find(([a, b]) => now >= Date.parse(a) && now < Date.parse(b));
  if (blocked) return {...base, reason: 'Inside a no-restart window (' + blocked[0] + ' to ' + blocked[1] + ').'};
  if (!snapshot || typeof snapshot !== 'object') return {...base, reason: 'No drain snapshot is available; the drain check cannot be shown.'};
  const observed = time(snapshot.observedAt);
  if (observed === null) return {...base, reason: 'The drain snapshot has no valid observation time.'};
  const view = {...base, observedAt: new Date(observed).toISOString()};
  if (now - observed > MAX_SNAPSHOT_AGE_MS || observed - now > 5_000) return {...view, reason: 'The drain snapshot is older than 60 seconds.'};
  if (snapshot.version !== 2) return {...view, reason: 'The drain snapshot is not the per-rank version 2 format.'};
  const ranks = parseRanks(snapshot.ranks), long = parseLong(snapshot.activeLongRequests);
  if (!ranks || !long) return {...view, reason: 'The drain snapshot is incomplete or malformed.'};
  const isStuck = r => r.running === 0 && r.pending > 0 && r.stateCacheUsagePercent >= STUCK_CACHE_PERCENT &&
    r.stateCacheFullSince !== null && now - Date.parse(r.stateCacheFullSince) >= STUCK_MIN_MS;
  const stuckRanks = ranks.filter(isStuck).map(r => r.rank);
  const healthy = ranks.filter(r => !stuckRanks.includes(r.rank));
  // A long request with no progress for >= 10 min while a rank is stuck is the one the stuck rank holds.
  const stalled = r => stuckRanks.length > 0 && r.lastProgressAt !== null && now - Date.parse(r.lastProgressAt) >= STUCK_MIN_MS;
  const stalledLongRequests = long.filter(stalled), activeLongRequests = long.filter(r => !stalled(r));
  const full = {...view, ranks, stuckRanks, activeLongRequests, stalledLongRequests};
  if (activeLongRequests.length) return {...full, reason: activeLongRequests.length + ' long request(s) are in flight; a restart would cut them.'};
  const busy = healthy.filter(r => r.running > 0 || r.pending > 0);
  if (busy.length) return {...full, reason: 'Healthy rank(s) ' + busy.map(r => r.rank + ' (running ' + r.running + ', pending ' + r.pending + ')').join(', ') + ' are serving requests; a restart would cut them.'};
  if (!stuckRanks.length) return {...full, reason: 'No rank is stuck (running 0, pending 1 or more, state cache at 99 percent or more for 10 minutes); a restart is not justified.'};
  return {...full, allowed: true, reason: 'Rank(s) ' + stuckRanks.join(', ') + ' stuck; every healthy rank idle; no live long request.'};
}

function readRequests(file) {
  try { return fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map(line => JSON.parse(line)); } catch { return []; }
}

const sortedRanks = a => Array.isArray(a) ? [...a].sort((x, y) => x - y) : null;
const sameRanks = (a, b) => { const x = sortedRanks(a), y = sortedRanks(b); return !!x && !!y && x.length === y.length && x.every((v, i) => v === y[i]); };

function lastRequest(file, now = Date.now()) {
  const rows = readRequests(file), last = rows.length ? rows[rows.length - 1] : null;
  if (!last) return null;
  const expires = Date.parse(last.expiresAt);
  return {requestedAt: last.requestedAt, requestedBy: last.requestedBy, status: last.status, expiresAt: last.expiresAt || null,
    expired: !Number.isFinite(expires) || now >= expires, stuckRanks: Array.isArray(last.stuckRanks) ? last.stuckRanks : [],
    drainSnapshotSha256: last.drainSnapshotSha256 || null};
}

// An unexpired request for the same stuck ranks already exists: refuse a duplicate instead of appending another row.
function openRequestFor(file, stuckRanks, now = Date.now()) {
  return readRequests(file).find(r => r.status === 'requested' && Number.isFinite(Date.parse(r.expiresAt)) && now < Date.parse(r.expiresAt) && sameRanks(r.stuckRanks, stuckRanks)) || null;
}

function appendRequest(file, record) {
  fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
  fs.appendFileSync(file, JSON.stringify(record) + '\n', {mode: 0o600});
}

module.exports = {CONFIRM_PHRASE, MAX_SNAPSHOT_AGE_MS, STUCK_MIN_MS, STUCK_CACHE_PERCENT, REQUEST_TTL_MS, DEFAULT_BLACKOUTS, blackouts, readSnapshot, readSnapshotWithHash, evaluate, lastRequest, openRequestFor, appendRequest};
