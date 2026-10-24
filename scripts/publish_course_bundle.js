'use strict';

// Offline data publisher. Never points at the auth/workspace volume or serves HTTP.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { readManifest, openMember } = require('./course_files');

function verifyGeneration(root, sha256) {
  const files = readManifest({ root, sha256 });
  const expected = new Set(['.course-manifest.json', ...Object.keys(files)]);
  const directories = new Set(['']);
  for (const name of expected) {
    let parent = path.posix.dirname(name);
    while (parent !== '.') { directories.add(parent); parent = path.posix.dirname(parent); }
  }
  if (directories.size > 4096) throw Error('Generation directory count exceeds bound');
  const pending = ['']; let seenFiles = 0, seenDirs = 0;
  while (pending.length) {
    const relative = pending.pop(), directory = path.join(root, relative);
    const info = fs.lstatSync(directory);
    if (!directories.has(relative) || !info.isDirectory() || info.uid !== 0 || (info.mode & 0o222)) throw Error('Unexpected or writable generation directory');
    if (++seenDirs > directories.size) throw Error('Generation directory inventory differs');
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const name = relative ? relative + '/' + entry.name : entry.name;
      if (entry.isDirectory()) pending.push(name);
      else if (!entry.isFile() || !expected.has(name) || ++seenFiles > expected.size) throw Error('Unexpected generation entry');
    }
  }
  if (seenFiles !== expected.size || seenDirs !== directories.size) throw Error('Incomplete generation inventory');
  const buffer = Buffer.alloc(1024 * 1024); let total = 0;
  for (const [name, item] of Object.entries(files)) {
    const fd = openMember(root, name.split('/'));
    try {
      const before = fs.fstatSync(fd, { bigint: true });
      if (before.size !== BigInt(item.bytes)) throw Error('Existing asset size differs');
      const hash = crypto.createHash('sha256'); let offset = 0;
      while (offset < item.bytes) {
        const count = fs.readSync(fd, buffer, 0, Math.min(buffer.length, item.bytes - offset), offset);
        if (!count) throw Error('Existing asset truncated');
        hash.update(buffer.subarray(0, count)); offset += count;
      }
      const after = fs.fstatSync(fd, { bigint: true });
      if (hash.digest('hex') !== item.sha256 || ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs'].some(key => before[key] !== after[key])) throw Error('Existing asset differs or changed');
      total += item.bytes;
    } finally { fs.closeSync(fd); }
  }
  return { manifest_sha256: sha256, files: Object.keys(files).length, bytes: total, destination: root, existing_generation_verified: true };
}

function publish({ source, sha256, destination }) {
  if (process.platform !== 'linux' || process.getuid() !== 0) throw Error('Root-owned Linux publication required');
  if (!path.isAbsolute(destination) || path.resolve(destination) !== destination) throw Error('Absolute generation destination required');
  const parent = path.dirname(destination), parentInfo = fs.lstatSync(parent);
  if (!parentInfo.isDirectory() || parentInfo.uid !== 0 || (parentInfo.mode & 0o022) || fs.realpathSync(parent) !== parent) throw Error('Private root-owned publication parent required');
  if (fs.existsSync(destination)) return verifyGeneration(destination, sha256);
  const files = readManifest({ root: source, sha256 });
  fs.mkdirSync(destination, { mode: 0o700 }); // Exclusive generation claim; concurrent publishers fail.
  const claim = fs.lstatSync(destination, { bigint: true });
  const stage = fs.mkdtempSync(path.join(parent, '.course-stage-'));
  const buffer = Buffer.alloc(1024 * 1024);
  let total = 0;
  for (const [name, item] of Object.entries(files)) {
    total += item.bytes;
    if (total > 2 * 1024 ** 3) throw Error('Course generation exceeds 2 GiB publication ceiling');
    const fd = openMember(source, name.split('/'));
    const target = path.join(stage, name);
    fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
    let output;
    try {
      output = fs.openSync(target, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o444);
      const digest = crypto.createHash('sha256'); let offset = 0;
      while (true) {
        const size = fs.readSync(fd, buffer, 0, buffer.length, offset);
        if (!size) break;
        offset += size;
        if (offset > item.bytes) throw Error('Source exceeds approved size');
        digest.update(buffer.subarray(0, size));
        let written = 0;
        while (written < size) written += fs.writeSync(output, buffer, written, size - written);
      }
      if (offset !== item.bytes || digest.digest('hex') !== item.sha256) throw Error('Source hash/size differs');
      fs.fchmodSync(output, 0o444); fs.fsyncSync(output);
    } finally { fs.closeSync(fd); if (output !== undefined) fs.closeSync(output); }
  }
  const manifestFd = openMember(source, ['.course-manifest.json']);
  try { fs.copyFileSync(`/proc/self/fd/${manifestFd}`, path.join(stage, '.course-manifest.json'), fs.constants.COPYFILE_EXCL); }
  finally { fs.closeSync(manifestFd); }
  fs.chmodSync(path.join(stage, '.course-manifest.json'), 0o444);
  const dirs = [stage];
  for (let i = 0; i < dirs.length; i++) for (const item of fs.readdirSync(dirs[i], { withFileTypes: true })) if (item.isDirectory()) dirs.push(path.join(dirs[i], item.name));
  for (const dir of dirs.reverse()) fs.chmodSync(dir, 0o555);
  // Read back the exact metadata before making this generation addressable.
  readManifest({ root: stage, sha256 });
  const current = fs.lstatSync(destination, { bigint: true });
  if (current.dev !== claim.dev || current.ino !== claim.ino || !current.isDirectory() || fs.readdirSync(destination).length) throw Error('Generation claim changed');
  fs.renameSync(stage, destination);
  return { manifest_sha256: sha256, files: Object.keys(files).length, bytes: total, destination, existing_generation_verified: false };
}
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length !== 3) throw Error('Usage: node publish_course_bundle.js SOURCE MANIFEST_SHA256 NEW_ABSOLUTE_GENERATION');
  console.log(JSON.stringify(publish({ source: args[0], sha256: args[1], destination: args[2] })));
}
module.exports = { publish, verifyGeneration };
