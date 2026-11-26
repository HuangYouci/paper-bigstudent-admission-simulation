/** 檢驗耗盡、微小質量及旁錄與原凍結配置的一致性。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const repository = process.env.BIGSTUDENT_REPOSITORY;
if (!repository) throw new Error('請設定 BIGSTUDENT_REPOSITORY 指向核實的純配置模組');
const { runFractionalDA, collect } = await import(pathToFileURL(path.join(repository, 'dev-only/simulation-weighting/da-rules.mjs')));
import { traceFractionalAllocation, verifyTrackedOutput } from './trace-allocation.mjs';

function context(weights, quota, empty = false) {
  const ids = weights.map((_, index) => String(index));
  return { candidateUids: ids, eligibleByUid: new Map(ids.map(uid => [uid, empty ? [] : [{ gid: 1, score: 10, rank: 1 }]])),
    weightOf: uid => weights[Number(uid)], quotaOf: () => quota, deptIds: [1],
    compareFor: () => (a, b) => b.weightedScore - a.weightedScore || a.uid.localeCompare(b.uid) };
}

function checked(ctx) {
  const traced = traceFractionalAllocation(ctx, collect);
  verifyTrackedOutput(runFractionalDA(ctx), traced.output);
  assert(Math.abs(traced.ledger.balanceResidual) <= 1e-12);
  assert(traced.ledger.droppedMass <= traced.ledger.dropMassBound + 1e-15);
  return traced.ledger;
}

test('容量不足的質量歸入志願耗盡', () => {
  const ledger = checked(context([5], 3));
  assert.equal(ledger.accounts.retained.mass, 3);
  assert.equal(ledger.accounts.exhausted.mass, 2);
  assert.equal(ledger.droppedMass, 0);
});

test('沒有合格志願的供給分開記錄', () => {
  const ledger = checked(context([5], 3, true));
  assert.equal(ledger.accounts.noPreferences.mass, 5);
  assert.equal(ledger.accounts.exhausted.mass, 0);
});

test('微小初始事件先計入取出丟棄', () => {
  const ledger = checked(context([5e-8], 1));
  assert.equal(ledger.accounts.droppedAtPop.mass, 5e-8);
  assert.equal(ledger.accounts.exhausted.mass, 0);
});

test('未轉送的微小擠出質量不能計入耗盡', () => {
  const ledger = checked(context([1, 1], 2 - 5e-8));
  assert(Math.abs(ledger.accounts.droppedDisplaced.mass - 5e-8) < 1e-15);
  assert.equal(ledger.accounts.exhausted.mass, 0);
});

test('微小剩餘容量不等於供給丟失', () => {
  const ledger = checked(context([1, 1], 1 + 5e-8));
  assert.equal(ledger.accounts.retained.mass, 1);
  assert.equal(ledger.accounts.exhausted.mass, 1);
  assert.equal(ledger.droppedMass, 0);
});

test('事件上限只能拋錯，不回傳完成質量帳', () => {
  assert.throws(() => traceFractionalAllocation(context([5], 0), collect, { maxEvents: 1 }), /未完成/);
});

test('無效供給與重複考生必須拒絕', () => {
  assert.throws(() => checked(context([-1], 3)), /供給/);
  const ctx = context([1], 3);
  ctx.candidateUids.push('0');
  assert.throws(() => checked(ctx), /考生鍵/);
});
