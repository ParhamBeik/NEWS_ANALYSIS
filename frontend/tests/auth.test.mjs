import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

// Execute the actual server modules with request-scoped framework and network boundaries.
async function load(path, globals, imports) {
  const context = vm.createContext({ URL, Headers, AbortSignal, ...globals });
  const module = new vm.SourceTextModule(await readFile(new URL(path, import.meta.url), 'utf8'), { context });
  await module.link((name) => {
    const values = imports[name];
    return new vm.SyntheticModule(Object.keys(values), function () {
      for (const [key, value] of Object.entries(values)) this.setExport(key, value);
    }, { context });
  });
  await module.evaluate();
  return module.namespace;
}

test('auth actions preserve trusted client identity and distinguish throttling from bad credentials', async () => {
  let sent;
  const environment = { TRUST_PROXY_HEADERS: '1' };
  const actions = await load('../app/login/actions.js', {
    process: { env: environment },
    fetch: async (url, options) => {
      sent = options;
      return { ok: false, status: 429, json: async () => ({ detail: 'throttled' }) };
    },
  }, {
    'next/headers': { cookies: async () => ({}), headers: async () => new Headers({ 'x-forwarded-for': '203.0.113.7' }) },
    'next/navigation': { redirect: () => { throw new Error('unexpected redirect'); } },
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

test('a stale cookie can reach login instead of cycling between home and login', async () => {
  const middleware = await load('../middleware.js', {}, {
    'next/server': { NextResponse: { next: () => 'continue', redirect: () => 'redirect' } },
  });
  assert.equal(middleware.middleware({
    nextUrl: new URL('http://localhost/login'), cookies: { get: () => 'revoked-token' },
    headers: new Headers(), url: 'http://localhost/login',
  }), 'continue');
});

test('dashboard API reads have a bounded server-side deadline', async () => {
  let sent;
  const api = await load('../lib/api.js', {
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
