'use strict';
const fs = require('node:fs');
const path = '/opt/dsh/container/PLATFORM_GUIDE.md';
function dshPlatformInstructions(instructions) {
  const guide = fs.readFileSync(path, 'utf8').replace(/\r\n/g, '\n');
  if (!guide.startsWith('# DSH shared platform guide\n') || Buffer.byteLength(guide) > 32768)
    throw new Error('Invalid operator platform guide');
  return guide + '\n\n' + (instructions || '');
}
module.exports = {dshPlatformInstructions};
