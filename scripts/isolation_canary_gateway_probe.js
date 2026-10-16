// Runs only in the disposable gateway. Never emits passwords, cookies or launch tokens.
const fs = require('fs');
const http = require('http');
const crypto = require('crypto');
const WebSocket = require(require.resolve('ws', {paths: ['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
const identities = JSON.parse(fs.readFileSync('/test-identities/users.json', 'utf8'));
const stateFile = '/auth/isolation-state.json';
const host = 'dsh-isolation.test';
const phase = process.argv[2];
const assert = (condition, message) => { if (!condition) throw new Error(message); };

function request(method, path, body = '', cookie = '', headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({host: '127.0.0.1', port: 3080, method, path,
      headers: {host, cookie, 'content-type': 'application/x-www-form-urlencoded',
        'content-length': Buffer.byteLength(body), ...headers}}, res => {
      let text = '';
      res.on('data', b => text += b);
      res.on('end', () => resolve({status: res.statusCode, text,
        cookie: (res.headers['set-cookie'] || []).map(x => x.split(';')[0]).join('; ')}));
    });
    req.setTimeout(30000, () => req.destroy(new Error('Synthetic HTTP test timeout')));
    req.on('error', reject);
    req.end(body);
  });
}

async function rpc(cookie, method, args) {
  const body = {type: 'client-request', rpcId: crypto.randomUUID(), method, payload: {args}};
  const res = await request('POST', '/api/' + method, JSON.stringify(body), cookie, {'content-type': 'application/json'});
  try { return JSON.parse(res.text); }
  catch { throw new Error('RPC did not return JSON: ' + method + ' HTTP ' + res.status); }
}

function value(r, method) {
  assert(r.result?.ok === true, method + ' failed: ' + JSON.stringify(r.result?.error || r.error || {}));
  return r.result.value;
}

function terminal(cookie, marker) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket('ws://127.0.0.1:3080/proxy/7681/ws', 'tty',
      {headers: {Host: host, Cookie: cookie, Origin: 'https://' + host, 'x-dsh-user': 'spoofed_other_user'}});
    let output = '';
    const timer = setTimeout(() => { ws.terminate(); reject(new Error('Terminal command did not return its own private marker')); }, 20000);
    ws.on('open', () => {
      ws.send(JSON.stringify({AuthToken: '', columns: 100, rows: 24}));
      setTimeout(() => ws.send('0cat /workspace/private-report.txt; printf "\\nUID=%s\\n" "$(id -u)"\r'), 500);
    });
    ws.on('message', data => {
      if (data[0] !== 48) return;
      output += data.subarray(1).toString();
      // Neither the marker contents nor UID 10001 is present in the sent command.
      if (output.includes(marker) && output.includes('UID=10001')) {
        clearTimeout(timer); ws.send('0exit\r'); ws.close(); resolve(true);
      }
    });
    ws.on('error', error => { clearTimeout(timer); reject(error); });
  });
}

function websocketIdentity(cookie, user, environment) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket('ws://127.0.0.1:3080/proxy/8081/ws-identity', {
      headers: {Host: host, Cookie: cookie, Origin: 'https://' + host,
        'X-DSH-User': 'forged_identity', 'x-dsh-user': 'second_forged_identity',
        'x-dsh-internet-access': environment === 'secure' ? 'on' : 'off'}});
    const timer = setTimeout(() => { ws.terminate(); reject(new Error('Identity WebSocket timeout')); }, 10000);
    ws.on('message', bytes => {
      clearTimeout(timer);
      try {
        const v = JSON.parse(bytes.toString());
        assert(v.user === user && v.mode === (environment === 'secure' ? 'off' : 'on') && v.count === 1,
          'WebSocket accepted forged or duplicate identity headers');
        ws.close(); resolve(true);
      } catch (e) { ws.terminate(); reject(e); }
    });
    ws.on('error', e => { clearTimeout(timer); reject(e); });
  });
}

(async () => {
  assert(['create', 'verify'].includes(phase), 'Expected create or verify');
  const state = phase === 'create' ? {sessions: []} : JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  const result = {phase, ownReports: 0, ownAttachmentFiles: 0, spoofedHeadersRejected: 0,
    ownSessionPages: 0, crossUserHistoryDenied: 0, crossEnvironmentHistoryDenied: 0,
    terminalCommands: 0, anonymousDenials: 0, websocketSpoofingDenied: 0};
  if (phase === 'create') {
    const accountHash = crypto.createHash('sha256').update(fs.readFileSync('/test-identities/users.json')).digest('hex');
    const registration = await request('POST', '/register', 'username=unapproved&password=not-a-real-password');
    assert(registration.status === 403, 'Registration must be disabled');
    assert(crypto.createHash('sha256').update(fs.readFileSync('/test-identities/users.json')).digest('hex') === accountHash, 'Registration changed identities');
    result.registrationDenied = true;
    for (const user of Object.keys(identities)) {
      for (const [mode, environment] of [['off', 'secure'], ['on', 'internet']]) {
        const login = await request('POST', '/login', new URLSearchParams({username: user, password: identities[user], internet: mode}).toString());
        assert(login.status === 302 && login.cookie, 'Candidate login failed');
        const cookie = login.cookie;
        const create = value(await rpc(cookie, 'session/create', {request: {cwd: '/workspace'}}), 'session/create');
        const title = 'SYNTHETIC_ISOLATION_' + user + '_' + environment;
        const rename = value(await rpc(cookie, 'session/rename', {request: {sessionId: create.sessionId, title}}), 'session/rename');
        const report = await request('GET', '/proxy/8081/report', '', cookie);
        assert(report.status === 200 && report.text.startsWith('PRIVATE_REPORT_'), 'Own report content unavailable');
        const attachment = await request('GET', '/proxy/8081/attachment', '', cookie);
        assert(attachment.status === 200 && attachment.text.startsWith('PRIVATE_ATTACHMENT_'), 'Own attachment fixture unavailable');
        state.sessions.push({user, environment, cookie, sessionId: create.sessionId, throughSeq: rename.seq,
          title, report: report.text, attachment: attachment.text});
      }
    }
    fs.writeFileSync(stateFile, JSON.stringify(state), {mode: 0o600, flag: 'wx'});
    result.sessionsCreated = state.sessions.length;
  }
  for (const own of state.sessions) {
    const anonymous = await request('GET', '/proxy/8081/report');
    assert(anonymous.text.includes('id="pane-login"') && !anonymous.text.includes(own.report), 'Anonymous report exposure');
    result.anonymousDenials++;
    const who = await request('GET', '/proxy/8081/identity?user=iso_bob', '', own.cookie,
      {'x-dsh-user': own.user === 'iso_alice' ? 'iso_bob' : 'iso_alice', 'x-dsh-internet-access': own.environment === 'secure' ? 'on' : 'off'});
    const identity = JSON.parse(who.text);
    assert(identity.gatewayUser === own.user && identity.environment === own.environment,
      'Spoofed header changed user/environment: ' + JSON.stringify({expectedUser: own.user, expectedEnvironment: own.environment, observed: identity}));
    result.spoofedHeadersRejected++;
    await websocketIdentity(own.cookie, own.user, own.environment); result.websocketSpoofingDenied++;
    const report = await request('GET', '/proxy/8081/report', '', own.cookie);
    assert(report.text === own.report, 'Own report changed or another backend selected'); result.ownReports++;
    const attachment = await request('GET', '/proxy/8081/attachment', '', own.cookie);
    assert(attachment.text === own.attachment, 'Own attachment fixture changed'); result.ownAttachmentFiles++;
    const listed = value(await rpc(own.cookie, 'session/list', {_request: {}}), 'session/list');
    assert(listed.items.some(x => x.sessionId === own.sessionId) && JSON.stringify(listed).includes(own.title), 'Own synthetic history missing');
    const page = {address: {kind: 'session', sessionId: own.sessionId}, throughSeq: own.throughSeq, maxMessages: 20};
    value(await rpc(own.cookie, 'session/page', {request: page}), 'own session/page'); result.ownSessionPages++;
    for (const other of state.sessions.filter(x => x !== own && (x.environment === own.environment || x.user === own.user))) {
      assert(!listed.items.some(x => x.sessionId === other.sessionId), 'Another runtime history listed');
      const denied = await rpc(own.cookie, 'session/page', {request: {...page, address: {kind: 'session', sessionId: other.sessionId}}});
      assert(denied.result?.ok === false, 'Another runtime history was readable');
      const error = JSON.stringify(denied.result.error);
      assert(/not-found|not found|no persisted session/i.test(error), 'History denial was not a not-found result: ' + error);
      if (other.user !== own.user) result.crossUserHistoryDenied++;
      else result.crossEnvironmentHistoryDenied++;
    }
    await terminal(own.cookie, own.report); result.terminalCommands++;
  }
  assert(state.sessions.length === 4, 'Expected two users in both environments');
  console.log(JSON.stringify({time: new Date().toISOString(), ...result}));
})().catch(error => { console.error(error.message); process.exitCode = 1; });
