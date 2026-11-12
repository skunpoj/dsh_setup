'use strict';
// ttyd (xterm.js) copies the selection to the clipboard on EVERY selection change (document.execCommand('copy') in its onSelectionChange handler) and has no
// client option to turn that off. This pure helper inserts a small script into ttyd's HTML page that refuses programmatic 'copy' commands, so selecting text
// no longer overwrites the clipboard; copying on purpose (Ctrl+Shift+C, right click, Ctrl+Insert) is the browser's own action and still works.
const GUARD = "<script>(function(){var o=document.execCommand;document.execCommand=function(c){if(String(c).toLowerCase()==='copy')return false;return o.apply(document,arguments)}})()</script>";

function injectCopyGuard(html) {
  if (typeof html !== 'string' || html.includes('document.execCommand=function(c){if(String(c).toLowerCase()===\'copy\')')) return html;   // already guarded
  const head = html.search(/<head[^>]*>/i);
  if (head < 0) return GUARD + html;
  const end = html.indexOf('>', head) + 1;
  return html.slice(0, end) + GUARD + html.slice(end);       // first script in <head>: runs before ttyd's own bundle
}

// Only ttyd's HTML page on the terminal port, only when the operator has not asked to keep the upstream behaviour.
function shouldGuard({ port, method, statusCode, contentType, env = process.env }) {
  return port === 7681 && method === 'GET' && statusCode === 200 && /text\/html/i.test(String(contentType || '')) && env.DSH_TTYD_COPY_ON_SELECT !== '1';
}

module.exports = { injectCopyGuard, shouldGuard, GUARD };
