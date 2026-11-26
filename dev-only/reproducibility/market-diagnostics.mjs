/** 唯讀重播歷史梯次；原始考生資料僅留於記憶體，輸出皆為彙總。 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire, registerHooks } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { auditAllocation } from './allocation-audit.mjs';
import { traceFractionalAllocation, verifyTrackedOutput } from './trace-allocation.mjs';

const MIN_PATTERN_RECORDS = 5;
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
const app = initializeApp({ credential: applicationDefault(), projectId: 'bigstudent-org' }, 'paper-readonly-v012-diagnostics');
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
  const weights = lib.solveWeights(candidates, 2026, lib.PRODUCTION_BANDS, c => c.normalizedScores, 39213);
  assert(weights.converged && weights.emptyCells === 0, '校準失敗');
  const ctx = lib.buildContext(candidates, year, weights.weightMap);
  const out = rules.runFractionalDA(ctx);
  const audit = auditAllocation(ctx, out);
  const traced = traceFractionalAllocation(ctx, rules.collect);
  verifyTrackedOutput(out, traced.output);
  assert(Math.abs(traced.ledger.balanceResidual) < 1e-7, '完整市場質量帳不吻合');
  const patterns = new Map(), eligibleCounts = new Map();
  let eligibleWishCount = 0, eligibleDemandMass = 0, eligibleSupply = 0, exactPriorityTies = 0;
  const competitors = new Map([...year.deptRowsMap.keys()].map(gid => [gid, []]));
  for (const c of candidates) {
    const pattern = MARGINAL_SUBJECTS.map(subject => c.normalizedScores[subject] >= 0 ? '1' : '0').join('');
    const entry = patterns.get(pattern) || { pattern, records: 0, mass: 0 };
    entry.records++; entry.mass += weights.weightMap.get(c.uid); patterns.set(pattern, entry);
    const wishes = ctx.eligibleByUid.get(c.uid) || [];
    eligibleWishCount += wishes.length;
    eligibleDemandMass += weights.weightMap.get(c.uid) * wishes.length;
    if (wishes.length) eligibleSupply += weights.weightMap.get(c.uid);
    for (const wish of wishes) {
      eligibleCounts.set(wish.gid, (eligibleCounts.get(wish.gid) || 0) + 1);
      competitors.get(wish.gid).push({ uid: c.uid, weightedScore: wish.score });
    }
  }
  for (const [gid, people] of competitors) {
    const compare = ctx.compareFor(gid);
    people.sort(compare);
    for (let i = 1; i < people.length; i++) if (compare(people[i-1], people[i]) === 0) exactPriorityTies++;
  }
  const normalThreshold = Math.ceil(20 * (1 - Math.min(1, candidates.length / 39213)));
  let normalLabelMismatches = 0, normalLabelChecks = 0;
  const python = process.env.PAPER_PYTHON;
  if (!python || !path.isAbsolute(python)) throw new Error('請指定 bundled Python 絕對路徑');
  const rows = JSON.parse(execFileSync(python, ['-c',
    'import csv,json,sys; print(json.dumps(list(csv.DictReader(open(sys.argv[1], newline="")))))',
    path.join(paper, 'data/department-benchmark.csv')], { encoding: 'utf8' }));
  const observedGids = new Set();
  for (const row of rows) {
    const gid = Number(row.gid);
    assert(Number.isInteger(gid) && gid > 0 && !observedGids.has(gid), '比較表校系鍵不符');
    observedGids.add(gid);
    const confidence = row.confidence;
    const expected = (eligibleCounts.get(gid) || 0) >= normalThreshold ? 'normal' : 'insufficient';
    normalLabelChecks++;
    normalLabelMismatches += Number(confidence !== expected);
  }
  const quotas = [...year.deptRowsMap.keys()].map(gid => ({ dept_group_id: gid, officialQuota: year.quotaOf(gid) }));
  const scaled = calculateScaledQuotas(quotas, candidates.length, 39213);
  const result = { checkedAt: retrievedAt, node: process.version, runId, databaseSHA256: hash(frozen), counts,
    allocationAudit: audit, ledger: traced.ledger, subjectsInPattern: MARGINAL_SUBJECTS,
    participationPatternCount: patterns.size,
    // Patterns with fewer than MIN_PATTERN_RECORDS records are merged before release to limit disclosure risk.
    participationPatterns: [...patterns.values()].filter(p => p.records >= MIN_PATTERN_RECORDS)
      .sort((a,b) => a.pattern.localeCompare(b.pattern)),
    participationPatternsSuppressed: (() => { const small = [...patterns.values()].filter(p => p.records < MIN_PATTERN_RECORDS);
      return { minimumRecords: MIN_PATTERN_RECORDS, patterns: small.length,
        records: small.reduce((s, p) => s + p.records, 0), mass: small.reduce((s, p) => s + p.mass, 0) }; })(),
    market: { departments: year.deptRowsMap.size, totalCapacity: year.totalQuota, eligibleWishCount,
      eligibleDemandMass, eligibleSupply, demandNote: '志願需求質量按邊重複累加，同一人的多個志願不是獨立全國需求。' },
    priority: { exactPriorityTies, scope: '完整合格清單排序後相鄰候選人比較；只驗證本固定市場，hash沒有最後UID回退。' },
    normalLabel: { threshold: normalThreshold, checked: normalLabelChecks, mismatches: normalLabelMismatches },
    hamilton: { departments: quotas.length, totalCapacity: year.totalQuota, scaledTotalQuota: scaled.scaledTotalQuota },
    privacy: '僅授權get/select；不保存考生原始資料或鍵，旁錄只保留彙總。' };
  assert.equal(normalLabelMismatches, 0, '保存normal標記與規則不一致');
  fs.writeFileSync(path.join(paper, 'data/market-diagnostics.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify({ market: result.market, allocationAudit: audit, ledger: traced.ledger,
    priority: result.priority, normalLabel: result.normalLabel, hamilton: result.hamilton }));
} finally {
  sqlite.close();
  delete globalThis.__paperReadonlyDatabase;
  await deleteApp(app);
}
