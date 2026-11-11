import test from 'node:test';
import assert from 'node:assert/strict';
import { businessApi, clearBusinessSession } from '../src/services/businessApi.ts';

test('system health uses authenticated business API and preserves fault and recovery records', async () => {
  const original = globalThis.fetch;
  const health = {observed_at: '2026-11-11T12:00:00+08:00', vehicle_available: false,
    issues: [{code: 'vehicle.telemetry', message: '遥测过期', impact: '不能确认状态', suggestion: '检查连接'}],
    history: [{id: 'problem', code: 'camera.frames', state: 'resolved', message: '相机恢复', first_seen: 'a', last_seen: 'b'}]};
  let calls = 0;
  const controller = new AbortController();
  globalThis.fetch = async (path, init) => {
    if (String(path).endsWith('/login')) return new Response(JSON.stringify({access_token: 'test-token', refresh_token: 'test-refresh',
      user: {id: 'test-user', role: {permissions: []}}}));
    calls++;
    assert.equal(String(path), '/api/v1/assistant/system-health');
    assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer test-token');
    assert.equal(init?.signal, controller.signal);
    return new Response(JSON.stringify(health));
  };
  try {
    await businessApi.login('operator', 'test-only');
    assert.deepEqual(await businessApi.assistantHealth(controller.signal), health);
    assert.equal(calls, 1);
  } finally { clearBusinessSession(); globalThis.fetch = original; }
});

test('system health failure remains visible instead of showing an empty healthy state', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async path => String(path).endsWith('/login')
    ? new Response(JSON.stringify({access_token: 'test-token', refresh_token: 'test-refresh', user: {id: 'test-user', role: {permissions: []}}}))
    : new Response(JSON.stringify({detail: '状态暂不可用'}), {status: 503});
  try { await businessApi.login('operator', 'test-only'); await assert.rejects(businessApi.assistantHealth(), /状态暂不可用/); }
  finally { clearBusinessSession(); globalThis.fetch = original; }
});
