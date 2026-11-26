/**
 * Record-level author checks of the fourth revision (specification: dev-only/review/analysis-plan-v022.md).
 *
 * Runs only on the author's computer. It reads the pseudonymized export written by export_runs.mjs
 * (EXPORT_FILE), keeps the records in memory, and writes two kinds of output:
 *   OUT_DIR      aggregate results (author-checks-<section>.json), which are released;
 *   PRIVATE_DIR  department-level simulated cutoffs of each rerun (dept-<label>.csv) and the resampling
 *                draws, which stay on the author's computer because small departments' cutoffs are order
 *                statistics. author_stats.py turns them into aggregate statistics on the released J2 set.
 *
 * Usage: SECTION=<section> EXPORT_FILE=... PRIVATE_DIR=... OUT_DIR=... node author_checks.mjs
 * Sections: reproduce, timing, runs, variants, subsamples, trs, fit, joint, ties, halfsamples (HALF_FROM, HALF_COUNT),
 * bayesboot (BB_FROM, BB_COUNT), vintage, participation, curve (CURVE_K), tilt, bootstrap (BOOT_FROM, BOOT_COUNT),
 * bootstrap-summary. Each section is short enough to run on its own.
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { paper, lib, rules, scoring, cleaning, MARGINAL_SUBJECTS, calculateScaledQuotas, closeRuntime, provenance, manifest } from './author_runtime.mjs';

const EXPORT_FILE = process.env.EXPORT_FILE;
const PRIVATE_DIR = process.env.PRIVATE_DIR;
const OUT_DIR = process.env.OUT_DIR || path.join(paper, 'out');
const SNAPSHOT = process.env.BENCHMARK_SNAPSHOT || path.join(paper, 'sources/benchmark-snapshot.md');
if (!EXPORT_FILE || !PRIVATE_DIR) throw new Error("Set EXPORT_FILE and PRIVATE_DIR (both on the author's computer)");
const SECTION = process.env.SECTION || 'reproduce';
const DEADLINE = Date.parse('2026-08-08T08:30:00Z'); // 16:30 Taiwan time
const EVALUATED = 'ast_20260815T150000Z';
const PRE_DEADLINE = 'ast_20260808T035958Z';
const POST_DEADLINE = 'ast_20260808T095000Z';
const START_TOTAL = 39213;
const REGISTRANTS = 33071;
const LAMBDA = 0.4;
const MIN_SUPPORT = 30;
const BOOT_B = 200;
const BOOT_SEED = 20261012;

fs.mkdirSync(OUT_DIR, { recursive: true });
fs.mkdirSync(PRIVATE_DIR, { recursive: true, mode: 0o700 });
const fileSHA256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const INPUTS = { exportSHA256: fileSHA256(EXPORT_FILE), benchmarkSnapshotSHA256: fileSHA256(SNAPSHOT),
  releasedDepartmentCsvSHA256: fileSHA256(path.join(paper, 'data/department-benchmark.csv')),
  authorChecksSHA256: fileSHA256(fileURLToPath(import.meta.url)),
  authorRuntimeSHA256: fileSHA256(path.join(path.dirname(fileURLToPath(import.meta.url)), 'author_runtime.mjs')) };
if (process.env.SYNTHETIC !== '1') {
  assert.equal(INPUTS.benchmarkSnapshotSHA256, manifest.aggregateSourceSHA256, 'benchmark snapshot differs from the manifest');
  assert.equal(INPUTS.releasedDepartmentCsvSHA256, manifest.departmentCsvSHA256, 'released department file differs from the manifest');
}
const exported = JSON.parse(fs.readFileSync(EXPORT_FILE, 'utf8'));
const sanitized = {};
for (const run of exported.runs) for (const r of run.records) {
  if (!Number.isFinite(r.updatedAt)) r.updatedAt = null;
  // The platform saved cleaned preferences (first occurrence of positive integers); re-apply the rule defensively.
  const seen = new Set();
  const wishes = (Array.isArray(r.wishes) ? r.wishes : []).map(Number).filter(g => Number.isInteger(g) && g > 0 && !seen.has(g) && seen.add(g));
  if (!Array.isArray(r.wishes) || wishes.length !== r.wishes.length) sanitized[run.runId] = (sanitized[run.runId] || 0) + 1;
  r.wishes = wishes;
}
const runs = new Map(exported.runs.map(run => [run.runId, run]));
const year = lib.loadYear(2026);
const benchmark = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8').split('```json\n')[1].split('\n```')[0]);
const GIDS = benchmark.rows.map(row => row.gid);
const frozenRow = new Map(benchmark.rows.map(row => [row.gid, row]));
const J2 = readCsv(path.join(paper, 'data/department-benchmark.csv'))
  .filter(r => r.v3 !== '' && r.baseline !== '')
  .map(r => ({ gid: Number(r.gid), actual: Number(r.actual), weightTotal: Number(r.weightTotal), baseline: Number(r.baseline),
    releasedV3: Number(r.v3), school: r.school }));
assert.equal(J2.length, 1521, 'released J2 set');

function readCsv(file) {
  const text = fs.readFileSync(file, 'utf8');
  const rows = [];
  let field = '', row = [], quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else quoted = false; } else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (ch !== '\r') field += ch;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  const [head, ...body] = rows;
  return body.filter(r => r.length === head.length).map(r => Object.fromEntries(head.map((h, k) => [h, r[k]])));
}

const isNum = v => typeof v === 'number' && Number.isFinite(v);
const sum = values => values.reduce((a, b) => a + b, 0);
const quantile = (values, p) => {
  const s = values.filter(isNum).sort((a, b) => a - b);
  return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : null;
};
const runMeta = run => ({ runId: run.runId, sampleCount: run.sampleCount, nationalBaselineCount: run.nationalBaselineCount,
  algorithmVersion: run.algorithmVersion, completedAt: run.completedAt ? new Date(run.completedAt).toISOString() : null,
  documents: run.records.length });
function save(name, value) {
  const file = path.join(OUT_DIR, `author-checks-${name}.json`);
  fs.writeFileSync(file, JSON.stringify({ section: name, computedAt: new Date().toISOString(), exportedAt: exported.exportedAt,
    recordsWithSanitizedPreferences: sanitized, inputs: INPUTS, provenance: provenance(), ...value }, null, 2) + '\n');
  console.log(JSON.stringify({ wrote: file }));
}

/** The research loader: drop mirror copies, reclassify zero Advanced Subjects grades, normalize, merge identical inputs. */
function prepare(records, { zeroCleaning = true } = {}) {
  const counts = { documents: records.length, mirrorCopies: 0, noValidScore: 0, zeroCleaningRecords: 0 };
  const list = [];
  for (const r of records) {
    if (r.dup) { counts.mirrorCopies++; continue; }
    const zero = zeroCleaning ? cleaning.cleanZeroAsUnregistered(r.scores || {}) : { cleaned: { ...(r.scores || {}) }, cleanedFields: [] };
    const normalizedScores = scoring.buildNormalizedAstUserGrade(zero.cleaned);
    if (!scoring.hasAnyNormalizedAstScore(normalizedScores)) { counts.noValidScore++; continue; }
    if (zero.cleanedFields.length) counts.zeroCleaningRecords++;
    list.push({ uid: r.id, wishes: r.wishes, rawScores: zero.cleaned, normalizedScores, sourceUpdatedAt: null,
      inputHash: '', mergedUids: [], cleanedZeroFields: zero.cleanedFields, updatedAt: r.updatedAt });
  }
  const merged = cleaning.mergeDuplicateCandidates(list);
  counts.mergedAway = merged.mergedAwayCount;
  counts.effective = merged.merged.length;
  return { candidates: merged.merged, counts };
}

const rake = (cands, bandsOf = lib.PRODUCTION_BANDS, total = START_TOTAL) =>
  lib.solveWeights(cands, 2026, bandsOf, c => c.normalizedScores, total);
const weightSummary = w => ({ converged: w.converged, iterations: w.iterations, emptyCells: w.emptyCells, cells: w.cellCount,
  maxRelErr: w.maxRelErr, sumW: w.sumW, nEff: w.nEff, min: w.min, median: w.median, max: w.max });
const cutoffs = (out, mode) => new Map(GIDS.map(gid => [gid, lib.cutoffOf(out, gid, mode)]));
function simulate(cands, weightMap) {
  const ctx = lib.buildContext(cands, year, weightMap);
  const out = rules.runFractionalDA(ctx);
  return { ctx, out, v3: cutoffs(out, 'fw'), fractional: cutoffs(out, 'marginal') };
}
function listings(cands) {
  const m = new Map();
  for (const c of cands) for (const g of c.wishes) m.set(g, (m.get(g) || 0) + 1);
  return m;
}
function writeDepartments(label, columns) {
  const keys = Object.keys(columns);
  const lines = ['gid,' + keys.join(',')];
  for (const gid of GIDS) lines.push([gid, ...keys.map(k => { const v = columns[k].get(gid); return isNum(v) ? String(v) : ''; })].join(','));
  fs.writeFileSync(path.join(PRIVATE_DIR, `dept-${label}.csv`), lines.join('\n') + '\n', { mode: 0o600 });
}
/** Quick J2 summary (author_stats.py computes the reported statistics and intervals). */
function j2Metrics(pred) {
  let covered = 0, absPred = 0, absMix = 0, absBase = 0, absBaseCovered = 0, flagged = 0, agree = 0, sumS = 0, mixAbove = 0;
  for (const r of J2) {
    const v = pred.get(r.gid);
    const base = Math.abs(r.baseline - r.actual) / r.weightTotal;
    absBase += base;
    const mix = isNum(v) ? LAMBDA * v + (1 - LAMBDA) * r.baseline : r.baseline;
    absMix += Math.abs(mix - r.actual) / r.weightTotal;
    if ((mix - r.actual) / r.weightTotal <= -1) mixAbove++;
    if (!isNum(v)) continue;
    covered++;
    absPred += Math.abs(v - r.actual) / r.weightTotal;
    absBaseCovered += base;
    const s = (v - r.baseline) / r.weightTotal, d = (r.actual - r.baseline) / r.weightTotal;
    sumS += s;
    if (Math.abs(s) >= 1 && d !== 0) { flagged++; if ((s > 0) === (d > 0)) agree++; }
  }
  return { covered, predMAE: covered ? absPred / covered : null, baselineMAECovered: covered ? absBaseCovered / covered : null,
    mixMAE: absMix / J2.length, baselineMAE: absBase / J2.length, mixMinusBaseline: (absMix - absBase) / J2.length,
    meanS: covered ? sumS / covered : null, flagged, directionAgreement: flagged ? agree / flagged : null,
    mixOfficialAboveShare: mixAbove / J2.length };
}
const inputKey = r => JSON.stringify([Object.keys(r.scores || {}).sort().map(k => [k, r.scores[k]]), r.wishes]);

/** Subject bands of a given width, merged with a neighbour until each has MIN_SUPPORT records and a positive target. */
function collapsedBands(cands, width, minSupport) {
  const out = new Map();
  for (const subject of MARGINAL_SUBJECTS) {
    const counts = lib.levelCounts(2026, subject);
    if (!counts) { out.set(subject, []); continue; }
    const support = new Array(61).fill(0);
    for (const c of cands) { const v = c.normalizedScores[subject]; if (isNum(v) && v >= 0 && v <= 60) support[v]++; }
    let bands = [];
    for (let lo = 0; lo <= 60; lo += width) bands.push([lo, Math.min(60, lo + width - 1)]);
    if (width === 10) bands = [[0, 9], [10, 19], [20, 29], [30, 39], [40, 49], [50, 60]];
    const stat = ([lo, hi]) => { let s = 0, t = 0; for (let l = lo; l <= hi; l++) { s += support[l]; t += counts[l]; } return { s, t }; };
    // Drop bands with neither target nor records; they constrain nothing.
    bands = bands.filter(b => { const { s, t } = stat(b); return s > 0 || t > 0; });
    for (;;) {
      const bad = bands.findIndex(b => { const { s, t } = stat(b); return s < minSupport || t <= 0; });
      if (bad < 0 || bands.length === 1) break;
      const left = bad - 1, right = bad + 1;
      const pick = left < 0 ? right : right >= bands.length ? left : (stat(bands[left]).s <= stat(bands[right]).s ? left : right);
      const [a, b] = [Math.min(bad, pick), Math.max(bad, pick)];
      bands.splice(a, 2, [bands[a][0], bands[b][1]]);
    }
    // Keep the full 0-60 range covered so that no record escapes the subject's margin.
    if (bands.length) { bands[0] = [0, bands[0][1]]; bands[bands.length - 1] = [bands[bands.length - 1][0], 60]; }
    for (let k = 1; k < bands.length; k++) bands[k] = [bands[k - 1][1] + 1, bands[k][1]];
    out.set(subject, bands);
  }
  return out;
}

/** Raking with weights bounded to [lo, hi] after every adjustment (truncated raking). */
function boundedRake(cands, bandsOf, lo, hi, total = START_TOTAL) {
  const n = cands.length;
  const w = new Array(n).fill(total / n);
  const cells = [];
  for (const subject of MARGINAL_SUBJECTS) {
    const counts = lib.levelCounts(2026, subject);
    if (!counts) continue;
    for (const [a, b] of bandsOf(subject)) {
      let target = 0;
      for (let l = a; l <= b; l++) target += counts[l];
      const idxs = [];
      for (let i = 0; i < n; i++) { const v = cands[i].normalizedScores[subject]; if (isNum(v) && v >= a && v <= b) idxs.push(i); }
      if (idxs.length && target > 0) cells.push({ idxs, target });
    }
  }
  let iterations = 0, maxRelErr = Infinity;
  for (; iterations < 2000; iterations++) {
    for (const c of cells) {
      let cur = 0;
      for (const i of c.idxs) cur += w[i];
      const f = c.target / cur;
      for (const i of c.idxs) w[i] = Math.min(hi, Math.max(lo, w[i] * f));
    }
    maxRelErr = 0;
    for (const c of cells) { let cur = 0; for (const i of c.idxs) cur += w[i]; maxRelErr = Math.max(maxRelErr, Math.abs(cur / c.target - 1)); }
    if (maxRelErr < 0.001) break;
  }
  const sumW = sum(w), sumSq = sum(w.map(x => x * x));
  const sorted = [...w].sort((a, b) => a - b);
  return { weightMap: new Map(cands.map((c, i) => [c.uid, w[i]])),
    summary: { converged: maxRelErr < 0.001, iterations: iterations + 1, maxRelErr, sumW, nEff: sumW * sumW / sumSq,
      min: sorted[0], median: sorted[Math.floor(n / 2)], max: sorted[n - 1], lower: lo, upper: hi } };
}

/** Truncate-replicate-sample integerization (Lovelace and Ballas, 2013). The remainder is drawn by systematic
 * sampling in random order, so that each record gains a copy with probability equal to its fractional part. */
function trsCounts(weights, rand) {
  const counts = weights.map(w => Math.floor(w));
  const frac = weights.map((w, i) => w - counts[i]);
  const order = frac.map((f, i) => [rand(), i]).sort((a, b) => a[0] - b[0]).map(x => x[1]);
  const start = rand();
  let cum = 0;
  for (const i of order) {
    const before = cum;
    cum += frac[i];
    if (Math.floor(cum - start) > Math.floor(before - start)) counts[i]++;
  }
  return counts;
}

/** Ordinary student-proposing deferred acceptance for whole persons with official quotas. */
function wholePersonDA(ctx) {
  const dept = new Map([...ctx.deptIds].map(gid => [gid, { quota: ctx.quotaOf(gid), held: [] }]));
  const ptr = new Map();
  const queue = [];
  for (const uid of ctx.candidateUids) if ((ctx.eligibleByUid.get(uid) || []).length) { ptr.set(uid, 0); queue.push(uid); }
  for (let head = 0; head < queue.length; head++) {
    const uid = queue[head];
    const el = ctx.eligibleByUid.get(uid);
    let p = ptr.get(uid);
    for (; p < el.length; p++) {
      const wish = el[p];
      const d = dept.get(wish.gid);
      if (!d || d.quota <= 0) continue;
      const cmp = ctx.compareFor(wish.gid);
      const entry = { uid, weightedScore: wish.score };
      let lo = 0, hi = d.held.length;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (cmp(d.held[mid], entry) <= 0) lo = mid + 1; else hi = mid; }
      if (lo >= d.quota) continue;
      d.held.splice(lo, 0, entry);
      if (d.held.length > d.quota) {
        const out = d.held.pop();
        ptr.set(out.uid, ptr.get(out.uid) + 1);
        queue.push(out.uid);
      }
      break;
    }
    ptr.set(uid, p);
  }
  return new Map(GIDS.map(gid => { const d = dept.get(gid); return [gid, d && d.held.length ? d.held[d.held.length - 1].weightedScore : null]; }));
}

function evaluatedCandidates() {
  const prepared = prepare(runs.get(EVALUATED).records);
  if (process.env.SYNTHETIC !== '1') assert.equal(prepared.candidates.length, 4627, 'evaluated records');
  return prepared;
}

try {
  if (SECTION === 'reproduce') {
    const run = runs.get(EVALUATED);
    const { candidates, counts } = evaluatedCandidates();
    const total = run.nationalBaselineCount ?? START_TOTAL;
    const w = rake(candidates, lib.PRODUCTION_BANDS, total);
    const sim = simulate(candidates, w.weightMap);
    const v2 = rules.runBinaryDA(sim.ctx, 'round');
    const scaled = calculateScaledQuotas([...year.deptRowsMap.keys()].map(gid => ({ dept_group_id: gid, officialQuota: year.quotaOf(gid) })),
      candidates.length, total);
    const uniform = lib.buildContext(candidates, year, new Map(candidates.map(c => [c.uid, 1])));
    uniform.quotaOf = gid => scaled.departmentQuotas.get(gid)?.scaledQuota ?? 0;
    const v1 = rules.runBinaryDA(uniform, 'always');
    const methods = { v1: cutoffs(v1, 'marginal'), v2: cutoffs(v2, 'marginal'), fractional: sim.fractional, v3: sim.v3 };
    const comparison = {};
    for (const [name, values] of Object.entries(methods)) {
      let both = 0, availabilityDiffers = 0, identical = 0, within001 = 0, maxAbs = 0, n = 0, rec = 0, fro = 0;
      for (const gid of GIDS) {
        const a = values.get(gid), f = frozenRow.get(gid)[name];
        if (isNum(a) !== isNum(f)) { availabilityDiffers++; continue; }
        if (!isNum(a)) continue;
        both++;
        const diff = Math.abs(a - f);
        if (diff < 1e-8) identical++;
        if (diff < 0.01) within001++;
        maxAbs = Math.max(maxAbs, diff);
      }
      for (const r of J2) {
        const a = values.get(r.gid), f = frozenRow.get(r.gid)[name];
        if (!isNum(a) || !isNum(f)) continue;
        n++; rec += Math.abs(a - r.actual) / r.weightTotal; fro += Math.abs(f - r.actual) / r.weightTotal;
      }
      comparison[name] = { both, availabilityDiffers, identical, within001, maxAbsDifference: maxAbs, j2Common: n,
        j2MAEReconstructed: rec / n, j2MAEFrozen: fro / n };
    }
    const eligibleCounts = candidates.map(c => (sim.ctx.eligibleByUid.get(c.uid) || []).length);
    writeDepartments('evaluated-main', { prediction: sim.v3, fractional: sim.fractional, v2: methods.v2, v1: methods.v1, listings: listings(candidates) });
    save('reproduce', { run: runMeta(run), counts, raking: weightSummary(w), frozenRaking: benchmark.raking, comparison,
      records: { noEligiblePreference: eligibleCounts.filter(k => k === 0).length,
        meanEligiblePreferences: sum(eligibleCounts) / candidates.length,
        meanListedPreferences: sum(candidates.map(c => c.wishes.length)) / candidates.length },
      j2: j2Metrics(sim.v3) });
  }

  if (SECTION === 'timing') {
    const byRun = exported.runs.map(run => {
      const own = run.records.filter(r => !r.dup);
      const t = own.map(r => r.updatedAt);
      return { ...runMeta(run), nonMirror: own.length,
        updatedBeforeDeadline: t.filter(x => x !== null && x <= DEADLINE).length,
        updatedAfterDeadline: t.filter(x => x !== null && x > DEADLINE).length,
        missingTimestamp: t.filter(x => x === null).length,
        updatedAfterRunCompleted: run.completedAt ? t.filter(x => x !== null && x > run.completedAt).length : null };
    });
    const ev = runs.get(EVALUATED), pre = runs.get(PRE_DEADLINE), post = runs.get(POST_DEADLINE);
    const own = run => new Map(run.records.filter(r => !r.dup).map(r => [r.id, r]));
    const evMap = own(ev), preMap = own(pre), postMap = own(post);
    const panel = { evaluatedRecords: evMap.size, alsoInPreDeadlineRun: 0, identicalToPreDeadline: 0, changedSincePreDeadline: 0,
      newSincePreDeadline: 0, preDeadlineRecordsLeft: [...preMap.keys()].filter(id => !evMap.has(id)).length,
      byUpdate: { beforeDeadline: { identical: 0, changed: 0, new: 0 }, afterDeadline: { identical: 0, changed: 0, new: 0 }, missing: { identical: 0, changed: 0, new: 0 } } };
    for (const [id, r] of evMap) {
      const group = r.updatedAt === null ? 'missing' : r.updatedAt <= DEADLINE ? 'beforeDeadline' : 'afterDeadline';
      if (!preMap.has(id)) { panel.newSincePreDeadline++; panel.byUpdate[group].new++; continue; }
      panel.alsoInPreDeadlineRun++;
      if (inputKey(preMap.get(id)) === inputKey(r)) { panel.identicalToPreDeadline++; panel.byUpdate[group].identical++; }
      else { panel.changedSincePreDeadline++; panel.byUpdate[group].changed++; }
    }
    // Changes between the last pre-deadline run and the first post-deadline run, by update time.
    const nearDeadline = { postDeadlineRecords: postMap.size, identical: 0, changed: 0, new: 0, changedUpdatedAfterDeadline: 0, newUpdatedAfterDeadline: 0 };
    for (const [id, r] of postMap) {
      const after = r.updatedAt !== null && r.updatedAt > DEADLINE;
      if (!preMap.has(id)) { nearDeadline.new++; if (after) nearDeadline.newUpdatedAfterDeadline++; continue; }
      if (inputKey(preMap.get(id)) === inputKey(r)) nearDeadline.identical++;
      else { nearDeadline.changed++; if (after) nearDeadline.changedUpdatedAfterDeadline++; }
    }
    // Effective (research-loader) records of the evaluated run by update time, and their listings.
    const { candidates } = evaluatedCandidates();
    const after = candidates.filter(c => c.updatedAt !== null && c.updatedAt > DEADLINE);
    const byDay = {};
    for (const c of candidates) {
      const key = c.updatedAt === null ? 'missing' : c.updatedAt < Date.parse('2026-08-01T16:00:00Z') ? 'before 2 August (Taiwan)'
        : new Date(c.updatedAt + 8 * 3600e3).toISOString().slice(0, 10);
      byDay[key] = (byDay[key] || 0) + 1;
    }
    save('timing', { deadline: new Date(DEADLINE).toISOString(), byRun, panel, nearDeadline,
      evaluatedEffective: { records: candidates.length, updatedAfterDeadline: after.length,
        updatedBeforeDeadline: candidates.filter(c => c.updatedAt !== null && c.updatedAt <= DEADLINE).length,
        missing: candidates.filter(c => c.updatedAt === null).length, byTaiwanDay: byDay } });
  }

  if (SECTION === 'runs') {
    const summary = [];
    const runOne = (label, records, extra = {}) => {
      const { candidates, counts } = prepare(records);
      const w = rake(candidates);
      const sim = simulate(candidates, w.weightMap);
      writeDepartments(label, { prediction: sim.v3, fractional: sim.fractional, listings: listings(candidates) });
      summary.push({ label, ...extra, counts, raking: weightSummary(w), j2: j2Metrics(sim.v3) });
      console.log(JSON.stringify({ label, n: candidates.length, ...j2Metrics(sim.v3) }));
    };
    for (const run of exported.runs) runOne(`run-${run.runId}`, run.records, { run: runMeta(run) });
    // The zero-grade rule triggered in some early runs; rerun those without it (exploratory, fourth review).
    for (const run of exported.runs) {
      if (!prepare(run.records).counts.zeroCleaningRecords) continue;
      const { candidates, counts } = prepare(run.records, { zeroCleaning: false });
      const w = rake(candidates);
      const sim = simulate(candidates, w.weightMap);
      writeDepartments(`run-${run.runId}-no-zero-cleaning`, { prediction: sim.v3, fractional: sim.fractional, listings: listings(candidates) });
      summary.push({ label: `run-${run.runId}-no-zero-cleaning`, run: runMeta(run), counts, raking: weightSummary(w), j2: j2Metrics(sim.v3) });
    }
    // Deadline reconstruction: the first post-deadline run, with records updated after the deadline replaced by their
    // version in the last pre-deadline run (dropped if absent).
    const pre = new Map(runs.get(PRE_DEADLINE).records.filter(r => !r.dup).map(r => [r.id, r]));
    const recon = [];
    const reconCounts = { keptUpdatedBeforeDeadline: 0, replacedByPreDeadlineVersion: 0, droppedNoPreDeadlineVersion: 0, keptMissingTimestamp: 0 };
    for (const r of runs.get(POST_DEADLINE).records) {
      if (r.dup) continue;
      if (r.updatedAt === null) { reconCounts.keptMissingTimestamp++; recon.push(r); }
      else if (r.updatedAt <= DEADLINE) { reconCounts.keptUpdatedBeforeDeadline++; recon.push(r); }
      else if (pre.has(r.id)) { reconCounts.replacedByPreDeadlineVersion++; recon.push(pre.get(r.id)); }
      else reconCounts.droppedNoPreDeadlineVersion++;
    }
    runOne('deadline-reconstructed', recon, { reconstruction: reconCounts });
    // Evaluated records in their latest known pre-deadline state.
    const post = new Map(runs.get(POST_DEADLINE).records.filter(r => !r.dup).map(r => [r.id, r]));
    const states = [];
    const stateCounts = { unchanged: 0, fromFirstPostDeadlineRun: 0, fromLastPreDeadlineRun: 0, dropped: 0 };
    for (const r of runs.get(EVALUATED).records) {
      if (r.dup) continue;
      if (r.updatedAt !== null && r.updatedAt <= DEADLINE) { stateCounts.unchanged++; states.push(r); continue; }
      const p = post.get(r.id);
      if (p && p.updatedAt !== null && p.updatedAt <= DEADLINE) { stateCounts.fromFirstPostDeadlineRun++; states.push(p); continue; }
      if (pre.has(r.id)) { stateCounts.fromLastPreDeadlineRun++; states.push(pre.get(r.id)); continue; }
      stateCounts.dropped++;
    }
    runOne('evaluated-pre-deadline-states', states, { reconstruction: stateCounts });
    runOne('evaluated-updated-before-deadline', runs.get(EVALUATED).records.filter(r => r.updatedAt !== null && r.updatedAt <= DEADLINE));
    save('runs', { note: 'v3 rerun with the current code and the frozen database on each saved input; raking starts at 39,213', summary });
  }

  if (SECTION === 'variants') {
    const { candidates } = evaluatedCandidates();
    const main = rake(candidates);
    const meanW = main.sumW / candidates.length;
    const variants = [];
    const record = (label, cands, weightMap, extra = {}) => {
      const sim = simulate(cands, weightMap);
      const ws = cands.map(c => weightMap.get(c.uid));
      writeDepartments(`variant-${label}`, { prediction: sim.v3, fractional: sim.fractional, listings: listings(cands) });
      variants.push({ label, records: cands.length, totalWeight: sum(ws), nEff: sum(ws) ** 2 / sum(ws.map(x => x * x)), ...extra, j2: j2Metrics(sim.v3) });
      console.log(JSON.stringify({ label, ...j2Metrics(sim.v3) }));
    };
    record('main', candidates, main.weightMap, { raking: weightSummary(main) });
    record('registrant-scaled', candidates, new Map(candidates.map(c => [c.uid, main.weightMap.get(c.uid) * REGISTRANTS / main.sumW])));
    record('uniform-calibrated-total', candidates, new Map(candidates.map(c => [c.uid, main.sumW / candidates.length])));
    record('uniform-registrants', candidates, new Map(candidates.map(c => [c.uid, REGISTRANTS / candidates.length])));
    const ctx0 = lib.buildContext(candidates, year, main.weightMap);
    const eligible = candidates.filter(c => (ctx0.eligibleByUid.get(c.uid) || []).length > 0);
    const we = rake(eligible);
    record('exclude-no-eligible', eligible, we.weightMap, { excluded: candidates.length - eligible.length, raking: weightSummary(we) });
    for (const [label, width] of [['collapsed-ten-grade', 10], ['collapsed-single-grade', 1]]) {
      const bands = collapsedBands(candidates, width, MIN_SUPPORT);
      const w = rake(candidates, s => bands.get(s) || []);
      record(label, candidates, w.weightMap, { raking: weightSummary(w),
        bandsPerSubject: Object.fromEntries([...bands].map(([s, b]) => [s, b.length])) });
    }
    for (const [lo, hi] of [[0.2, 5], [0.2, 10]]) {
      const bounded = boundedRake(candidates, lib.PRODUCTION_BANDS, lo * meanW, hi * meanW);
      record(`bounded-${lo}-${hi}`, candidates, bounded.weightMap, { raking: bounded.summary });
    }
    for (const k of [5, 10, 20, 40]) {
      const truncated = candidates.map(c => ({ ...c, wishes: c.wishes.slice(0, k) }));
      record(`truncate-${k}`, truncated, main.weightMap, { meanListed: sum(truncated.map(c => c.wishes.length)) / truncated.length });
    }
    save('variants', { meanWeight: meanW, minSupport: MIN_SUPPORT, variants });
  }

  if (SECTION === 'subsamples') {
    const { candidates } = evaluatedCandidates();
    const results = [];
    for (const fraction of [0.25, 0.5, 0.75]) {
      for (let s = 0; s < 5; s++) {
        const rand = lib.mulberry32(20261126 + 10 * s + Math.round(fraction * 4));
        const keyed = candidates.map(c => [rand(), c]).sort((a, b) => a[0] - b[0]);
        const sample = keyed.slice(0, Math.round(fraction * candidates.length)).map(x => x[1]);
        const w = rake(sample);
        const sim = simulate(sample, w.weightMap);
        const label = `subsample-${Math.round(fraction * 100)}-${s}`;
        writeDepartments(label, { prediction: sim.v3, fractional: sim.fractional, listings: listings(sample) });
        results.push({ label, fraction, seedIndex: s, records: sample.length, raking: weightSummary(w), j2: j2Metrics(sim.v3) });
        console.log(JSON.stringify({ label, ...j2Metrics(sim.v3) }));
      }
    }
    save('subsamples', { results });
  }

  if (SECTION === 'trs') {
    const { candidates } = evaluatedCandidates();
    const main = rake(candidates);
    const sim = simulate(candidates, main.weightMap);
    const weights = candidates.map(c => main.weightMap.get(c.uid));
    const from = Number(process.env.TRS_FROM || 0), count = Number(process.env.TRS_COUNT || 10);
    const results = [];
    for (let s = from; s < Math.min(10, from + count); s++) {
      const counts = trsCounts(weights, lib.mulberry32(20261500 + s));
      const population = [];
      candidates.forEach((c, i) => { for (let k = 0; k < counts[i]; k++) population.push({ ...c, uid: `${c.uid}#${k}` }); });
      const ctx = lib.buildContext(population, year, new Map(population.map(p => [p.uid, 1])));
      const cut = wholePersonDA(ctx);
      writeDepartments(`trs-${s}`, { prediction: cut });
      let n = 0, dFrac = 0, dV3 = 0;
      for (const r of J2) {
        const a = cut.get(r.gid), f = sim.fractional.get(r.gid), v = sim.v3.get(r.gid);
        if (!isNum(a) || !isNum(f) || !isNum(v)) continue;
        n++; dFrac += Math.abs(a - f) / r.weightTotal; dV3 += Math.abs(a - v) / r.weightTotal;
      }
      results.push({ seed: 20261500 + s, persons: population.length, zeroCopies: counts.filter(k => k === 0).length,
        j2: j2Metrics(cut), commonWithFractional: n, meanAbsDiffFromFractional: dFrac / n, meanAbsDiffFromV3: dV3 / n });
      console.log(JSON.stringify(results[results.length - 1]));
    }
    const file = path.join(OUT_DIR, 'author-checks-trs.json');
    const previous = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')).results.filter(r => !results.some(x => x.seed === r.seed)) : [];
    save('trs', { calibratedTotal: main.sumW, results: [...previous, ...results].sort((a, b) => a.seed - b.seed) });
  }

  if (SECTION === 'fit') {
    const { candidates } = evaluatedCandidates();
    const main = rake(candidates);
    const meanW = main.sumW / candidates.length;
    const ten = collapsedBands(candidates, 10, MIN_SUPPORT), single = collapsedBands(candidates, 1, MIN_SUPPORT);
    const weightings = {
      'three-band (production)': main.weightMap,
      'collapsed ten-grade': rake(candidates, s => ten.get(s) || []).weightMap,
      'collapsed single-grade': rake(candidates, s => single.get(s) || []).weightMap,
      'bounded 0.2-5': boundedRake(candidates, lib.PRODUCTION_BANDS, 0.2 * meanW, 5 * meanW).weightMap,
      'bounded 0.2-10': boundedRake(candidates, lib.PRODUCTION_BANDS, 0.2 * meanW, 10 * meanW).weightMap,
      'uniform at calibrated total': new Map(candidates.map(c => [c.uid, meanW])),
    };
    const bands = lib.PRODUCTION_BANDS();
    const result = {};
    for (const [label, wm] of Object.entries(weightings)) {
      const subjects = {};
      for (const subject of MARGINAL_SUBJECTS) {
        const official = lib.levelCounts(2026, subject);
        if (!official) continue;
        const est = new Array(61).fill(0);
        for (const c of candidates) { const v = c.normalizedScores[subject]; if (isNum(v) && v >= 0 && v <= 60) est[v] += wm.get(c.uid); }
        const tOff = sum(official), tEst = sum(est);
        const tae = sum(official.map((o, l) => Math.abs(est[l] - o))) / tOff;
        const within = bands.map(([lo, hi]) => {
          let o = 0, ol = 0, e = 0, el = 0, records = 0;
          for (let l = lo; l <= hi; l++) { o += official[l]; ol += l * official[l]; e += est[l]; el += l * est[l]; }
          for (const c of candidates) { const v = c.normalizedScores[subject]; if (isNum(v) && v >= lo && v <= hi) records++; }
          // Means of bands with fewer than ten records are suppressed (counts below five are not shown).
          const shown = records >= 10;
          return { band: [lo, hi], records: records >= 5 ? records : '<5', officialMean: o ? ol / o : null,
            weightedMean: shown && e ? el / e : null, difference: shown && o && e ? el / e - ol / o : null };
        });
        subjects[subject] = { officialTotal: tOff, weightedTotal: tEst, gradeTAE: tae, withinBand: within };
      }
      const diffs = Object.values(subjects).flatMap(s => s.withinBand.map(b => b.difference)).filter(isNum);
      result[label] = { meanGradeTAE: sum(Object.values(subjects).map(s => s.gradeTAE)) / Object.keys(subjects).length,
        meanAbsWithinBandDifference: sum(diffs.map(Math.abs)) / diffs.length,
        meanWithinBandDifference: sum(diffs) / diffs.length, subjects };
    }
    save('fit', { note: 'per-grade total absolute error and within-band weighted mean grade against the official 2026 distributions', result });
  }


  if (SECTION === 'joint') {
    // Joint distribution beyond the calibrated margins: the official 2026 tables of unweighted totals by subject
    // combination (announced before registration, so counting examinees) against the calibrated records.
    const { candidates } = evaluatedCandidates();
    const main = rake(candidates);
    const meanW = main.sumW / candidates.length;
    const tables = JSON.parse(fs.readFileSync(path.join(paper, 'data/combination-tables.json'), 'utf8')).tables;
    const departments = JSON.parse(fs.readFileSync(path.join(paper, 'data/baseline-inputs.json'), 'utf8')).departments;
    const field = subject => (subject.startsWith('gsat') ? 'ast_' + subject : subject);
    const comboKey = items => items.map(i => field(i.subject)).sort().join('+');
    const interpolate = (xs, ys, x) => {
      if (x <= xs[0]) return ys[0];
      if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
      for (let k = 1; k < xs.length; k++) if (x <= xs[k]) return xs[k] === xs[k - 1] ? ys[k] : ys[k - 1] + (x - xs[k - 1]) / (xs[k] - xs[k - 1]) * (ys[k] - ys[k - 1]);
      return ys[ys.length - 1];
    };
    // Mid-point count at or above a total, as in practice_baseline.py.
    const countAbove = (rows, total) => interpolate(rows.map(r => r.level), rows.map(r => r.cum_above - r.people / 2), total);
    function platformTable(subjects, weightOf) {
      const maxLevel = 60 * subjects.length;
      const people = new Array(maxLevel + 1).fill(0);
      let records = 0;
      for (const c of candidates) {
        let total = 0, ok = true;
        for (const s of subjects) { const v = c.normalizedScores[s]; if (!isNum(v) || v < 0) { ok = false; break; } total += v; }
        if (!ok) continue;
        records++;
        people[total] += weightOf(c);
      }
      const rows = [];
      let above = sum(people);
      for (let level = 0; level <= maxLevel; level++) { rows.push({ level, people: people[level], cum_above: above }); above -= people[level]; }
      return { rows, records, total: sum(people) };
    }
    const weightings = { calibrated: c => main.weightMap.get(c.uid), uniform: () => meanW };
    const combos = [];
    for (const [key, official] of Object.entries(tables)) {
      if (!key.startsWith('2026:')) continue;
      const subjects = key.slice(5).split('+');
      const N = official[official.length - 1].cum_below;
      const entry = { combination: key.slice(5), officialExaminees: N };
      for (const [name, weightOf] of Object.entries(weightings)) {
        const p = platformTable(subjects, weightOf);
        if (p.records < 5) { entry[name] = { records: '<5' }; continue; }
        const tail = {};
        for (const q of [0.5, 0.75, 0.9, 0.95]) {
          // Official total with a share q of examinees below it.
          const t = interpolate(official.map(r => r.cum_below / N), official.map(r => r.level), q);
          tail[q] = Math.log(countAbove(p.rows, t) / countAbove(official, t));
        }
        entry[name] = { records: p.records, logRatioAll: Math.log(p.total / N), logRatioAboveOfficialQuantile: tail };
      }
      combos.push(entry);
    }
    const released = new Map(J2.map(r => [r.gid, r]));
    const deps = [];
    for (const d of departments) {
      const r = released.get(d.gid);
      if (!r || !d.items?.length || new Set(d.items.map(i => i.weight)).size !== 1) continue;
      const official = tables[`2026:${comboKey(d.items)}`];
      if (!official) continue;
      const m = d.items[0].weight;
      const t = r.actual / m;
      const subjects = d.items.map(i => field(i.subject));
      const entry = { e: (r.releasedV3 - r.actual) / r.weightTotal, S: (r.releasedV3 - r.baseline) / r.weightTotal,
        D: (r.actual - r.baseline) / r.weightTotal, school: r.school };
      for (const [name, weightOf] of Object.entries(weightings)) {
        const p = platformTable(subjects, weightOf);
        const a = countAbove(p.rows, t), o = countAbove(official, t);
        entry[name] = a > 0 && o > 0 ? Math.log(a / o) : null;
      }
      deps.push(entry);
    }
    const rank = v => { const idx = v.map((x, i) => [x, i]).sort((a, b) => a[0] - b[0]); const r = new Array(v.length); let k = 0;
      while (k < idx.length) { let j = k; while (j + 1 < idx.length && idx[j + 1][0] === idx[k][0]) j++; for (let t = k; t <= j; t++) r[idx[t][1]] = (k + j) / 2; k = j + 1; } return r; };
    const pearson = (x, y) => { const mx = sum(x) / x.length, my = sum(y) / y.length; let a = 0, b = 0, c = 0;
      for (let i = 0; i < x.length; i++) { a += (x[i] - mx) * (y[i] - my); b += (x[i] - mx) ** 2; c += (y[i] - my) ** 2; } return a / Math.sqrt(b * c); };
    const spearman = (x, y) => pearson(rank(x), rank(y));
    const slope = (x, y) => { const mx = sum(x) / x.length, my = sum(y) / y.length; let a = 0, b = 0;
      for (let i = 0; i < x.length; i++) { a += (x[i] - mx) * (y[i] - my); b += (x[i] - mx) ** 2; } return a / b; };
    const depSummary = {};
    for (const name of Object.keys(weightings)) {
      const use = deps.filter(d => isNum(d[name]));
      const rho = use.map(d => d[name]);
      depSummary[name] = { departments: use.length, schools: new Set(use.map(d => d.school)).size,
        logRatio: { p25: quantile(rho, 0.25), median: quantile(rho, 0.5), p75: quantile(rho, 0.75), meanAbs: sum(rho.map(Math.abs)) / rho.length },
        spearmanWithError: spearman(rho, use.map(d => d.e)), spearmanWithS: spearman(rho, use.map(d => d.S)),
        spearmanWithD: spearman(rho, use.map(d => d.D)), slopeErrorOnLogRatio: slope(rho, use.map(d => d.e)),
        meanErrorByLogRatioSign: { over: (() => { const u = use.filter(d => d[name] > 0); return { n: u.length, meanError: sum(u.map(d => d.e)) / u.length }; })(),
          under: (() => { const u = use.filter(d => d[name] <= 0); return { n: u.length, meanError: sum(u.map(d => d.e)) / u.length }; })() } };
    }
    const comboSummary = {};
    for (const name of Object.keys(weightings)) {
      const shown = combos.filter(c => isNum(c[name]?.logRatioAll));
      comboSummary[name] = { combinations: shown.length,
        medianAbsLogRatioAll: quantile(shown.map(c => Math.abs(c[name].logRatioAll)), 0.5),
        medianAbsLogRatioAbove: Object.fromEntries([0.5, 0.75, 0.9, 0.95].map(q => [q, quantile(shown.map(c => Math.abs(c[name].logRatioAboveOfficialQuantile[q])), 0.5)])),
        medianLogRatioAbove: Object.fromEntries([0.5, 0.75, 0.9, 0.95].map(q => [q, quantile(shown.map(c => c[name].logRatioAboveOfficialQuantile[q]), 0.5)])) };
    }
    save('joint', { note: 'log ratios of calibrated (or uniformly weighted) record mass to official examinees at or above a total; released v3 values for errors',
      comboSummary, departmentSummary: depSummary, combinations: combos });
  }

  if (SECTION === 'ties') {
    // The final tie-break hashes the account identifier, which the export pseudonymizes. Re-drawing it with
    // 20 salts, at fixed weights, measures how much the cutoffs depend on that arbitrary order.
    const { candidates } = evaluatedCandidates();
    const main = rake(candidates);
    const results = [];
    for (let s = 0; s < 20; s++) {
      const salted = candidates.map(c => ({ ...c, uid: `${c.uid}~${s}` }));
      const weightMap = new Map(salted.map((c, i) => [c.uid, main.weightMap.get(candidates[i].uid)]));
      const sim = simulate(salted, weightMap);
      writeDepartments(`ties-${s}`, { prediction: sim.v3, fractional: sim.fractional });
      let changed = 0, compared = 0;
      for (const gid of GIDS) {
        const a = sim.v3.get(gid), f = frozenRow.get(gid).v3;
        if (!isNum(a) || !isNum(f)) continue;
        compared++;
        if (Math.abs(a - f) > 1e-8) changed++;
      }
      results.push({ salt: s, departmentsCompared: compared, departmentsDifferentFromFrozen: changed, j2: j2Metrics(sim.v3) });
      console.log(JSON.stringify(results[results.length - 1]));
    }
    const range = key => { const v = results.map(r => r.j2[key]); return { min: Math.min(...v), max: Math.max(...v) }; };
    save('ties', { salts: 20, predMAE: range('predMAE'), mixMinusBaseline: range('mixMinusBaseline'),
      directionAgreement: range('directionAgreement'), results });
  }

  if (SECTION === 'tilt') {
    // Preference selection within score cells (exploratory, fourth review): records of one kind are made Γ times as
    // likely before raking, which then restores every score margin, so the tilt changes only the mix of preferences
    // within score cells. Kinds: records listing a larger than median share of private institutions; records with
    // longer than median lists.
    const { candidates } = evaluatedCandidates();
    const N = candidates.length;
    const isPublic = gid => /^(國立|.*市立)/.test(String(year.deptRowsMap.get(gid)?.['學校名稱'] || ''));
    const privateShare = candidates.map(c => { const l = c.wishes.filter(g => year.deptRowsMap.has(g)); return l.length ? l.filter(g => !isPublic(g)).length / l.length : 0; });
    const median = v => { const s = [...v].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
    const groups = {
      'private-leaning': (() => { const m = median(privateShare); return privateShare.map(x => x > m); })(),
      'long-lists': (() => { const m = median(candidates.map(c => c.wishes.length)); return candidates.map(c => c.wishes.length > m); })(),
    };
    const cells = [];
    for (const subject of MARGINAL_SUBJECTS) {
      const counts = lib.levelCounts(2026, subject);
      if (!counts) continue;
      for (const [a, b] of lib.PRODUCTION_BANDS(subject)) {
        let target = 0;
        for (let l = a; l <= b; l++) target += counts[l];
        const idxs = [];
        for (let i = 0; i < N; i++) { const v = candidates[i].normalizedScores[subject]; if (isNum(v) && v >= a && v <= b) idxs.push(i); }
        cells.push({ idxs, target });
      }
    }
    const rakeFrom = init => {
      const w = [...init];
      let iterations = 0, maxRelErr = Infinity;
      for (; iterations < 2000; iterations++) {
        maxRelErr = 0;
        for (const c of cells) {
          if (!c.idxs.length || c.target <= 0) continue;
          let cur = 0;
          for (const i of c.idxs) cur += w[i];
          const f = c.target / cur;
          maxRelErr = Math.max(maxRelErr, Math.abs(f - 1));
          for (const i of c.idxs) w[i] *= f;
        }
        if (maxRelErr < 0.001) break;
      }
      return { w, converged: maxRelErr < 0.001, iterations: iterations + 1 };
    };
    const results = [];
    for (const [name, member] of Object.entries(groups)) {
      for (const gamma of [0.8, 1.25]) {
        const init = member.map(m => (m ? gamma : 1));
        const scale = START_TOTAL / sum(init);
        const { w, converged } = rakeFrom(init.map(x => x * scale));
        const share = sum(w.filter((_, i) => member[i])) / sum(w);
        const base = rake(candidates);
        const baseShare = sum(candidates.map((c, i) => (member[i] ? base.weightMap.get(c.uid) : 0))) / base.sumW;
        const sim = simulate(candidates, new Map(candidates.map((c, i) => [c.uid, w[i]])));
        writeDepartments(`tilt-${name}-${gamma}`, { prediction: sim.v3 });
        results.push({ group: name, gamma, records: member.filter(Boolean).length, converged, weightedShare: share, productionShare: baseShare, j2: j2Metrics(sim.v3) });
        console.log(JSON.stringify(results[results.length - 1]));
      }
    }
    save('tilt', { note: 'Γ multiplies the starting weight of the group before raking to the production margins', results });
  }

  if (SECTION === 'curve') {
    // Learning curve (exploratory, added during the fourth simulated review): 20 random subsamples without
    // replacement of k/8 of the evaluated records for k = 1..7, each recalibrated and reallocated.
    const { candidates } = evaluatedCandidates();
    const N = candidates.length;
    const ks = (process.env.CURVE_K || '1,2,3,4,5,6,7').split(',').map(Number);
    if (ks[0] === 1) fs.rmSync(path.join(PRIVATE_DIR, 'curve-reps.jsonl'), { force: true });
    for (const k of ks) {
      for (let d = 0; d < 20; d++) {
        const rand = lib.mulberry32(20261300 + 100 * k + d);
        const sample = candidates.map(c => [rand(), c]).sort((a, b) => a[0] - b[0]).slice(0, Math.round(k * N / 8)).map(x => x[1]);
        const w = rake(sample);
        const sim = simulate(sample, w.weightMap);
        fs.appendFileSync(path.join(PRIVATE_DIR, 'curve-reps.jsonl'), JSON.stringify({ k, d, records: sample.length,
          converged: w.converged, nEff: w.nEff, ...j2Metrics(sim.v3) }) + '\n', { mode: 0o600 });
      }
    }
    const reps = [...new Map(fs.readFileSync(path.join(PRIVATE_DIR, 'curve-reps.jsonl'), 'utf8').trim().split('\n')
      .map(l => JSON.parse(l)).map(r => [`${r.k}-${r.d}`, r])).values()];
    const byK = {};
    for (const r of reps) (byK[r.k] ||= []).push(r);
    const stat = (list, key) => { const v = list.map(r => r[key]).filter(isNum); const m = sum(v) / v.length;
      return { mean: m, sd: Math.sqrt(sum(v.map(x => (x - m) ** 2)) / Math.max(1, v.length - 1)), min: Math.min(...v), max: Math.max(...v) }; };
    save('curve', { draws: 20, levels: Object.fromEntries(Object.entries(byK).map(([k, list]) => [k, { n: list.length, records: list[0].records,
      allConverged: list.every(r => r.converged), predMAE: stat(list, 'predMAE'), mixMinusBaseline: stat(list, 'mixMinusBaseline'),
      directionAgreement: stat(list, 'directionAgreement'), mixOfficialAboveShare: stat(list, 'mixOfficialAboveShare'), meanS: stat(list, 'meanS'),
      nEff: stat(list, 'nEff') }])), note: 'Subsamples without replacement; spreads shrink as the share grows because draws overlap.' });
  }

  if (SECTION === 'halfsamples') {
    // Delete-half jackknife (exploratory, added during the fourth simulated review): half-samples drawn without
    // replacement, each recalibrated and reallocated. For a statistic of the whole sample, the variance across
    // half-samples estimates its sampling variance without the location shift of the with-replacement bootstrap.
    const runId = process.env.HALF_RUN || EVALUATED;
    const { candidates } = runId === EVALUATED ? evaluatedCandidates() : prepare(runs.get(runId).records);
    const tag = runId === EVALUATED ? '' : `-${runId}`;
    const N = candidates.length, half = Math.floor(N / 2);
    const from = Number(process.env.HALF_FROM || 0), count = Number(process.env.HALF_COUNT || 50);
    if (from === 0) fs.rmSync(path.join(PRIVATE_DIR, `halfsample-reps${tag}.jsonl`), { force: true });
    for (let k = from; k < Math.min(100, from + count); k++) {
      const rand = lib.mulberry32(20261201 + k);
      const sample = candidates.map(c => [rand(), c]).sort((a, b) => a[0] - b[0]).slice(0, half).map(x => x[1]);
      const w = rake(sample);
      const sim = simulate(sample, w.weightMap);
      const frac = Object.fromEntries(Object.entries(j2Metrics(sim.fractional)).map(([key, v]) => ['fractional_' + key, v]));
      fs.appendFileSync(path.join(PRIVATE_DIR, `halfsample-reps${tag}.jsonl`), JSON.stringify({ k, converged: w.converged,
        emptyCells: w.emptyCells, nEff: w.nEff, ...j2Metrics(sim.v3), ...frac }) + '\n', { mode: 0o600 });
    }
    const file = path.join(PRIVATE_DIR, `halfsample-reps${tag}.jsonl`);
    const reps = [...new Map(fs.readFileSync(file, 'utf8').trim().split('\n').map(l => JSON.parse(l)).map(r => [r.k, r])).values()];
    if (reps.length === 100) {
      const sd = key => { const v = reps.map(r => r[key]).filter(isNum); const m = sum(v) / v.length; return Math.sqrt(sum(v.map(x => (x - m) ** 2)) / (v.length - 1)); };
      const mean = key => { const v = reps.map(r => r[key]).filter(isNum); return sum(v) / v.length; };
      save(`halfsamples${tag}`, { runId, draws: reps.length, records: half, seeds: '20261201-20261300', allConverged: reps.every(r => r.converged),
        mean: Object.fromEntries(['predMAE', 'mixMinusBaseline', 'directionAgreement', 'mixOfficialAboveShare', 'meanS', 'fractional_predMAE',
          'fractional_mixMinusBaseline', 'fractional_directionAgreement'].map(key => [key, mean(key)])),
        sd: Object.fromEntries(['predMAE', 'mixMinusBaseline', 'directionAgreement', 'mixOfficialAboveShare', 'meanS', 'fractional_predMAE',
          'fractional_mixMinusBaseline', 'fractional_directionAgreement'].map(key => [key, sd(key)])),
        share: { mixBetterThanBaseline: reps.filter(r => r.mixMinusBaseline < 0).length / reps.length },
        note: 'Delete-half jackknife: the standard deviation across half-samples estimates the sampling standard deviation of the full-sample statistic; the means are those of half-size samples.' });
    }
  }

  if (SECTION === 'bayesboot') {
    // Bayesian bootstrap with calibration (exploratory, added during the fourth simulated review): every record is
    // kept, with a random Exp(1) multiplier on its starting weight, and raking then restores the margins. Unlike
    // resampling with replacement, no record is lost, so the draws are not shifted toward smaller samples.
    const { candidates } = evaluatedCandidates();
    const N = candidates.length;
    const from = Number(process.env.BB_FROM || 0), count = Number(process.env.BB_COUNT || 100);
    if (from === 0) fs.rmSync(path.join(PRIVATE_DIR, 'bayesboot-reps.jsonl'), { force: true });
    const cells = [];
    for (const subject of MARGINAL_SUBJECTS) {
      const counts = lib.levelCounts(2026, subject);
      if (!counts) continue;
      for (const [a, b] of lib.PRODUCTION_BANDS(subject)) {
        let target = 0;
        for (let l = a; l <= b; l++) target += counts[l];
        const idxs = [];
        for (let i = 0; i < N; i++) { const v = candidates[i].normalizedScores[subject]; if (isNum(v) && v >= a && v <= b) idxs.push(i); }
        cells.push({ idxs, target });
      }
    }
    for (let b = from; b < Math.min(200, from + count); b++) {
      const rand = lib.mulberry32(20261210 + b);
      const g = candidates.map(() => -Math.log(1 - rand()));
      const scale = START_TOTAL / sum(g);
      const w = g.map(x => x * scale);
      let iterations = 0, maxRelErr = Infinity;
      for (; iterations < 2000; iterations++) {
        maxRelErr = 0;
        for (const c of cells) {
          if (!c.idxs.length || c.target <= 0) continue;
          let cur = 0;
          for (const i of c.idxs) cur += w[i];
          if (cur <= 0) continue;
          const f = c.target / cur;
          maxRelErr = Math.max(maxRelErr, Math.abs(f - 1));
          for (const i of c.idxs) w[i] *= f;
        }
        if (maxRelErr < 0.001) break;
      }
      const sim = simulate(candidates, new Map(candidates.map((c, i) => [c.uid, w[i]])));
      fs.appendFileSync(path.join(PRIVATE_DIR, 'bayesboot-reps.jsonl'), JSON.stringify({ b, converged: maxRelErr < 0.001,
        iterations: iterations + 1, sumW: sum(w), ...j2Metrics(sim.v3) }) + '\n', { mode: 0o600 });
    }
    const file = path.join(PRIVATE_DIR, 'bayesboot-reps.jsonl');
    const reps = [...new Map(fs.readFileSync(file, 'utf8').trim().split('\n').map(l => JSON.parse(l)).map(r => [r.b, r])).values()];
    if (reps.length === 200) {
      const summarize = key => { const v = reps.map(r => r[key]).filter(isNum); return { p025: quantile(v, 0.025), p50: quantile(v, 0.5), p975: quantile(v, 0.975), mean: sum(v) / v.length }; };
      save('bayesboot', { B: 200, seeds: '20261210-20261409', allConverged: reps.every(r => r.converged),
        v3MAE: summarize('predMAE'), mixMAE: summarize('mixMAE'), mixMinusBaseline: summarize('mixMinusBaseline'),
        shareMixBetterThanBaseline: reps.filter(r => r.mixMinusBaseline < 0).length / reps.length,
        directionAgreement: summarize('directionAgreement'), meanS: summarize('meanS'), covered: summarize('covered') });
    }
  }

  if (SECTION === 'vintage') {
    // The whole-person rule (v2, current code) on the last pre-deadline records and on the deadline reconstruction.
    const pre = new Map(runs.get(PRE_DEADLINE).records.filter(r => !r.dup).map(r => [r.id, r]));
    const recon = [];
    for (const r of runs.get(POST_DEADLINE).records) {
      if (r.dup) continue;
      if (r.updatedAt === null || r.updatedAt <= DEADLINE) recon.push(r);
      else if (pre.has(r.id)) recon.push(pre.get(r.id));
    }
    const out = {};
    for (const [label, records] of [['run-ast_20260808T035958Z', runs.get(PRE_DEADLINE).records], ['deadline-reconstructed', recon]]) {
      const { candidates } = prepare(records);
      const w = rake(candidates);
      const ctx = lib.buildContext(candidates, year, w.weightMap);
      const v2 = cutoffs(rules.runBinaryDA(ctx, 'round'), 'marginal');
      writeDepartments(`v2-${label}`, { prediction: v2 });
      out[label] = { records: candidates.length, j2: j2Metrics(v2) };
      console.log(JSON.stringify({ label, ...j2Metrics(v2) }));
    }
    save('vintage', { note: 'whole-person (v2) rule with the current code on the pre-deadline inputs', out });
  }

  if (SECTION === 'participation') {
    // (a) Coverage of each subject band by records; (b) weighted preference-list length; (c) Lee-type bounds for the
    // mass that represents test-takers who did not register: remove 2,840.5 units from the top or the bottom of a
    // composite percentile without recalibrating, and rerun.
    const { candidates } = evaluatedCandidates();
    const main = rake(candidates);
    const coverage = {};
    for (const subject of MARGINAL_SUBJECTS) {
      const counts = lib.levelCounts(2026, subject);
      if (!counts) continue;
      coverage[subject] = lib.PRODUCTION_BANDS(subject).map(([a, b]) => {
        let official = 0, records = 0;
        for (let l = a; l <= b; l++) official += counts[l];
        for (const c of candidates) { const v = c.normalizedScores[subject]; if (isNum(v) && v >= a && v <= b) records++; }
        return { band: [a, b], records: records >= 5 ? records : '<5', official, coverage: records >= 5 ? records / official : null };
      });
    }
    const ctx0 = lib.buildContext(candidates, year, main.weightMap);
    const W = sum(candidates.map(c => main.weightMap.get(c.uid)));
    const listed = sum(candidates.map(c => main.weightMap.get(c.uid) * c.wishes.length)) / W;
    const eligible = sum(candidates.map(c => main.weightMap.get(c.uid) * (ctx0.eligibleByUid.get(c.uid) || []).length)) / W;
    const pr = {};
    for (const subject of MARGINAL_SUBJECTS) {
      const counts = lib.levelCounts(2026, subject);
      if (!counts) continue;
      const total = sum(counts);
      const below = []; let run = 0;
      for (let l = 0; l <= 60; l++) { below.push(run); run += counts[l]; }
      pr[subject] = level => (below[level] + counts[level] / 2) / total;
    }
    const composite = c => {
      const v = Object.keys(pr).map(s => c.normalizedScores[s]).map((x, k) => [x, Object.keys(pr)[k]]).filter(([x]) => isNum(x) && x >= 0 && x <= 60);
      return v.length ? sum(v.map(([x, s]) => pr[s](x))) / v.length : 0.5;
    };
    const excess = main.sumW - REGISTRANTS;
    const order = candidates.map(c => [composite(c), c]).sort((a, b) => a[0] - b[0]);
    const bounds = {};
    for (const side of ['top', 'bottom']) {
      const seq = side === 'top' ? [...order].reverse() : order;
      const wm = new Map(main.weightMap);
      let left = excess;
      for (const [, c] of seq) {
        if (left <= 0) break;
        const w = wm.get(c.uid), take = Math.min(w, left);
        wm.set(c.uid, w - take); left -= take;
      }
      const sim = simulate(candidates, wm);
      writeDepartments(`participation-${side}`, { prediction: sim.v3 });
      bounds[side] = { removedMass: excess, j2: j2Metrics(sim.v3) };
      console.log(JSON.stringify({ side, ...j2Metrics(sim.v3) }));
    }
    save('participation', { coverage, weightedMeanListed: listed, weightedMeanEligible: eligible, officialPreferencesPerRegistrant: 55, bounds,
      note: 'Coverage counts records per production band against official examinees; bands with fewer than five records are suppressed. Bounds remove the mass in excess of the registrants from the top or bottom of the mean percentile rank across subjects, without recalibration.' });
  }

  if (SECTION === 'bootstrap') {
    const { candidates } = evaluatedCandidates();
    const N = candidates.length;
    const from = Number(process.env.BOOT_FROM || 0), count = Number(process.env.BOOT_COUNT || 20);
    if (from === 0) for (const f of ['bootstrap-draws.jsonl', 'bootstrap-reps.jsonl']) fs.rmSync(path.join(PRIVATE_DIR, f), { force: true });
    const rand = lib.mulberry32(BOOT_SEED);
    for (let k = 0; k < from * N; k++) rand();
    const started = Date.now();
    for (let b = from; b < Math.min(BOOT_B, from + count); b++) {
      const sample = [];
      for (let k = 0; k < N; k++) { const c = candidates[Math.floor(rand() * N)]; sample.push({ ...c, uid: `${c.uid}#${k}` }); }
      const w = rake(sample);
      const sim = simulate(sample, w.weightMap);
      fs.appendFileSync(path.join(PRIVATE_DIR, 'bootstrap-draws.jsonl'), JSON.stringify({ b, v3: GIDS.map(g => sim.v3.get(g)) }) + '\n', { mode: 0o600 });
      fs.appendFileSync(path.join(PRIVATE_DIR, 'bootstrap-reps.jsonl'), JSON.stringify({ b, converged: w.converged, emptyCells: w.emptyCells,
        nEff: w.nEff, sumW: w.sumW, ...j2Metrics(sim.v3) }) + '\n', { mode: 0o600 });
    }
    console.log(JSON.stringify({ from, count, seconds: (Date.now() - started) / 1000 }));
  }

  if (SECTION === 'bootstrap-summary') {
    const reps = new Map();
    for (const line of fs.readFileSync(path.join(PRIVATE_DIR, 'bootstrap-reps.jsonl'), 'utf8').trim().split('\n')) { const r = JSON.parse(line); reps.set(r.b, r); }
    const draws = new Map();
    for (const line of fs.readFileSync(path.join(PRIVATE_DIR, 'bootstrap-draws.jsonl'), 'utf8').trim().split('\n')) { const r = JSON.parse(line); draws.set(r.b, r.v3); }
    assert.equal(reps.size, BOOT_B, 'all replicates present');
    assert.equal(draws.size, BOOT_B, 'all draws present');
    const list = [...reps.values()];
    const summarize = key => { const v = list.map(r => r[key]).filter(isNum); return { p025: quantile(v, 0.025), p50: quantile(v, 0.5), p975: quantile(v, 0.975), mean: sum(v) / v.length }; };
    const lines = ['gid,valid,p05,p50,p95'];
    let tested = 0, inside = 0;
    const widths = [];
    const j2Set = new Map(J2.map(r => [r.gid, r]));
    GIDS.forEach((gid, k) => {
      const arr = [...draws.values()].map(v => v[k]).filter(isNum);
      const p05 = quantile(arr, 0.05), p50 = quantile(arr, 0.5), p95 = quantile(arr, 0.95);
      lines.push([gid, arr.length, p05 ?? '', p50 ?? '', p95 ?? ''].join(','));
      const r = j2Set.get(gid);
      if (r && arr.length >= 0.9 * BOOT_B) {
        tested++;
        if (r.actual >= p05 && r.actual <= p95) inside++;
        widths.push((p95 - p05) / r.weightTotal);
      }
    });
    fs.writeFileSync(path.join(PRIVATE_DIR, 'bootstrap-departments.csv'), lines.join('\n') + '\n', { mode: 0o600 });
    save('bootstrap', { spec: 'dev-only/review/analysis-plan-v018.md (H6)', B: BOOT_B, seed: BOOT_SEED,
      allConverged: list.every(r => r.converged), maxEmptyCells: Math.max(...list.map(r => r.emptyCells)),
      v3MAE: summarize('predMAE'), mixMAE: summarize('mixMAE'), mixMinusBaseline: summarize('mixMinusBaseline'),
      shareMixBetterThanBaseline: list.filter(r => r.mixMinusBaseline < 0).length / BOOT_B,
      directionAgreement: summarize('directionAgreement'), meanS: summarize('meanS'), covered: summarize('covered'), nEff: summarize('nEff'),
      departmentsTested: tested, officialInside90: tested ? inside / tested : null, medianStandardizedWidth90: quantile(widths, 0.5),
      note: 'Departments with at least 180 valid draws among the released J2 set; department quantiles are kept on the author\'s computer.' });
  }
} finally {
  closeRuntime();
}
