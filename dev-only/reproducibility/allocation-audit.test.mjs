/** 驗證獨立稽核器可抓出同分、閒置容量及質量違規。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { auditAllocation } from './allocation-audit.mjs';

const ctx = {
  candidateUids: ['a', 'b'],
  eligibleByUid: new Map(['a', 'b'].map(uid => [uid, [{ gid: 1, score: 10, rank: 1 }]])),
  weightOf: () => 1,
  quotaOf: () => 1,
  deptIds: [1],
  compareFor: () => (a, b) => b.weightedScore - a.weightedScore || a.uid.localeCompare(b.uid),
};

function output(held) {
  return { results: new Map([[1, { held, assignedWeight: held.reduce((sum, h) => sum + h.mass, 0) }]]) };
}

test('同分但完整比序優先者被拒仍構成阻擋邊', () => {
  const out = output([{ uid: 'b', score: 10, mass: 1 }]);
  assert.equal(auditAllocation(ctx, out, { validate: false }).blockingPairs, 1);
  assert.throws(() => auditAllocation(ctx, out), /穩定配置/);
});

test('未配置候選人與閒置容量構成阻擋邊', () => {
  assert.equal(auditAllocation(ctx, output([]), { validate: false }).blockingPairs, 2);
});

test('容量及個人供給超額必須拒絕', () => {
  assert.throws(() => auditAllocation(ctx, output([{ uid: 'a', score: 10, mass: 2 }])), /可行性/);
});

test('完整比序、零容量與合法配置通過', () => {
  assert.equal(auditAllocation(ctx, output([{ uid: 'a', score: 10, mass: 1 }])).blockingPairs, 0);
  assert.equal(auditAllocation({ ...ctx, quotaOf: () => 0 }, output([])).blockingPairs, 0);
});

test('重複有效志願不能套用本稽核的模型假設', () => {
  const invalid = { ...ctx, eligibleByUid: new Map([['a', [{ gid: 1, score: 10, rank: 1 }, { gid: 1, score: 10, rank: 2 }]], ['b', []]]) };
  assert.throws(() => auditAllocation(invalid, output([])), /有效志願不可重複/);
});

test('容差以下的正阻擋量仍須旁錄', () => {
  const small = { ...ctx, candidateUids: ['a'], eligibleByUid: new Map([['a', [{ gid: 1, score: 10, rank: 1 }]]]), weightOf: () => 5e-7 };
  const result = auditAllocation(small, output([]));
  assert.equal(result.maxBlockingMass, 5e-7);
  assert.equal(result.positiveBlockingEdges, 1);
  assert.equal(result.blockingPairs, 0);
});

test('全部供給已留任仍可能由較差志願移向中間志願', () => {
  const wishes = [{ gid: 1, score: 10, rank: 1 }, { gid: 2, score: 10, rank: 2 }, { gid: 3, score: 10, rank: 3 }];
  const market = { ...ctx, candidateUids: ['a'], eligibleByUid: new Map([['a', wishes]]), weightOf: () => 5, quotaOf: gid => gid === 1 ? 3 : 5, deptIds: [1, 2, 3] };
  const result = { results: new Map([[1, { assignedWeight: 3, held: [{ uid: 'a', score: 10, mass: 3 }] }], [2, { assignedWeight: 0, held: [] }], [3, { assignedWeight: 2, held: [{ uid: 'a', score: 10, mass: 2 }] }]]) };
  assert.equal(auditAllocation(market, result, { validate: false }).maxBlockingMass, 2);
});

test('容量稽核不能信任輸出自報的留任總量', () => {
  const out = output([{ uid: 'a', score: 10, mass: 2 }]);
  out.results.get(1).assignedWeight = 0;
  const result = auditAllocation(ctx, out, { validate: false });
  assert.equal(result.maxCapacityExcess, 1);
  assert.equal(result.maxReportedWeightDifference, 2);
  assert.throws(() => auditAllocation(ctx, out), /可行性/);
});

test('偏好以合格清單次序為準，不依賴外加rank欄位', () => {
  const market = { ...ctx, candidateUids: ['a'], eligibleByUid: new Map([['a', [{ gid: 1, score: 10, rank: 2 }, { gid: 2, score: 10, rank: 1 }]]]), deptIds: [1, 2] };
  const out = { results: new Map([[1, { assignedWeight: 1, held: [{ uid: 'a', score: 10, mass: 1 }] }], [2, { assignedWeight: 0, held: [] }]]) };
  assert.equal(auditAllocation(market, out).maxBlockingMass, 0);
});
