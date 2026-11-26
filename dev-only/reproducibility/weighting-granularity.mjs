/** v0.16 加權粒度比較：唯讀讀取一次保存梯次；個人資料只在記憶體，輸出為校系門檻與校準診斷。 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire, registerHooks } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

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
const app = initializeApp({ credential: applicationDefault(), projectId: 'bigstudent-org' }, 'paper-readonly-weighting');
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
  // ---- v0.16 H4：加權粒度比較（規格 dev-only/review/analysis-plan-v016.md）----
  const configs = [
    ['uniform', null],
    ['ew2', lib.equalWidthBands(2)],
    ['ew3', lib.PRODUCTION_BANDS],
    ['ew6', lib.equalWidthBands(6)],
    ['ew61', lib.equalWidthBands(61)],
    ['eq3', lib.equalCountBands(2026, 3)],
  ];
  function finalResidual(population, weights, bandsOf) {
    let worst = 0, cells = 0, empty = 0;
    for (const subject of MARGINAL_SUBJECTS) {
      const levels = lib.levelCounts(2026, subject);
      for (const [lo, hi] of bandsOf(subject)) {
        let target = 0, fitted = 0, sample = 0;
        for (let l = lo; l <= hi; l++) target += levels[l];
        for (const person of population) {
          const score = person.normalizedScores[subject];
          if (score >= lo && score <= hi) { fitted += weights.get(person.uid); sample++; }
        }
        if (target > 0) { cells++; if (!sample) empty++; else worst = Math.max(worst, Math.abs(fitted / target - 1)); }
      }
    }
    return { cells, emptyTargetCells: empty, maxRelativeResidualNonEmpty: worst };
  }
  const diagnosticsOut = {};
  const cutoffs = {};
  for (const [name, bandsOf] of configs) {
    let weightMap, diag;
    if (bandsOf === null) {
      weightMap = new Map(candidates.map(c => [c.uid, 39213 / candidates.length]));
      diag = { calibrated: false, nEff: candidates.length, min: 39213 / candidates.length, max: 39213 / candidates.length };
    } else {
      const s = lib.solveWeights(candidates, 2026, bandsOf, c => c.normalizedScores, 39213);
      weightMap = s.weightMap;
      diag = { calibrated: true, iterations: s.iterations, converged: s.converged, emptyCells: s.emptyCells, cellCount: s.cellCount,
        sumW: s.sumW, nEff: s.nEff, min: s.min, median: s.median, max: s.max, updateCriterion: s.maxRelErr,
        ...finalResidual(candidates, s.weightMap, bandsOf) };
    }
    const output = rules.runFractionalDA(lib.buildContext(candidates, year, weightMap));
    diag.events = output.events;
    diagnosticsOut[name] = diag;
    cutoffs[name] = new Map(benchmark.rows.map(row => [row.gid, lib.cutoffOf(output, row.gid, 'fw')]));
    console.log(JSON.stringify({ stage: 'config', name, nEff: diag.nEff, converged: diag.converged ?? null, events: output.events }));
  }
  // 正式設定必須逐系重現凍結 v3
  let maxDiff = 0;
  for (const row of benchmark.rows) {
    const value = cutoffs.ew3.get(row.gid);
    assert.equal(value === null, row.v3 === null, 'ew3 缺值型態與凍結 v3 不同');
    if (value !== null) maxDiff = Math.max(maxDiff, Math.abs(value - row.v3));
  }
  assert(maxDiff < 1e-8, 'ew3 未重現凍結 v3');
  const header = ['gid', ...configs.map(([name]) => name)];
  const lines = [header.join(',')];
  for (const row of benchmark.rows) {
    lines.push([row.gid, ...configs.map(([name]) => { const v = cutoffs[name].get(row.gid); return v === null ? '' : String(v); })].join(','));
  }
  fs.writeFileSync(path.join(paper, 'data/weighting-granularity-departments.csv'), lines.join('\n') + '\n');
  const result = { checkedAt: retrievedAt, runId, spec: 'dev-only/review/analysis-plan-v016.md', databaseSHA256: hash(frozen),
    repositoryHead: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(), node: process.version,
    firestoreDocumentsRead: snap.size + 1, counts, ew3ReproducesFrozenV3MaxDifference: maxDiff, diagnostics: diagnosticsOut,
    privacy: 'Firestore 僅 get/select 一次；個人資料只在記憶體，不落地、不列印；輸出為校系門檻與校準診斷。' };
  fs.writeFileSync(path.join(paper, 'data/weighting-granularity-diagnostics.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify({ stage: '完成', ew3ReproducesFrozenV3MaxDifference: maxDiff, firestoreDocumentsRead: snap.size + 1 }));
} finally {
  sqlite.close();
  delete globalThis.__paperReadonlyDatabase;
  await deleteApp(app);
}
