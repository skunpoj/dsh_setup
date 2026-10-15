// Probe the application, not the socat bridge which opens before DSH starts.
const http = require('http');
const request = http.get('http://127.0.0.1:3080/', response => {
  response.resume();
  process.exit([200, 302, 401].includes(response.statusCode) ? 0 : 1);
});
request.setTimeout(2000, () => request.destroy(new Error('application health timeout')));
request.on('error', () => process.exit(1));
