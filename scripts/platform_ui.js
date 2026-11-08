'use strict';
const fs = require('node:fs');
const path = require('node:path');
const css = fs.readFileSync(path.join(__dirname, 'bot_platform.css'), 'utf8');
// Neutral product mark (shield with three linked nodes, currentColor); no organisation logo or name.
const MARK_SVG = "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 32 32\" fill=\"none\"><path d=\"M16 3.5 26.5 7.5v7.6c0 6.4-4.4 11.3-10.5 13.4C9.9 26.4 5.5 21.5 5.5 15.1V7.5L16 3.5Z\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"/><path d=\"M11.5 13.5h9M11.5 13.5 16 20.5M20.5 13.5 16 20.5\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\"/><circle cx=\"11.5\" cy=\"13.5\" r=\"2.3\" fill=\"currentColor\"/><circle cx=\"20.5\" cy=\"13.5\" r=\"2.3\" fill=\"currentColor\"/><circle cx=\"16\" cy=\"20.5\" r=\"2.3\" fill=\"currentColor\"/></svg>";
const mark = '<span class="gh-brand">' + MARK_SVG + '<span>Governed Harness</span></span>';
// Gateway pages that carry their own light/dark design (the sign-in page) opt out of this theme.
const SELF_THEMED = /<html[^>]*\sdata-self-themed=/i;
// Other gateway pages (credentials) get a neutral brand bar.
function brand(html) {
  if (html.includes('class="gh-brand"')) return html;
  return html.replace(/<body([^>]*)>/i, '<body$1><div class="bot-brand-bar">' + mark + '</div>');
}
function platformTheme(html) {
  if (SELF_THEMED.test(html) || html.includes('id="bot-platform-theme"')) return html;
  const style = '<style id="bot-platform-theme">'+css+'</style>';
  const themed = /<\/head>/i.test(html) ? html.replace(/<\/head>/i, style+'</head>') : html.replace(/<\/style>/i, '</style>'+style);
  return brand(themed);
}
module.exports = { platformTheme };
