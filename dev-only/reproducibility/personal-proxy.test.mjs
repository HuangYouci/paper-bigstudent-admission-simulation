import test from 'node:test';
import assert from 'node:assert/strict';
import { reconstructThresholdOutcome, summarizePersonalProxies } from './personal-proxy.mjs';

test('嚴格超過門檻時，選第一個合格志願', () => {
  const out = reconstructThresholdOutcome([1, 2, 3], [9, 12, 20], new Map([[1, 10], [2, 10], [3, 10]]));
  assert.equal(out.legacy, 2); assert.equal(out.legacyRank, 2); assert.deepEqual(out.possible, [2]);
});
test('同分可能錄取或落到後續志願', () => {
  const out = reconstructThresholdOutcome([1, 2], [10, 11], new Map([[1, 10], [2, 10]]));
  assert.equal(out.legacy, 1); assert.deepEqual(out.possible, [1, 2]); assert.equal(out.reachableTies, 1);
});
test('只有同分時，保留未分發可能', () => {
  const out = reconstructThresholdOutcome([1], [10], new Map([[1, 10]]));
  assert.deepEqual(out.possible, [1, null]);
});
test('缺門檻的前置志願不能默認未錄取', () => {
  const out = reconstructThresholdOutcome([1, 2], [15, 12], new Map([[2, 10]]));
  assert.equal(out.legacy, 2); assert.deepEqual(out.possible, [1, 2]); assert.equal(out.reachableMissingCutoffs, 1);
});
test('已確定較前志願時，後續同分與缺門檻不影響結果', () => {
  const out = reconstructThresholdOutcome([1, 2, 3], [11, 10, 10], new Map([[1, 10], [2, 10]]));
  assert.deepEqual(out.possible, [1]); assert.equal(out.reachableTies, 0); assert.equal(out.reachableMissingCutoffs, 0);
});
test('不合格志願不參與門檻判斷，原始志願序保留', () => {
  const out = reconstructThresholdOutcome([1, 2], [null, 11], new Map([[1, 10], [2, 10]]));
  assert.equal(out.legacyRank, 2); assert.deepEqual(out.possible, [2]);
});
test('全數低於門檻或空志願，僅有未分發結果', () => {
  assert.deepEqual(reconstructThresholdOutcome([1], [9], new Map([[1, 10]])).possible, [null]);
  assert.deepEqual(reconstructThresholdOutcome([], [], new Map()).possible, [null]);
});
test('分母區分全體、雙方上榜及雙方未上榜', () => {
  const records = [
    { wishes: [1], scores: [11], status: 'assigned', assignedGid: 1, assignedRank: 1 },
    { wishes: [1], scores: [9], status: 'unassigned', assignedGid: null, assignedRank: null },
    { wishes: [1], scores: [11], status: 'unassigned', assignedGid: null, assignedRank: null },
  ];
  const out = summarizePersonalProxies(records, new Map([[1, 10]]));
  assert.equal(out.rates.sameDepartmentAmongBothAssigned, 1);
  assert.equal(out.rates.sameDepartmentAmongAllRecords, 1 / 3);
  assert.equal(out.rates.sameOutcomeIncludingBothUnassigned, 2 / 3);
  assert.equal(out.uncertainty.agreementLowerRate, 2 / 3);
  assert.equal(out.uncertainty.agreementUpperRate, 2 / 3);
});
test('同分不確定案例擴張可能一致範圍，不自動算對', () => {
  const out = summarizePersonalProxies([{ wishes: [1], scores: [10], status: 'unassigned', assignedGid: null, assignedRank: null }], new Map([[1, 10]]));
  assert.equal(out.uncertainty.agreementLowerRate, 0); assert.equal(out.uncertainty.agreementUpperRate, 1);
});
test('拒絕不完整、非有限或錯位的外部輸入', () => {
  assert.throws(() => reconstructThresholdOutcome([1], [], new Map()));
  assert.throws(() => reconstructThresholdOutcome([1], [NaN], new Map()));
  assert.throws(() => reconstructThresholdOutcome([1], [11], new Map([[1, -1]])));
  assert.throws(() => summarizePersonalProxies([{ wishes: [1], scores: [11], status: 'assigned', assignedGid: 2, assignedRank: 1 }], new Map([[1, 10]])));
});
