/** 唯讀重播歷史梯次；原始考生資料僅留於記憶體，輸出皆為彙總。 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire, registerHooks } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { auditAllocation } from './allocation-audit.mjs';

const paper = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const repo = process.env.BIGSTUDENT_REPOSITORY;
if (!repo || !path.isAbsolute(repo)) throw new Error('請指定平台 repository 絕對路徑');
const manifest = JSON.parse(fs.readFileSync(path.join(paper, 'data/manifest.json')));
const requireRepo = createRequire(path.join(repo, 'package.json'));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
for (const [name, expected] of Object.entries(manifest.sourceHashes)) {
  if (name === 'lib/database.db') continue;
  assert.equal(hash(fs.readFileSync(path.join(repo, name))), expected, `平台模組版本不符：${name}`);
}
const frozen = execFileSync('git', ['show', `${manifest.verifiableResearchCommit}:lib/database.db`], { cwd: repo, maxBuffer: 60_000_000 });
assert.equal(hash(frozen), manifest.sourceHashes['lib/database.db']);
const Database = requireRepo('better-sqlite3');
const sqlite = new Database(frozen, { readonly: true });
sqlite.pragma('query_only = ON');
globalThis.__paperReadonlyDatabase = sqlite;
await import(pathToFileURL(path.join(repo, 'dev-only/simulation-weighting/ts-alias-hook.mjs')));
registerHooks({
  load(url, context, nextLoad) {
    if (url === pathToFileURL(path.join(repo, 'src/lib/university-data.js')).href) {
      return { format: 'module', shortCircuit: true, source: 'export const db = globalThis.__paperReadonlyDatabase;' };
    }
    return nextLoad(url, context);
  },
});
process.env.LAB_CACHE_DIR = path.join(paper, 'dev-only/workspace');
const lib = await import(pathToFileURL(path.join(repo, 'dev-only/backtest-v3/lib.mjs')));
const rules = await import(pathToFileURL(path.join(repo, 'dev-only/simulation-weighting/da-rules.mjs')));
const scoring = await import(pathToFileURL(path.join(repo, 'src/lib/simulation/ast/scoring.ts')));
const cleaning = await import(pathToFileURL(path.join(repo, 'src/lib/simulation/ast/candidate-cleaning.ts')));
const { MARGINAL_SUBJECTS } = await import(pathToFileURL(path.join(repo, 'src/lib/simulation/ast/weighting.ts')));
const { calculateScaledQuotas } = await import(pathToFileURL(path.join(repo, 'src/lib/simulation/ast/quota.ts')));
const { initializeApp, applicationDefault, deleteApp } = requireRepo('firebase-admin/app');
const { getFirestore } = requireRepo('firebase-admin/firestore');
const app = initializeApp({ credential: applicationDefault(), projectId: 'bigstudent-org' }, 'paper-readonly-replay');
const cloud = getFirestore(app);
const runId = manifest.runId;
const ref = cloud.doc(`statistics/admission_simulation/runs/${runId}`);
const retrievedAt = new Date().toISOString();
try {
  const metadata = (await ref.get()).data();
  assert.equal(metadata?.sampleCount, 4627, '梯次樣本數不符');
  assert.equal(metadata.nationalBaselineCount, 39213);
  const snap = await ref.collection('candidates').select('duplicateOf', 'input.scores', 'input.wishes').get();
  const counts = { documents: snap.size, markedDuplicates: 0, noNormalizedScore: 0, zeroCleaningPeople: 0, zeroCleaningFields: 0 };
  const raw = [];
  const cleaned = [];
  for (const doc of snap.docs) {
    const data = doc.data();
    if (data.duplicateOf) { counts.markedDuplicates++; continue; }
    const scores = data.input?.scores || {};
    const wishes = Array.isArray(data.input?.wishes) ? data.input.wishes : [];
    assert(wishes.every(gid => Number.isInteger(gid) && gid > 0), '志願資料格式不符');
    const zero = cleaning.cleanZeroAsUnregistered(scores);
    const normalizedScores = scoring.buildNormalizedAstUserGrade(zero.cleaned);
    if (!scoring.hasAnyNormalizedAstScore(normalizedScores)) { counts.noNormalizedScore++; continue; }
    if (zero.cleanedFields.length) counts.zeroCleaningPeople++;
    counts.zeroCleaningFields += zero.cleanedFields.length;
    const base = { uid: doc.id, wishes, sourceUpdatedAt: null, inputHash: '', mergedUids: [] };
    cleaned.push({ ...base, rawScores: zero.cleaned, normalizedScores, cleanedZeroFields: zero.cleanedFields });
    raw.push({ ...base, rawScores: scores, normalizedScores: scoring.buildNormalizedAstUserGrade(scores), cleanedZeroFields: [] });
  }
  const merged = cleaning.mergeDuplicateCandidates(cleaned);
  counts.additionalMerged = merged.mergedAwayCount;
  const candidates = merged.merged;
  counts.effectiveCandidates = candidates.length;
  assert.equal(candidates.length, 4627, '清洗後候選人數不符');
  const year = lib.loadYear(2026);
  const benchmark = JSON.parse(fs.readFileSync(path.join(paper, 'sources/benchmark-snapshot.md'), 'utf8').split('```json\n')[1].split('\n```')[0]);
  const expected = new Map(benchmark.rows.map(row => [row.gid, row]));
  const shared = benchmark.rows.filter(row => row.v3 !== null && row.baseline !== null).map(row => row.gid);
  function residuals(population, weights) {
    const cells = [];
    for (const subject of MARGINAL_SUBJECTS) {
      const levels = lib.levelCounts(2026, subject);
      assert(levels, '官方邊際缺漏');
      for (const [lo, hi] of lib.PRODUCTION_BANDS(subject)) {
        let target = 0, fitted = 0, sample = 0;
        for (let l = lo; l <= hi; l++) target += levels[l];
        for (const person of population) {
          const score = person.normalizedScores[subject];
          if (score >= lo && score <= hi) { fitted += weights.get(person.uid); sample++; }
        }
        cells.push({ subject, lo, hi, sample, target, fitted, relativeResidual: target ? (fitted - target) / target : null });
      }
    }
    return { maxAbsoluteRelativeResidual: Math.max(...cells.filter(c => c.target > 0).map(c => Math.abs(c.relativeResidual))), cells };
  }
  function evaluate(out, gids = shared) {
    const values = gids.map(gid => ({ gid, value: lib.cutoffOf(out, gid, 'fw') })).filter(r => r.value !== null);
    return { n: values.length, standardizedMAE: values.reduce((sum, r) => sum + Math.abs(r.value - expected.get(r.gid).actual) / expected.get(r.gid).weightTotal, 0) / values.length,
      fixedSetSize: gids.length, missing: gids.length - values.length };
  }
  function diagnostics(solution) {
    return { iterations: solution.iterations, converged: solution.converged, emptyCells: solution.emptyCells, sumW: solution.sumW, nEff: solution.nEff,
      min: solution.min, median: solution.median, max: solution.max, updateCriterion: solution.maxRelErr };
  }
  const w = lib.solveWeights(candidates, 2026, lib.PRODUCTION_BANDS, c => c.normalizedScores, 39213);
  assert(w.converged && w.emptyCells === 0, '標準設定校準失敗');
  const ctx = lib.buildContext(candidates, year, w.weightMap);
  const out = rules.runFractionalDA(ctx);
  const allocationAudit = auditAllocation(ctx, out);
  const unit = lib.buildContext(candidates, year, new Map(candidates.map(c => [c.uid, 1])));
  const scaled = calculateScaledQuotas([...year.deptRowsMap.keys()].map(gid => ({ dept_group_id: gid, officialQuota: year.quotaOf(gid) })), candidates.length, 39213);
  unit.quotaOf = gid => scaled.departmentQuotas.get(gid)?.scaledQuota ?? 0;
  const v1 = rules.runBinaryDA(unit, 'always');
  const v2 = rules.runBinaryDA(ctx, 'round');
  const concordance = {};
  for (const [name, output, mode] of [['v1', v1, 'marginal'], ['v2', v2, 'marginal'], ['fractional', out, 'marginal'], ['v3', out, 'fw']]) {
    let maxDifference = 0, supported = 0;
    for (const row of benchmark.rows) {
      const value = lib.cutoffOf(output, row.gid, mode);
      assert.equal(value === null, row[name] === null, `${name} 缺值型態改變`);
      if (value !== null) { supported++; maxDifference = Math.max(maxDifference, Math.abs(value - row[name])); }
    }
    assert(maxDifference < 1e-8, `${name} 重播不一致`);
    concordance[name] = { supported, maxDifference };
  }
  console.log(JSON.stringify({ stage: '完整市場重播核對通過', counts, concordance }));
  const sensitivity = { reference: { ...diagnostics(w), ...evaluate(out), residuals: residuals(candidates, w.weightMap), events: out.events } };
  const outputs = { reference: out };
  for (const initialTotal of [33071, 4627]) {
    const alt = lib.solveWeights(candidates, 2026, lib.PRODUCTION_BANDS, c => c.normalizedScores, initialTotal);
    assert(alt.converged && !alt.emptyCells, '替代初始化未收斂');
    const alternative = rules.runFractionalDA(lib.buildContext(candidates, year, alt.weightMap));
    outputs[`initialize_${initialTotal}`] = alternative;
    sensitivity[`initialize_${initialTotal}`] = { ...diagnostics(alt), ...evaluate(alternative), residuals: residuals(candidates, alt.weightMap) };
  }
  const sorted = [...w.weights].sort((a, b) => a - b);
  for (const percentile of [.95, .99]) {
    const cap = sorted[Math.floor(percentile * (sorted.length - 1))];
    const weights = new Map(candidates.map(c => [c.uid, Math.min(cap, w.weightMap.get(c.uid))]));
    const alternative = rules.runFractionalDA(lib.buildContext(candidates, year, weights));
    outputs[`cap_${percentile}`] = alternative;
    sensitivity[`cap_${percentile}`] = { cap, ...evaluate(alternative), residuals: residuals(candidates, weights), note: '校準後截尾且不再校準；故意檢查邊際失配的代價，非新模型效能宣稱' };
  }
  const rescaled = new Map(candidates.map(c => [c.uid, w.weightMap.get(c.uid) * 33071 / w.sumW]));
  outputs.total_33071 = rules.runFractionalDA(lib.buildContext(candidates, year, rescaled));
  sensitivity.total_33071 = { ...evaluate(outputs.total_33071), residuals: residuals(candidates, rescaled), note: '校準後整體縮放至登記人數；不保留原考試邊際，不等同登記考生的有效校準' };
  const uncleaned = cleaning.mergeDuplicateCandidates(raw).merged;
  const uw = lib.solveWeights(uncleaned, 2026, lib.PRODUCTION_BANDS, c => c.normalizedScores, 39213);
  const uout = rules.runFractionalDA(lib.buildContext(uncleaned, year, uw.weightMap));
  outputs.keep_zero = uout;
  sensitivity.keep_zero = { candidates: uncleaned.length, ...diagnostics(uw), ...evaluate(uout), residuals: residuals(uncleaned, uw.weightMap) };
  const allCommon = shared.filter(gid => Object.values(outputs).every(output => lib.cutoffOf(output, gid) !== null));
  const commonSensitivity = { n: allCommon.length, baselineMAE: allCommon.reduce((sum, gid) => sum + Math.abs(expected.get(gid).baseline - expected.get(gid).actual) / expected.get(gid).weightTotal, 0) / allCommon.length,
    methods: Object.fromEntries(Object.entries(outputs).map(([key, output]) => [key, evaluate(output, allCommon)])) };
  const ordering = [];
  for (const seed of [20261008, 20261009, 20261010]) {
    const shuffled = [...ctx.candidateUids];
    const rand = lib.mulberry32(seed);
    for (let i = shuffled.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]; }
    const permuted = rules.runFractionalDA({ ...ctx, candidateUids: shuffled });
    let maxCutoffDifference = 0, maxMassDifference = 0;
    for (const [gid, original] of out.results) {
      const other = permuted.results.get(gid);
      const before = lib.cutoffOf(out, gid), after = lib.cutoffOf(permuted, gid);
      assert.equal(before === null, after === null, '順序測試缺值改變');
      if (before !== null) maxCutoffDifference = Math.max(maxCutoffDifference, Math.abs(before - after));
      const allocations = new Map(other.held.map(h => [h.uid, h.mass]));
      for (const held of original.held) maxMassDifference = Math.max(maxMassDifference, Math.abs(held.mass - (allocations.get(held.uid) || 0)));
      for (const held of other.held) if (!original.heldUids.has(held.uid)) maxMassDifference = Math.max(maxMassDifference, held.mass);
    }
    ordering.push({ seed, events: permuted.events, maxCutoffDifference, maxMassDifference });
  }
  const result = { checkedAt: retrievedAt, runId, databaseSHA256: hash(frozen), repositoryHead: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(), node: process.version,
    counts, concordance, allocationAudit, sensitivity, commonSensitivity, ordering, privacy: 'Firestore 僅 get/select；個人原始資料不落地、不列印；輸出為校準格與研究彙總。' };
  fs.writeFileSync(path.join(paper, 'data/replay-results.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify({ stage: '敏感度完成', allocationAudit, commonSensitivity, ordering }));
} finally {
  sqlite.close();
  delete globalThis.__paperReadonlyDatabase;
  await deleteApp(app);
}
