/** 固定亂數人工市場壓力測試；不使用個人資料或官方真值。 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { auditAllocation } from './allocation-audit.mjs';
import crypto from 'node:crypto';
import { traceFractionalAllocation, verifyTrackedOutput } from './trace-allocation.mjs';

const repo = process.env.BIGSTUDENT_REPOSITORY;
if (!repo) throw new Error('請設定 BIGSTUDENT_REPOSITORY');
const ruleFile = path.join(repo, 'dev-only/simulation-weighting/da-rules.mjs');
assert.equal(crypto.createHash('sha256').update(fs.readFileSync(ruleFile)).digest('hex'), '3629b6829899419da5a6158cd2c0081ca70f8ffeea2275ff0cd3ee3aa03abe8b', '凍結核心版本不符');
const { runBinaryDA, runFractionalDA, collect } = await import(pathToFileURL(ruleFile));
const paper = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

/** 固定演算法的偽亂數，避免依賴執行時間。 */
function random(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle(values, rng) {
  const out = [...values];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

function market(seed, weightMode) {
  const rng = random(seed);
  const deptIds = [1, 2, 3, 4, 5, 6];
  const quotas = new Map(deptIds.map(gid => [gid, Math.floor(21 * rng())]));
  const people = Array.from({ length: 40 }, (_, index) => {
    const uid = `synthetic-${String(index).padStart(3, '0')}`;
    const weight = weightMode === 'unit' ? 1 : weightMode === 'uniform_1_4' ? 1 + 3 * rng() : 100 ** rng();
    const wishes = shuffle(deptIds, rng).slice(0, 1 + Math.floor(6 * rng())).map((gid, index) => ({ gid, score: Math.floor(61 * rng()), rank: index + 1, wishIndex: index }));
    return { uid, weight, wishes };
  });
  const weights = new Map(people.map(p => [p.uid, p.weight]));
  return { candidateUids: people.map(p => p.uid), eligibleByUid: new Map(people.map(p => [p.uid, p.wishes])),
    weightOf: uid => weights.get(uid), quotaOf: gid => quotas.get(gid), deptIds,
    compareFor: () => (a, b) => b.weightedScore - a.weightedScore || a.uid.localeCompare(b.uid) };
}

function distance(first, second) {
  let difference = 0;
  for (const [gid, result] of first.results) {
    const other = second.results.get(gid);
    const keys = new Set([...result.held.map(h => h.uid), ...other.held.map(h => h.uid)]);
    for (const uid of keys) {
      const mass = result.held.find(h => h.uid === uid)?.mass || 0;
      const otherMass = other.held.find(h => h.uid === uid)?.mass || 0;
      difference = Math.max(difference, Math.abs(mass - otherMass));
    }
  }
  return difference;
}

const scenarios = {};
const diagnostics = { executions: 0, maxBlockingMass: 0, maxAbsoluteBalanceResidual: 0, maxDroppedMass: 0, maxDropEvents: 0, maxFractionalEvents: 0, positiveBlockingExecutions: 0 };
function inspect(ctx, out) {
  const { output, ledger } = traceFractionalAllocation(ctx, collect);
  verifyTrackedOutput(out, output);
  const audit = auditAllocation(ctx, out);
  assert(Math.abs(ledger.balanceResidual) <= 1e-8, '質量帳殘差過大');
  assert(ledger.droppedMass <= ledger.dropMassBound + 1e-12, 'EPS丟棄超出旁錄上界');
  diagnostics.executions++;
  diagnostics.maxBlockingMass = Math.max(diagnostics.maxBlockingMass, audit.maxBlockingMass);
  diagnostics.positiveBlockingExecutions += Number(audit.positiveBlockingEdges > 0);
  diagnostics.maxAbsoluteBalanceResidual = Math.max(diagnostics.maxAbsoluteBalanceResidual, Math.abs(ledger.balanceResidual));
  diagnostics.maxDroppedMass = Math.max(diagnostics.maxDroppedMass, ledger.droppedMass);
  diagnostics.maxDropEvents = Math.max(diagnostics.maxDropEvents, ledger.dropEvents);
  diagnostics.maxFractionalEvents = Math.max(diagnostics.maxFractionalEvents, out.events);
}
for (const [scenarioIndex, mode] of ['unit', 'uniform_1_4', 'loguniform_1_100'].entries()) {
  const summary = { markets: 200, roundBlockingMarkets: 0, roundCapacityExcessMarkets: 0, roundOrderDependentMarkets: 0,
    fractionalBlockingMarkets: 0, fractionalOrderDependentMarkets: 0, maxFractionalMassDifference: 0, maxFractionalEvents: 0 };
  for (let index = 0; index < 200; index++) {
    const seed = 20261008 + scenarioIndex * 10000 + index;
    const ctx = market(seed, mode);
    const binary = runBinaryDA(ctx, 'round');
    const fractional = runFractionalDA(ctx);
    inspect(ctx, fractional);
    const binaryAudit = auditAllocation(ctx, binary, { validate: false });
    const fractionalAudit = auditAllocation(ctx, fractional);
    summary.roundBlockingMarkets += Number(binaryAudit.blockingPairs > 0);
    summary.roundCapacityExcessMarkets += Number(binaryAudit.maxCapacityExcess > 1e-6);
    summary.fractionalBlockingMarkets += Number(fractionalAudit.blockingPairs > 0);
    summary.maxFractionalEvents = Math.max(summary.maxFractionalEvents, fractional.events);
    let binaryChanges = false, fractionalChanges = false;
    for (const salt of [100000, 200000, 300000]) {
      const permuted = { ...ctx, candidateUids: shuffle(ctx.candidateUids, random(seed + salt)) };
      const binaryOther = runBinaryDA(permuted, 'round');
      const fractionalOther = runFractionalDA(permuted);
      inspect(permuted, fractionalOther);
      summary.maxFractionalEvents = Math.max(summary.maxFractionalEvents, fractionalOther.events);
      binaryChanges ||= distance(binary, binaryOther) > 1e-6;
      const change = distance(fractional, fractionalOther);
      fractionalChanges ||= change > 1e-6;
      summary.maxFractionalMassDifference = Math.max(summary.maxFractionalMassDifference, change);
    }
    summary.roundOrderDependentMarkets += Number(binaryChanges);
    summary.fractionalOrderDependentMarkets += Number(fractionalChanges);
  }
  assert.equal(summary.fractionalOrderDependentMarkets, 0, '人工市場順序測試失敗');
  scenarios[mode] = summary;
}
assert.equal(scenarios.unit.roundBlockingMarkets, 0);
assert.equal(scenarios.unit.roundCapacityExcessMarkets, 0);
assert.equal(scenarios.unit.roundOrderDependentMarkets, 0);
const result = { checkedAt: new Date().toISOString(), seed: 20261008, node: process.version,
  generator: { candidateCount: 40, departmentCount: 6, quotas: '獨立離散均勻 0–20', wishCount: '獨立離散均勻 1–6',
    wishOrder: '不重複校系之隨機排列', score: '各有效邊獨立離散均勻 0–60；同分以固定 uid 排序',
    weights: ['固定 1', '連續均勻 [1,4)', '對數均勻 [1,100)'], permutationsPerMarket: 3 },
  scenarios, diagnostics, note: '人工分布用於工程病態診斷，不表示真實市場的發生機率、預測誤差或一般定理。' };
fs.writeFileSync(path.join(paper, 'data/stress-diagnostics.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result));
