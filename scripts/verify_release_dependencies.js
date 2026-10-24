// Bind the reviewed SDK to the dependency actually resolved by DSH's adapter.
// This reads installed metadata only; it never imports a provider or calls it.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {findPackageJSON} = require('node:module');
const {pathToFileURL} = require('node:url');
const root = process.env.DSH_PACKAGE_DIR || '/usr/local/lib/node_modules/@deepseek-ai/dsh';
const [expectedDSH, expectedSDK] = process.argv.slice(2);
assert(expectedDSH && expectedSDK, 'Expected DSH and SDK versions are required');
const metadata = file => JSON.parse(fs.readFileSync(file, 'utf8'));
assert.equal(metadata(path.join(root, 'package.json')).version, expectedDSH, 'DSH release differs');
const adapter = path.join(root, 'node_modules/@deepseek-ai/dsh-llm-pi-ai');
// The SDK is import-only. Resolve metadata with Node's ESM package resolver,
// rather than requiring its entry point or assuming a hoisted installation.
const sdkFile = findPackageJSON('@earendil-works/pi-ai', pathToFileURL(path.join(adapter, 'package.json')));
assert(sdkFile, 'Resolved SDK metadata missing');
const sdk = metadata(sdkFile);
assert.equal(sdk.name, '@earendil-works/pi-ai');
assert.equal(sdk.version, expectedSDK, 'Adapter resolves an unreviewed SDK release');
assert.equal(path.resolve(sdkFile), path.join(path.resolve(root), 'node_modules/@earendil-works/pi-ai/package.json'), 'Resolved SDK differs from the managed loader target');
console.log(JSON.stringify({installedDSH: expectedDSH, adapterSDK: sdk.version, adapterResolutionVerified: true, loaderTargetVerified: true, providerImported: false}));
