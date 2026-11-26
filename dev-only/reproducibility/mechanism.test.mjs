/** 以合成資料查核平台的加權配對機制；不讀取考生資料。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const repository = process.env.BIGSTUDENT_REPOSITORY;
if (!repository) throw new Error('請設定 BIGSTUDENT_REPOSITORY 指向唯讀平台原始碼');
const { runBinaryDA, runFractionalDA } = await import(pathToFileURL(path.join(repository, 'dev-only/simulation-weighting/da-rules.mjs')));

function context(candidates, quotas, order = candidates.map(candidate => candidate.uid)) {
  const weights = new Map(candidates.map(candidate => [candidate.uid, candidate.weight]));
  const eligible = new Map(candidates.map(candidate => [candidate.uid, candidate.wishes.map(([gid, score], index) => ({ gid, score, rank: index + 1, wishIndex: index }))]));
  return {
    candidateUids: order,
    eligibleByUid: eligible,
    weightOf: uid => weights.get(uid),
    quotaOf: gid => quotas.get(gid) ?? 0,
    deptIds: [...quotas.keys()],
    compareFor: () => (a, b) => b.weightedScore - a.weightedScore || a.uid.localeCompare(b.uid),
  };
}

function permutations(items) {
  if (items.length === 0) return [[]];
  return items.flatMap((item, index) => permutations(items.filter((_, other) => other !== index)).map(rest => [item, ...rest]));
}

const inversionCase = [
  { uid: 'a', weight: 9, wishes: [[1, 220]] },
  { uid: 'b', weight: 9, wishes: [[1, 195]] },
  { uid: 'c', weight: 1, wishes: [[1, 150]] },
];

test('v2 反例重現高分完全拒絕、低分保留與順序相依', () => {
  const outcomes = permutations(['a', 'b', 'c']).map(order => runBinaryDA(context(inversionCase, new Map([[1, 12]]), order), 'round'));
  assert.ok(outcomes.some(output => output.blocking > 0), '反例必須能實際觸發倒掛');
  assert.ok(new Set(outcomes.map(output => output.results.get(1).minScore)).size > 1, '反例必須能觸發順序相依');
});

test('fractional 反例的六種排列皆保留高分質量、恰好填滿容量', () => {
  for (const order of permutations(['a', 'b', 'c'])) {
    const output = runFractionalDA(context(inversionCase, new Map([[1, 12]]), order));
    const department = output.results.get(1);
    assert.equal(output.blocking, 0);
    assert.equal(department.minScore, 195);
    assert.equal(department.assignedWeight, 12);
    assert.deepEqual(department.held.map(entry => [entry.uid, entry.mass]), [['a', 9], ['b', 3]]);
    assert.equal(department.marginalMassFraction, 1 / 3);
  }
});

test('剩餘質量流向下一志願，單一候選人可在多系保留質量', () => {
  const output = runFractionalDA(context([{ uid: 'a', weight: 5, wishes: [[1, 200], [2, 180]] }], new Map([[1, 3], [2, 2]])));
  assert.equal(output.results.get(1).assignedWeight, 3);
  assert.equal(output.results.get(2).assignedWeight, 2);
  assert.equal(output.spread.deptCountByUid.get('a'), 2);
  assert.equal(output.states.get('a').assigned.rank, 1);
});

test('單位權重與整數容量退化為一般離散 DA', () => {
  const candidates = [
    { uid: 'a', weight: 1, wishes: [[1, 200], [2, 170]] },
    { uid: 'b', weight: 1, wishes: [[1, 190], [2, 180]] },
    { uid: 'c', weight: 1, wishes: [[2, 175]] },
  ];
  const ctx = context(candidates, new Map([[1, 1], [2, 1]]));
  const binary = runBinaryDA(ctx, 'always');
  const fractional = runFractionalDA(ctx);
  for (const gid of [1, 2]) {
    assert.deepEqual(fractional.results.get(gid).held, binary.results.get(gid).held);
  }
});

test('容量為零與需求不足分別保留缺值與未滿額，不虛造出清門檻', () => {
  const candidates = [{ uid: 'a', weight: 1, wishes: [[1, 200], [2, 180]] }];
  const output = runFractionalDA(context(candidates, new Map([[1, 0], [2, 5]])));
  assert.equal(output.results.get(1).minScore, null);
  assert.equal(output.results.get(2).assignedWeight, 1);
  assert.equal(output.results.get(2).minScore, 180);
});
