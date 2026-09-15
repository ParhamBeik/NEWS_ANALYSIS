import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { loadServerModule } from './helpers.mjs';

test('auth actions preserve trusted client identity and distinguish throttling from bad credentials', async () => {
  let sent;
  const environment = { TRUST_PROXY_HEADERS: '1' };
  const actions = await loadServerModule('../app/login/actions.js', {
    process: { env: environment },
    fetch: async (url, options) => {
      sent = options;
      return { ok: false, status: 429, json: async () => ({ detail: 'throttled' }) };
    },
  }, {
    'next/headers': { cookies: async () => ({}), headers: async () => new Headers({ 'x-forwarded-for': '203.0.113.7' }) },
    'next/navigation': { redirect: () => { throw new Error('unexpected redirect'); } },
    '@/lib/api': { API_ORIGIN: 'http://backend:8000' },
  });
  const form = new FormData();
  form.set('username', 'analyst');
  form.set('password', 'secret');
  form.set('passwordConfirm', 'secret');
  for (const action of [actions.login, actions.signup]) {
    assert.match((await action(null, form)).error, /Too many attempts/);
    assert.equal(sent.headers['X-Forwarded-For'], '203.0.113.7');
    assert.ok(sent.signal instanceof AbortSignal);
    environment.TRUST_PROXY_HEADERS = '0';
    await action(null, form);
    assert.equal(sent.headers['X-Forwarded-For'], undefined);
    environment.TRUST_PROXY_HEADERS = '1';
  }
});

// Regression: this handler used `new URL("/login", request.url)`, and behind the Caddy edge
// request.url carries the address Next bound to inside the container - so production replied
// `Location: https://0.0.0.0:3000/login` and every sign-out navigated nowhere.
test('sign-out sends a relative Location, not the container address', async () => {
  const deleted = [];
  let revoked = null;
  class FakeResponse {
    constructor(body, init) {
      this.body = body;
      this.status = init.status;
      this.headers = init.headers;
    }
  }
  const route = await loadServerModule('../app/logout/route.js', {
    fetch: async (url, options) => { revoked = { url, options }; return { ok: true }; },
  }, {
    'next/headers': {
      cookies: async () => ({
        get: () => ({ value: 'a-live-token' }),
        delete: (name) => deleted.push(name),
      }),
    },
    'next/server': { NextResponse: FakeResponse },
    '@/lib/api': { API_ORIGIN: 'http://backend:8000' },
  });

  const response = await route.POST();
  assert.equal(response.status, 303);
  assert.equal(response.headers.Location, '/login');
  assert.doesNotMatch(
    response.headers.Location,
    /^[a-z]+:\/\//,
    'an absolute Location is resolved from the container bind address, not the public host',
  );
  // The token is revoked server-side and the cookie dropped; dropping it alone is not a
  // sign-out, because a DRF token has no expiry.
  assert.equal(revoked.url, 'http://backend:8000/api/auth/logout/');
  assert.deepEqual(deleted, ['news_token']);
});

test('a stale cookie can reach login instead of cycling between home and login', async () => {
  const middleware = await loadServerModule('../middleware.js', {}, {
    'next/server': { NextResponse: { next: () => 'continue', redirect: () => 'redirect' } },
  });
  assert.equal(middleware.middleware({
    nextUrl: new URL('http://localhost/login'), cookies: { get: () => 'revoked-token' },
    headers: new Headers(), url: 'http://localhost/login',
  }), 'continue');
  assert.equal(middleware.middleware({
    nextUrl: new URL('http://localhost/robots.txt'), cookies: { get: () => undefined },
    headers: new Headers(), url: 'http://localhost/robots.txt',
  }), 'continue');
  assert.equal(middleware.middleware({
    nextUrl: new URL('http://localhost/logout'), cookies: { get: () => undefined },
    headers: new Headers(), url: 'http://localhost/logout',
  }), 'continue');
});

test('dashboard API reads have a bounded server-side deadline', async () => {
  let sent;
  const api = await loadServerModule('../lib/api.js', {
    process: { env: {} },
    fetch: async (_url, options) => {
      sent = options;
      return { ok: true, status: 204 };
    },
  }, {
    'next/headers': {
      cookies: async () => ({ get: () => undefined }),
      headers: async () => new Headers(),
    },
    'next/navigation': { redirect: () => {} },
  });

  await api.apiFetch('/api/health/');
  assert.ok(sent.signal instanceof AbortSignal);
});

// The root layout renders on /login too, so an unauthenticated read here must be a normal
// null rather than the redirect apiGet would issue - that redirect targets the very page
// whose layout produced it.
test('the signed-in identity resolves to null instead of redirecting a signed-out visitor', async () => {
  let calls = 0;
  const loadApi = (token, respond) => loadServerModule('../lib/api.js', {
    process: { env: {} },
    fetch: async () => {
      calls += 1;
      return respond();
    },
  }, {
    'next/headers': {
      cookies: async () => ({ get: (name) => (token && name === 'news_token' ? { value: token } : undefined) }),
      headers: async () => new Headers(),
    },
    'next/navigation': { redirect: () => { throw new Error('unexpected redirect'); } },
  });

  const anonymous = await loadApi(null, () => null);
  assert.equal(await anonymous.currentUser(), null);
  assert.equal(calls, 0, 'no cookie means no call to the API at all');

  const revoked = await loadApi('stale', () => ({ ok: false, status: 401, json: async () => ({}) }));
  assert.equal(await revoked.currentUser(), null);

  const unreachable = await loadApi('good', () => { throw new Error('ECONNREFUSED'); });
  assert.equal(await unreachable.currentUser(), null);

  // Field by field, not deepEqual: the module runs in its own vm realm, so the object it
  // returns has a different Object.prototype and fails a strict structural comparison.
  const staff = await loadApi('good', () => ({ ok: true, status: 200, json: async () => ({ username: 'parham', is_staff: true }) }));
  const admin = await staff.currentUser();
  assert.equal(admin.username, 'parham');
  assert.equal(admin.isStaff, true);

  // Django omits nothing here, but a plain user's is_staff must never arrive as undefined
  // and light up the admin link by accident.
  const analyst = await loadApi('good', () => ({ ok: true, status: 200, json: async () => ({ username: 'demo1' }) }));
  const plain = await analyst.currentUser();
  assert.equal(plain.username, 'demo1');
  assert.equal(plain.isStaff, false);
});

test('the Django admin link is an anchor the Next router cannot swallow', async () => {
  const shell = await readFile(new URL('../components/AppShell.js', import.meta.url), 'utf8');
  assert.match(shell, /<a\s+href="\/admin\/"/, 'a next/link to /admin/ would 404 in the Next router');
  assert.match(shell, /user\?\.isStaff \?/, 'the admin link is gated on is_staff');
});

test('the Quality dashboard imports every shared component it renders', async () => {
  const page = await readFile(new URL('../app/kpi/page.js', import.meta.url), 'utf8');
  assert.match(page, /import\s*\{[^}]*\bMetric\b[^}]*\}\s*from\s*["']@\/components\/primitives["']/);
});

test('dashboard cards can contain scrollable content without widening their grid', async () => {
  const primitives = await readFile(new URL('../components/primitives.js', import.meta.url), 'utf8');
  assert.match(primitives, /className=\{`min-w-0 rounded-xl border/);
});

test('the skip link target accepts programmatic keyboard focus', async () => {
  const shell = await readFile(new URL('../components/AppShell.js', import.meta.url), 'utf8');
  assert.match(shell, /<main id="main" tabIndex=\{-1\}/);
});
