import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
const policy = JSON.parse(fs.readFileSync('/etc/claude-code/managed-settings.json'));
assert.deepEqual(policy.allowedProviders, ['customEndpoint']);
assert.deepEqual(policy.availableModels, ['deepseek-v4.1-flash']);
assert.equal(policy.enforceAvailableModels, true);
assert.equal(policy.model, 'deepseek-v4.1-flash');
assert.equal(policy.env.API_TIMEOUT_MS, '3600000');
assert.equal(policy.env.ANTHROPIC_CUSTOM_MODEL_OPTION, 'deepseek-v4.1-flash');
// Retries are NOT pinned in the policy: interactive Claude keeps its normal retry; dsh-unattended sets both for unattended tasks (its guard refuses replays).
assert.equal(policy.env.CLAUDE_CODE_MAX_RETRIES, undefined);
assert.equal(policy.env.CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK, undefined);
// The managed policy pins the ONE canonical LiteLLM gateway Service. dsh-unattended.py (claude_managed_pin) fails closed for a provider-restricted policy without a pin and
// routes unattended Claude through the guard's proxy listener (HTTP_PROXY) while the pin stays the endpoint name; the same value gives interactive Claude its endpoint.
assert.equal(policy.env.ANTHROPIC_BASE_URL, 'http://litellm-gateway.llm.svc.cluster.local:4000');
assert.ok(!Object.keys(policy.env).some((name) => name.toUpperCase().includes('PROXY')), 'the policy pins an endpoint, never a proxy');
assert.equal(policy.availableModelsMatch, 'exact');
// The banking gate hook is installed for every session but acts only when DSH_BANKING_GATE=1 (set by dsh-unattended --banking-gate for an admitted banking task).
assert.equal(policy.hooks.PreToolUse.length, 1);
assert.equal(policy.hooks.PreToolUse[0].matcher, '*');
assert.equal(policy.hooks.PreToolUse[0].hooks[0].command, '/usr/local/bin/node /opt/dsh/container/dsh-banking-gate.cjs');
assert.equal(policy.hooks.PostToolUse[0].matcher, 'Write|Edit|MultiEdit');
assert.equal(policy.hooks.PostToolUse[0].hooks[0].command, '/usr/local/bin/node /opt/dsh/container/dsh-banking-gate.cjs');
assert.equal(policy.env.NODE_TLS_REJECT_UNAUTHORIZED, undefined);
const source = fs.readFileSync('/usr/local/lib/node_modules/@truefoundry/trueforge/dist/main.js','utf8');
assert.ok(source.includes('const modelProviderStore = managedStore();'));
assert.ok(source.includes('Model configuration is operator managed'));
assert.match(execFileSync('claude', ['--version'], {encoding:'utf8'}), /2\.1\.301/);
assert.match(execFileSync('trueforge', ['--help'], {encoding:'utf8'}), /0\.179\.2/);
console.log('Pinned harness versions and operator-owned configuration verified.');
