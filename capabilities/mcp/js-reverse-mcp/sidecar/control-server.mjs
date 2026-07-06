import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { launchPersistentContext } from 'cloakbrowser/puppeteer';

const slots = Number.parseInt(process.env.CAIRN_CLOAK_SLOTS || '2', 10);
const cdpBasePort = Number.parseInt(process.env.CAIRN_CLOAK_CDP_BASE_PORT || '9222', 10);
const controlPort = Number.parseInt(process.env.CAIRN_CLOAK_CONTROL_PORT || '7310', 10);
const leaseTtlMs = Number.parseInt(process.env.CAIRN_CLOAK_LEASE_TTL_MS || '900000', 10);
const leaseWaitMs = Number.parseInt(process.env.CAIRN_CLOAK_LEASE_WAIT_MS || '30000', 10);

const state = Array.from({ length: slots }, (_, index) => ({
  slot: index,
  cdpPort: cdpBasePort + index,
  browserUrl: `http://127.0.0.1:${cdpBasePort + index}`,
  publicBrowserUrl: `http://${process.env.CAIRN_CLOAK_PUBLIC_HOST || process.env.HOSTNAME || 'localhost'}:${cdpBasePort + index}`,
  leaseId: null,
  leaseExpiresAt: 0,
  browser: null,
  launchError: '',
}));
const waiters = [];

async function launchSlot(item) {
  const args = [
    `--remote-debugging-address=0.0.0.0`,
    `--remote-debugging-port=${item.cdpPort}`,
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--window-size=1365,900',
  ];
  item.browser = await launchPersistentContext({
    userDataDir: `/profiles/slot-${item.slot}`,
    headless: false,
    humanize: true,
    args,
    launchOptions: {
      args,
      dumpio: false,
    },
  });
}

async function launchAll() {
  await Promise.all(state.map(async item => {
    try {
      await launchSlot(item);
    } catch (error) {
      item.launchError = error?.message || String(error);
      console.error(`slot ${item.slot} launch failed: ${item.launchError}`);
    }
  }));
}

function expireLeases() {
  const now = Date.now();
  for (const item of state) {
    if (item.leaseId && item.leaseExpiresAt <= now) {
      item.leaseId = null;
      item.leaseExpiresAt = 0;
    }
  }
}

function lease(leaseId) {
  expireLeases();
  const item = state.find(candidate => !candidate.leaseId && candidate.browser && !candidate.launchError);
  if (!item) return null;
  item.leaseId = leaseId || randomUUID();
  item.leaseExpiresAt = Date.now() + leaseTtlMs;
  return { slot: item.slot, browser_url: item.publicBrowserUrl, lease_id: item.leaseId, ttl_ms: leaseTtlMs };
}

function release(leaseId) {
  let released = false;
  for (const item of state) {
    if (item.leaseId === leaseId) {
      item.leaseId = null;
      item.leaseExpiresAt = 0;
      released = true;
    }
  }
  drainWaiters();
  return released;
}

function drainWaiters() {
  for (let index = 0; index < waiters.length;) {
    const waiter = waiters[index];
    const result = lease(waiter.leaseId);
    if (!result) {
      index += 1;
      continue;
    }
    waiters.splice(index, 1);
    clearTimeout(waiter.timer);
    waiter.resolve(result);
  }
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    let body = '';
    request.setEncoding('utf8');
    request.on('data', chunk => { body += chunk; });
    request.on('end', () => {
      if (!body.trim()) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
  });
}

function writeJson(response, status, payload) {
  response.writeHead(status, { 'content-type': 'application/json' });
  response.end(JSON.stringify(payload));
}

function healthPayload() {
  expireLeases();
  return {
    slots: state.map(item => ({
      slot: item.slot,
      cdp_port: item.cdpPort,
      busy: Boolean(item.leaseId),
      ready: Boolean(item.browser) && !item.launchError,
      lease_expires_at: item.leaseExpiresAt || null,
      error: item.launchError,
    })),
  };
}

await launchAll();
setInterval(expireLeases, 10000).unref();

const server = http.createServer(async (request, response) => {
  try {
    if (request.method === 'GET' && request.url === '/healthz') {
      writeJson(response, 200, healthPayload());
      return;
    }
    if (request.method === 'POST' && request.url === '/lease') {
      const body = await readJson(request);
      const leaseId = typeof body.lease_id === 'string' && body.lease_id ? body.lease_id : randomUUID();
      const result = lease(leaseId);
      if (result) {
        writeJson(response, 200, result);
        return;
      }
      const waited = await new Promise(resolve => {
        const waiter = { leaseId, resolve, timer: null };
        waiter.timer = setTimeout(() => {
          const index = waiters.indexOf(waiter);
          if (index >= 0) waiters.splice(index, 1);
          resolve(null);
        }, leaseWaitMs);
        waiters.push(waiter);
      });
      if (waited) writeJson(response, 200, waited);
      else writeJson(response, 503, { error: 'no cloak browser slot available', wait_ms: leaseWaitMs });
      return;
    }
    if (request.method === 'POST' && request.url === '/release') {
      const body = await readJson(request);
      writeJson(response, 200, { released: release(String(body.lease_id || '')) });
      return;
    }
    writeJson(response, 404, { error: 'not found' });
  } catch (error) {
    writeJson(response, 500, { error: error?.message || String(error) });
  }
});

server.listen(controlPort, '0.0.0.0', () => {
  console.log(`cloak sidecar control listening on ${controlPort}`);
});
