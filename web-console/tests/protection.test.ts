import assert from 'node:assert/strict';
import test from 'node:test';
import { createRobotApi } from '../src/robotApi';
import { protectionReason } from '../src/protectionStatus';
import { DriveHoldController } from '../src/liveControl';

test('ordinary held driving uses the original protocol without status-issued press credentials', async () => {
  const sent: Record<string, unknown>[] = [];
  const api = createRobotApi(async (_url, init) => {
    const body = JSON.parse(String(init?.body)); sent.push(body);
    return Response.json(body.mode ? {ok: true, drive_id: 'drive'} : {ok: true});
  });
  await api.setMode('manual');
  let tick = () => {};
  const changes: (string | null)[] = [];
  const hold = new DriveHoldController(async command => { await api.sendCommand(command); return true; },
    {every: fn => {tick = fn; return 1;}, clear: () => {}}, command => changes.push(command));
  hold.start('forward');
  for (let i = 0; i < 12; i++) {
    await new Promise(resolve => setImmediate(resolve)); tick();
  }
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(changes, ['forward']);
  const movements = sent.filter(v => v.command === 'forward');
  assert.equal(movements.length, 13);
  for (const command of movements) assert.deepEqual(Object.keys(command).sort(), ['command', 'drive_id', 'drive_seq']);
  hold.stop(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(sent.at(-1)?.command, 'stop');
  assert.deepEqual(changes, ['forward', null]);
});

test('profile and recovery actions preserve pending controller acknowledgement', async () => {
  const requests: unknown[] = [];
  const api = createRobotApi(async (_url, init) => {
    requests.push(JSON.parse(String(init?.body)));
    return Response.json({confirmed: false, settings: {enabled: false, protection_mode: 'basic', trigger_distance_m: .6}});
  });
  const pending = await api.setAvoidance({protection_mode: 'full'});
  assert.equal(pending.confirmed, false);
  assert.equal(pending.settings.protection_mode, 'basic');
  await api.setAvoidance({acknowledge: 'epoch'});
  assert.deepEqual(requests, [{protection_mode: 'full'}, {acknowledge: 'epoch'}]);
});

test('intercept reasons have understandable labels without claiming unknown space is an obstacle', () => {
  assert.match(protectionReason('avoidance_waiting_observation'), /缺少可靠观测/);
  assert.match(protectionReason('scan_odom_tf_unavailable'), /位姿变换/);
  assert.doesNotMatch(protectionReason('future_unknown_reason'), /future_unknown_reason/);
});

test('reusing manual control preserves sequence floors and the same client identity', async () => {
  const sent: Record<string, unknown>[]=[];
  let selections=0;
  const api=createRobotApi(async (_url, init) => {
    const body=JSON.parse(String(init?.body));sent.push(body);
    if (body.mode) return Response.json({ok:true, mode:'manual', drive_id:'same', motion_epoch:'m',
      command_valid_until:1234, drive_seq_floor:selections++ ? 9 : 0, intent_seq_floor:selections>1 ? 5 : 0});
    return Response.json({ok:true});
  });
  await api.setMode('manual');await api.sendCommand('forward');
  await api.setMode('manual');await api.sendCommand('backward');
  assert.equal(sent[0].client_id,sent[2].client_id);
  assert.equal(sent[3].drive_seq,10);assert.equal('intent_seq' in sent[3],false);
});
