'use strict';
const fs = require('node:fs');
const path = require('node:path');
const css = fs.readFileSync(path.join(__dirname, 'bot_platform.css'), 'utf8');
function platformTheme(html) {
  if (html.includes('id="bot-platform-theme"')) return html;
  const style = '<style id="bot-platform-theme">'+css+'</style>';
  return /<\/head>/i.test(html) ? html.replace(/<\/head>/i, style+'</head>') : html.replace(/<\/style>/i, '</style>'+style);
}
module.exports = { platformTheme };
