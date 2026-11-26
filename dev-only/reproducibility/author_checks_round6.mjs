/**
 * Checks added after the sixth round of simulated reviews (exploratory; specification:
 * dev-only/review/analysis-plan-v025.md, written before these computations; Supplement S32).
 *
 * Same inputs, runtime and outputs as author_checks.mjs, whose short helpers it repeats so that the earlier scripts,
 * and the hashes recorded with their outputs, stay unchanged. Runs only on the author's computer; aggregates go to
 * OUT_DIR (author-checks-<section>.json) and department-level values computed from records to PRIVATE_DIR. The
 * engine section reads no record except to recompute the evaluated run's v3 for the August rule, and writes
 * OUT_DIR/engine-2026.csv, whose engine columns come from public admission data only.
 *
 * Sections:
 *   engine       the production placement engine's 2026 cutoffs (before and after its quota adjustment) and the
 *                August backtest's complete rule, rebuilt with the platform's own functions (plan A);
 *   synthetic    v3 with each record's preferences replaced by a list generated from public information (plan B);
 *   placements   each record's placement under the baseline, the engine, v2, v3 and the combination against the
 *                official-cutoff reconstruction, by mean-grade fifth (plan C; run engine first);
 *   quota2025    v3 with 2025 quotas (plan D);
 *   earliest     v3 with each account's earliest saved preference list, and how lists changed (plan E);
 *   tilt         the selection tilts of S27h with Γ in {0.25, 0.5, 2, 4}, plus records listing mostly low-level
 *                departments (plan F);
 *   small        non-returners' subjects and grades, content hashes of the saved runs, and each department's Kish
 *                effective sample size (plan G1-G3);
 *   halves       40 delete-half replicates with department-level values, for subgroup standard deviations (plan G5).
 *
 * Usage: SECTION=<section> EXPORT_FILE=... PRIVATE_DIR=... OUT_DIR=... node author_checks_round6.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { paper, repo, lib, rules, scoring, cleaning, MARGINAL_SUBJECTS, closeRuntime, provenance, manifest } from './author_runtime.mjs';

const threshold = await import(pathToFileURL(path.join(repo, 'src/lib/predict/common/threshold.ts')));
const quotaAdjustment = await import(pathToFileURL(path.join(repo, 'src/lib/predict/ast/quota-adjustment.ts')));

const EXPORT_FILE = process.env.EXPORT_FILE;
const PRIVATE_DIR = process.env.PRIVATE_DIR;
const OUT_DIR = process.env.OUT_DIR || path.join(paper, 'out');
const SNAPSHOT = process.env.BENCHMARK_SNAPSHOT || path.join(paper, 'sources/benchmark-snapshot.md');
if (!EXPORT_FILE || !PRIVATE_DIR) throw new Error("Set EXPORT_FILE and PRIVATE_DIR (both on the author's computer)");
const SECTION = process.env.SECTION || 'engine';
const DEADLINE = Date.parse('2026-08-08T08:30:00Z'); // 16:30 Taiwan time
const EVALUATED = 'ast_20260815T150000Z';
const PRE_DEADLINE = 'ast_20260808T035958Z';
const START_TOTAL = 39213;
const LAMBDA = 0.4;
const SEED = 20261126;

fs.mkdirSync(OUT_DIR, { recursive: true });
fs.mkdirSync(PRIVATE_DIR, { recursive: true, mode: 0o700 });
const fileSHA256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const here = path.dirname(fileURLToPath(import.meta.url));
const INPUTS = { exportSHA256: fileSHA256(EXPORT_FILE), benchmarkSnapshotSHA256: fileSHA256(SNAPSHOT),
  releasedDepartmentCsvSHA256: fileSHA256(path.join(paper, 'data/department-benchmark.csv')),
  authorChecksRound6SHA256: fileSHA256(fileURLToPath(import.meta.url)),
  authorRuntimeSHA256: fileSHA256(path.join(here, 'author_runtime.mjs')),
  planSHA256: fileSHA256(path.join(paper, 'dev-only/review/analysis-plan-v025.md')) };
if (process.env.SYNTHETIC !== '1') {
  assert.equal(INPUTS.benchmarkSnapshotSHA256, manifest.aggregateSourceSHA256, 'benchmark snapshot differs from the manifest');
  assert.equal(INPUTS.releasedDepartmentCsvSHA256, manifest.departmentCsvSHA256, 'released department file differs from the manifest');
}
const exported = JSON.parse(fs.readFileSync(EXPORT_FILE, 'utf8'));
const sanitized = {};
for (const run of exported.runs) for (const r of run.records) {
  if (!Number.isFinite(r.updatedAt)) r.updatedAt = null;
  const seen = new Set();
  const wishes = (Array.isArray(r.wishes) ? r.wishes : []).map(Number).filter(g => Number.isInteger(g) && g > 0 && !seen.has(g) && seen.add(g));
  if (!Array.isArray(r.wishes) || wishes.length !== r.wishes.length) sanitized[run.runId] = (sanitized[run.runId] || 0) + 1;
  r.wishes = wishes;
}
const runs = new Map(exported.runs.map(run => [run.runId, run]));
const runOrder = exported.runs.map(run => run.runId).sort();
const year = lib.loadYear(2026);
const benchmark = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8').split('```json\n')[1].split('\n```')[0]);
const GIDS = benchmark.rows.map(row => row.gid);
const released = readCsv(path.join(paper, 'data/department-benchmark.csv'));
const byGid = new Map(released.map(r => [Number(r.gid), r]));
const OFFICIAL = new Map(released.map(r => [Number(r.gid), Number(r.actual)]));
const BASELINE = new Map(released.filter(r => r.baseline !== '').map(r => [Number(r.gid), Number(r.baseline)]));
const WEIGHT_TOTAL = new Map(released.map(r => [Number(r.gid), Number(r.weightTotal)]));
const J2 = released.filter(r => r.v3 !== '' && r.baseline !== '')
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
const mean = values => (values.length ? sum(values) / values.length : null);
const quantile = (values, p) => {
  const s = values.filter(isNum).sort((a, b) => a - b);
  return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : null;
};
function save(name, value) {
  const file = path.join(OUT_DIR, `author-checks-${name}.json`);
  fs.writeFileSync(file, JSON.stringify({ section: name, computedAt: new Date().toISOString(), exportedAt: exported.exportedAt,
    recordsWithSanitizedPreferences: sanitized, inputs: INPUTS, provenance: provenance(), ...value }, null, 2) + '\n');
  console.log(JSON.stringify({ wrote: file }));
}
/** The research loader, as in author_checks.mjs. */
function prepare(records) {
  const counts = { documents: records.length, mirrorCopies: 0, noValidScore: 0, zeroCleaningRecords: 0 };
  const list = [];
  for (const r of records) {
    if (r.dup) { counts.mirrorCopies++; continue; }
    const zero = cleaning.cleanZeroAsUnregistered(r.scores || {});
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
function evaluatedCandidates() {
  const prepared = prepare(runs.get(EVALUATED).records);
  if (process.env.SYNTHETIC !== '1') assert.equal(prepared.candidates.length, 4627, 'evaluated records');
  return prepared;
}
const rake = cands => lib.solveWeights(cands, 2026, lib.PRODUCTION_BANDS, c => c.normalizedScores, START_TOTAL);
const cutoffs = (out, mode) => new Map(GIDS.map(gid => [gid, lib.cutoffOf(out, gid, mode)]));
function simulate(cands, weightMap, quotaOf = null) {
  const base = lib.buildContext(cands, year, weightMap);
  const ctx = quotaOf ? { ...base, quotaOf } : base;
  const out = rules.runFractionalDA(ctx);
  let assigned = 0;
  for (const gid of ctx.deptIds) assigned += out.results.get(gid)?.assignedWeight ?? 0;
  const total = sum(cands.map(c => weightMap.get(c.uid) || 0));
  return { ctx, out, v3: cutoffs(out, 'fw'), fractional: cutoffs(out, 'marginal'), unassignedShare: 1 - assigned / total };
}
function writeDepartments(label, columns) {
  const keys = Object.keys(columns);
  const lines = ['gid,' + keys.join(',')];
  for (const gid of GIDS) lines.push([gid, ...keys.map(k => { const v = columns[k].get(gid); return isNum(v) ? String(v) : ''; })].join(','));
  fs.writeFileSync(path.join(PRIVATE_DIR, `dept-${label}.csv`), lines.join('\n') + '\n', { mode: 0o600 });
}
/** Quick J2 summary; author_round6_stats.py computes the reported statistics and intervals. */
function j2Metrics(pred) {
  let covered = 0, absPred = 0, absMix = 0, absBase = 0, flagged = 0, agree = 0, sumS = 0, mixAbove = 0, biasPred = 0;
  let lowN = 0, lowBias = 0;
  for (const r of J2) {
    const v = pred.get(r.gid);
    absBase += Math.abs(r.baseline - r.actual) / r.weightTotal;
    const mix = isNum(v) ? LAMBDA * v + (1 - LAMBDA) * r.baseline : r.baseline;
    absMix += Math.abs(mix - r.actual) / r.weightTotal;
    if ((mix - r.actual) / r.weightTotal <= -1) mixAbove++;
    if (!isNum(v)) continue;
    covered++;
    absPred += Math.abs(v - r.actual) / r.weightTotal;
    biasPred += (v - r.actual) / r.weightTotal;
    if (r.baseline / r.weightTotal < 30) { lowN++; lowBias += (v - r.actual) / r.weightTotal; }
    const s = (v - r.baseline) / r.weightTotal, d = (r.actual - r.baseline) / r.weightTotal;
    sumS += s;
    if (Math.abs(s) >= 1 && d !== 0) { flagged++; if ((s > 0) === (d > 0)) agree++; }
  }
  return { covered, predMAE: covered ? absPred / covered : null, predBias: covered ? biasPred / covered : null,
    biasBelowLevel30: lowN ? lowBias / lowN : null, mixMAE: absMix / J2.length, baselineMAE: absBase / J2.length,
    mixMinusBaseline: (absMix - absBase) / J2.length, meanS: covered ? sumS / covered : null, flagged,
    directionAgreement: flagged ? agree / flagged : null, mixOfficialAboveShare: mixAbove / J2.length };
}
const isUniform = items => items.length > 1 && new Set(items.map(i => i.weight)).size === 1;
const modeOf = items => (isUniform(items) ? 'official-combo' : 'comonotonic');
const isPublicSchool = school => /^(國立|臺北市立|高雄市立|市立)/.test(String(school || ''));
const levelOf = gid => (BASELINE.has(gid) ? BASELINE.get(gid) / WEIGHT_TOTAL.get(gid) : null);
/** Mean grade over the subjects a record took (normalized grades are negative for subjects not taken), as in S20b. */
const meanGrade = c => mean(Object.values(c.normalizedScores).filter(v => isNum(v) && v >= 0));
const subjectsTaken = c => Object.values(c.normalizedScores).filter(v => isNum(v) && v >= 0).length;

try {
  if (SECTION === 'engine') {
    const years = new Map();
    for (const y of [2026, 2025, 2024, 2023]) { try { years.set(y, lib.loadYear(y)); } catch { /* year absent */ } }
    const y26 = years.get(2026), y25 = years.get(2025);
    // The simulation side uses the released v3 of the evaluated run (the values behind every reported statistic), so
    // this section reads no record; departments whose v3 is withheld fall back to the history side.
    const RELEASED_V3 = new Map(released.filter(r => r.v3 !== '').map(r => [Number(r.gid), Number(r.v3)]));
    const releasedV3 = new Set(RELEASED_V3.keys());
    const sim = { v3: RELEASED_V3 };
    const rows = [];
    const tally = {};
    const bump = key => { tally[key] = (tally[key] || 0) + 1; };
    for (const gid of GIDS) {
      const row = y26.deptRowsMap.get(gid);
      const out = { gid };
      rows.push(out);
      if (!row) { bump('noRuleRow'); continue; }
      const newW = lib.weightItemsOf(row);
      if (newW.hasSkill || !newW.items.length) { bump('skillOrNoItems'); continue; }
      const newItems = newW.items;
      // The engine's history: the most recent year before 2026 with an admission score (results of 2026 were not yet known).
      let ry = null;
      for (const y of [2025, 2024, 2023]) {
        const c = years.get(y);
        if (c && c.deptRowsMap.has(gid) && c.groundTruth.has(gid)) { ry = y; break; }
      }
      // The August backtest's rule (final-model.mjs): percentile of last year's cutoff under last year's rules,
      // mixed with the percentile of v3 at 0.4, mapped back through this year's distribution.
      const m26 = modeOf(newItems);
      const toScore26 = pr => (pr === null || !isNum(pr) ? null : threshold.weightedScoreAtPrPublic(newItems, 2026, pr, m26));
      const priorRow = y25.deptRowsMap.get(gid);
      const priorPr = priorRow && y25.groundTruth.has(gid) && !y25.skillDept.has(gid)
        ? lib.prOfScore(lib.weightItemsOf(priorRow).items, 2025, y25.groundTruth.get(gid)) : null;
      const v3 = sim.v3.get(gid);
      const simPr = isNum(v3) ? lib.prOfScore(newItems, 2026, v3) : null;
      out.backtestPrior = toScore26(priorPr);
      const mixPr = (a, b) => (isNum(a) && isNum(b) ? LAMBDA * a + (1 - LAMBDA) * b : isNum(a) ? a : isNum(b) ? b : null);
      out.augustRule = toScore26(mixPr(simPr, priorPr));
      out.v3Released = releasedV3.has(gid);
      if (ry === null) { bump('noHistory'); }
      else {
        const oldRow = years.get(ry).deptRowsMap.get(gid);
        const oldW = lib.weightItemsOf(oldRow);
        if (oldW.hasSkill) { bump('historySkill'); }
        else {
          const oldCutoff = years.get(ry).groundTruth.get(gid);
          const rebuilt = threshold.rebuildWeightedThreshold(oldW.items, newItems, ry, oldCutoff);
          const baseCutoff = rebuilt.cutoff;
          const basePr = threshold.weightedPrAtScore(newItems, ry, baseCutoff, rebuilt.distributionMode);
          let finalCutoff = baseCutoff, quotaReason = null;
          if (ry === 2025 && rebuilt.distributionMode !== 'unavailable') {
            const res = quotaAdjustment.adjustCutoffDeltaTByQuota({ baseCutoff, basePr, quotaCurrent: Number(row['總名額']),
              quotaReference: Number(oldRow['總名額']), sumOfMultipliers: sum(newItems.map(i => i.weight)) });
            finalCutoff = res.finalCutoff; quotaReason = res.reason;
          } else quotaReason = ry !== 2025 ? 'non-consecutive-year' : 'distribution-unavailable';
          // The engine compares a user's grades, equated to the result year, with these cutoffs; the 2026 equivalent is
          // the 2026 total at the same percentile of the department's distribution.
          const mode = rebuilt.distributionMode !== 'unavailable' ? rebuilt.distributionMode : m26;
          const toNow = c => {
            let p = threshold.weightedPrAtScore(newItems, ry, c, mode);
            let used = mode;
            if (!isNum(p) && mode !== 'comonotonic') { p = threshold.weightedPrAtScore(newItems, ry, c, 'comonotonic'); used = 'comonotonic'; }
            if (!isNum(p)) return { value: null, used };
            let v = threshold.weightedScoreAtPrPublic(newItems, 2026, p, used);
            if (!isNum(v) && used !== 'comonotonic') { v = threshold.weightedScoreAtPrPublic(newItems, 2026, p, 'comonotonic'); used = 'comonotonic'; }
            return { value: isNum(v) ? v : null, used };
          };
          const b = toNow(baseCutoff), f = toNow(finalCutoff);
          Object.assign(out, { resultYear: ry, method: rebuilt.method, distributionMode: rebuilt.distributionMode, mappingMode: f.used,
            quotaReason, engineBase: b.value, engineFinal: f.value });
          const enginePr = isNum(f.value) ? lib.prOfScore(newItems, 2026, f.value) : null;
          out.augustRuleEngine = toScore26(mixPr(simPr, enginePr));
          bump(`resultYear${ry}`); bump(`method-${rebuilt.method}`); bump(`quota-${quotaReason}`);
        }
      }
    }
    const fmt = v => (isNum(v) ? v.toFixed(2) : '');
    const head = 'gid,result_year,method,quota_reason,engine_base,engine_final,backtest_prior,august_rule,august_rule_engine';
    const lines = [head, ...rows.map(r => [r.gid, r.resultYear ?? '', r.method ?? '', r.quotaReason ?? '', fmt(r.engineBase), fmt(r.engineFinal),
      fmt(r.backtestPrior), r.v3Released ? fmt(r.augustRule) : '', r.v3Released ? fmt(r.augustRuleEngine) : ''].join(','))];
    fs.writeFileSync(path.join(OUT_DIR, 'engine-2026.csv'), lines.join('\n') + '\n');
    writeDepartments('engine', { engineBase: new Map(rows.map(r => [r.gid, r.engineBase])), engineFinal: new Map(rows.map(r => [r.gid, r.engineFinal])),
      backtestPrior: new Map(rows.map(r => [r.gid, r.backtestPrior])), augustRule: new Map(rows.map(r => [r.gid, r.augustRule])),
      augustRuleEngine: new Map(rows.map(r => [r.gid, r.augustRuleEngine])) });
    const quick = key => {
      const set = J2.filter(r => isNum(rows.find(x => x.gid === r.gid)?.[key]));
      const by = new Map(rows.map(x => [x.gid, x]));
      return { n: set.length, mae: mean(set.map(r => Math.abs(by.get(r.gid)[key] - r.actual) / r.weightTotal)),
        bias: mean(set.map(r => (by.get(r.gid)[key] - r.actual) / r.weightTotal)),
        baselineMAESameSet: mean(set.map(r => Math.abs(r.baseline - r.actual) / r.weightTotal)) };
    };
    save('engine', { note: 'exploratory (plan v0.25 A); engine cutoffs rebuilt with the platform functions and the frozen database; '
      + 'the August rule uses the released v3; OUT_DIR/engine-2026.csv holds the releasable columns', tally,
      quickJ2: Object.fromEntries(['engineBase', 'engineFinal', 'backtestPrior', 'augustRule', 'augustRuleEngine'].map(k => [k, quick(k)])) });
  }

  if (SECTION === 'synthetic') {
    const { candidates } = evaluatedCandidates();
    const w = rake(candidates);
    const real = simulate(candidates, w.weightMap);
    const withBaseline = [...BASELINE.keys()].filter(gid => year.deptRowsMap.has(gid));
    const all = lib.buildContext(candidates.map(c => ({ ...c, wishes: withBaseline })), year, w.weightMap);
    const ownLength = uid => (real.ctx.eligibleByUid.get(uid) || []).length;
    const make = lengthOf => candidates.map(c => {
      const options = (all.eligibleByUid.get(c.uid) || []).map(x => ({ gid: x.gid, distance: Math.abs((x.score - BASELINE.get(x.gid)) / WEIGHT_TOTAL.get(x.gid)),
        level: levelOf(x.gid) }));
      options.sort((a, b) => a.distance - b.distance || a.gid - b.gid);
      const pick = options.slice(0, lengthOf(c));
      pick.sort((a, b) => b.level - a.level || a.gid - b.gid);
      return { ...c, wishes: pick.map(x => x.gid) };
    });
    const variants = { real: { cands: candidates, sim: real } };
    for (const [label, lengthOf] of [['ownLength', c => ownLength(c.uid)], ['fiftyFive', () => 55]]) {
      const cands = make(lengthOf);
      variants[label] = { cands, sim: simulate(cands, w.weightMap) };
    }
    const summary = {};
    for (const [label, { cands, sim }] of Object.entries(variants)) {
      writeDepartments(`synthetic-${label}`, { prediction: sim.v3 });
      const lengths = cands.map(c => (sim.ctx.eligibleByUid.get(c.uid) || []).length);
      summary[label] = { meanEligibleListed: mean(lengths), unassignedShare: sim.unassignedShare,
        coveredDepartments: GIDS.filter(g => isNum(sim.v3.get(g))).length, j2: j2Metrics(sim.v3) };
      console.log(JSON.stringify({ label, ...summary[label].j2 }));
    }
    // Overlap between real and generated lists (share of a record's eligible listings that the generated list keeps).
    const overlap = candidates.map(c => {
      const realSet = new Set((real.ctx.eligibleByUid.get(c.uid) || []).map(x => x.gid));
      const gen = variants.ownLength.cands.find(x => x.uid === c.uid)?.wishes || [];
      return realSet.size ? gen.filter(g => realSet.has(g)).length / realSet.size : null;
    }).filter(isNum);
    save('synthetic', { note: 'exploratory (plan v0.25 B); same records, grades and production weights; generated lists take '
      + 'the eligible departments with a baseline nearest to the record\'s score relative to the baseline, ordered by level',
      variants: summary, meanOverlapWithRealList: mean(overlap) });
  }

  if (SECTION === 'placements') {
    const engineFile = path.join(PRIVATE_DIR, 'dept-engine.csv');
    assert.ok(fs.existsSync(engineFile), 'run SECTION=engine first');
    const ENGINE = new Map(readCsv(engineFile).filter(r => r.engineFinal !== '').map(r => [Number(r.gid), Number(r.engineFinal)]));
    const report = {};
    for (const [label, runId] of [['preDeadline', PRE_DEADLINE], ['evaluated', EVALUATED]]) {
      const { candidates } = prepare(runs.get(runId).records);
      const w = rake(candidates);
      const ctx = lib.buildContext(candidates, year, w.weightMap);
      const v3 = cutoffs(rules.runFractionalDA(ctx), 'fw');
      const v2 = cutoffs(rules.runBinaryDA(ctx, 'round'), 'marginal');
      const fallback = (v, gid) => (isNum(v) ? v : BASELINE.get(gid));
      const methods = {
        baseline: gid => BASELINE.get(gid),
        engine: gid => ENGINE.get(gid),
        v2: gid => fallback(v2.get(gid), gid),
        v3: gid => fallback(v3.get(gid), gid),
        combination: gid => { const v = v3.get(gid), b = BASELINE.get(gid); return isNum(v) && isNum(b) ? LAMBDA * v + (1 - LAMBDA) * b : isNum(v) ? v : b; },
        official: gid => OFFICIAL.get(gid),
      };
      const place = (c, cut) => {
        for (const wish of ctx.eligibleByUid.get(c.uid) || []) {
          const k = cut(wish.gid);
          if (isNum(k) && wish.score >= k - 1e-9) return wish.wishIndex;
        }
        return null;
      };
      const sorted = candidates.map(c => [meanGrade(c), w.weightMap.get(c.uid)]).sort((a, b) => a[0] - b[0]);
      const total = sum(sorted.map(x => x[1]));
      const cuts = [];
      let acc = 0, k = 1;
      for (const [g, wt] of sorted) { acc += wt; while (k < 5 && acc >= (k * total) / 5) { cuts.push(g); k++; } }
      const fifth = g => cuts.filter(c => g > c).length + 1;
      const blank = () => ({ records: 0, weight: 0, same: 0, earlier: 0, later: 0, predictedOnly: 0, officialOnly: 0, neither: 0,
        wSame: 0, wEarlier: 0, wLater: 0, wPredictedOnly: 0, wOfficialOnly: 0, wNeither: 0 });
      const kind = (p, o) => (p === null && o === null ? 'neither' : p === null ? 'officialOnly' : o === null ? 'predictedOnly'
        : p === o ? 'same' : p < o ? 'earlier' : 'later');
      const W = { same: 'wSame', earlier: 'wEarlier', later: 'wLater', predictedOnly: 'wPredictedOnly', officialOnly: 'wOfficialOnly', neither: 'wNeither' };
      const tables = {};
      for (const m of ['baseline', 'engine', 'v2', 'v3', 'combination']) tables[m] = { all: blank(), 1: blank(), 2: blank(), 3: blank(), 4: blank(), 5: blank() };
      const change = { all: blank(), 1: blank(), 5: blank() };
      for (const c of candidates) {
        const o = place(c, methods.official);
        const q = String(fifth(meanGrade(c)));
        const wt = w.weightMap.get(c.uid);
        const placed = {};
        for (const m of Object.keys(tables)) {
          placed[m] = place(c, methods[m]);
          const kd = kind(placed[m], o);
          for (const key of ['all', q]) { const t = tables[m][key]; t.records++; t.weight += wt; t[kd]++; t[W[kd]] += wt; }
        }
        // From the baseline to the combination: 'earlier' means the combination places the record at an earlier preference.
        const kd = kind(placed.combination, placed.baseline);
        for (const key of ['all', q]) { if (!change[key]) continue; const t = change[key]; t.records++; t.weight += wt; t[kd]++; t[W[kd]] += wt; }
      }
      report[label] = { runId, records: candidates.length, fifthCuts: cuts, byMethod: tables, combinationAgainstBaseline: change };
    }
    save('placements6', { note: 'exploratory (plan v0.25 C); placement = first eligible listed department whose cutoff the weighted '
      + 'score reaches (ties admitted); earlier = the method places the record at an earlier, more favorable preference than the '
      + 'official cutoffs; departments without a value under a method are skipped (v2 and v3 fall back to the baseline)', report });
  }

  if (SECTION === 'quota2025') {
    const y25 = lib.loadYear(2025);
    const { candidates } = evaluatedCandidates();
    const w = rake(candidates);
    const quota25 = gid => (y25.deptRowsMap.has(gid) && y25.quotaOf(gid) > 0 ? y25.quotaOf(gid) : year.quotaOf(gid));
    const real = simulate(candidates, w.weightMap);
    const alt = simulate(candidates, w.weightMap, quota25);
    writeDepartments('quota2025', { prediction: alt.v3, real: real.v3 });
    const changed = GIDS.filter(g => y25.deptRowsMap.has(g) && y25.quotaOf(g) > 0 && y25.quotaOf(g) !== year.quotaOf(g)).length;
    save('quota2025', { note: 'exploratory (plan v0.25 D); same records and weights, 2025 quotas where the department had one',
      departmentsWithChangedQuota: changed, real: j2Metrics(real.v3), quota2025: j2Metrics(alt.v3) });
  }

  if (SECTION === 'earliest') {
    const first = new Map();
    for (const runId of runOrder) for (const r of runs.get(runId).records) if (!r.dup && !first.has(r.id)) first.set(r.id, { runId, wishes: r.wishes });
    const ev = runs.get(EVALUATED).records;
    const firstRun = {};
    let changed = 0, linked = 0;
    const added = [], removed = [];
    const modified = ev.map(r => {
      if (r.dup) return r;
      const f = first.get(r.id);
      if (!f) return r;
      linked++;
      firstRun[f.runId] = (firstRun[f.runId] || 0) + 1;
      if (JSON.stringify(f.wishes) !== JSON.stringify(r.wishes)) {
        changed++;
        const a = new Set(f.wishes), b = new Set(r.wishes);
        for (const g of b) if (!a.has(g)) added.push(g);
        for (const g of a) if (!b.has(g)) removed.push(g);
      }
      return { ...r, wishes: f.wishes };
    });
    const describe = list => {
      const known = list.filter(g => byGid.has(g));
      const low = known.filter(g => isNum(levelOf(g)) && levelOf(g) < 30).length;
      const priv = known.filter(g => !isPublicSchool(byGid.get(g).school)).length;
      return { listings: list.length, known: known.length, levelBelow30Share: known.length ? low / known.length : null,
        privateShare: known.length ? priv / known.length : null };
    };
    const { candidates, counts } = prepare(modified);
    const w = rake(candidates);
    const sim = simulate(candidates, w.weightMap);
    writeDepartments('earliest', { prediction: sim.v3 });
    save('earliest', { note: 'exploratory (plan v0.25 E); each account\'s preference list from the earliest saved run in which it '
      + 'appears, with its evaluated grades; production calibration', counts, linkedAccounts: linked, accountsWhoseListChanged: changed,
      firstRunOfAccounts: firstRun, added: describe(added), removed: describe(removed), j2: j2Metrics(sim.v3) });
  }

  if (SECTION === 'tilt') {
    const { candidates } = evaluatedCandidates();
    const N = candidates.length;
    const isPublic = gid => /^(國立|.*市立)/.test(String(year.deptRowsMap.get(gid)?.['學校名稱'] || ''));
    const share = pred => candidates.map(c => { const l = c.wishes.filter(g => year.deptRowsMap.has(g)); return l.length ? l.filter(pred).length / l.length : 0; });
    const median = v => { const s = [...v].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
    const privateShare = share(g => !isPublic(g));
    const lowShare = share(g => isNum(levelOf(g)) && levelOf(g) < 30);
    const groups = {
      'private-leaning': (() => { const m = median(privateShare); return privateShare.map(x => x > m); })(),
      'long-lists': (() => { const m = median(candidates.map(c => c.wishes.length)); return candidates.map(c => c.wishes.length > m); })(),
      'low-level-leaning': (() => { const m = median(lowShare); return lowShare.map(x => x > m); })(),
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
    const base = rake(candidates);
    const results = [];
    for (const [name, member] of Object.entries(groups)) {
      const baseShare = sum(candidates.map((c, i) => (member[i] ? base.weightMap.get(c.uid) : 0))) / base.sumW;
      for (const gamma of [0.25, 0.5, 2, 4]) {
        const init = member.map(m => (m ? gamma : 1));
        const scale = START_TOTAL / sum(init);
        const { w, converged } = rakeFrom(init.map(x => x * scale));
        const weighted = sum(w.filter((_, i) => member[i])) / sum(w);
        const sim = simulate(candidates, new Map(candidates.map((c, i) => [c.uid, w[i]])));
        writeDepartments(`tilt6-${name}-${gamma}`, { prediction: sim.v3 });
        results.push({ group: name, gamma, records: member.filter(Boolean).length, converged, weightedShare: weighted, productionShare: baseShare, j2: j2Metrics(sim.v3) });
        console.log(JSON.stringify(results[results.length - 1]));
      }
    }
    save('tilt6', { note: 'exploratory (plan v0.25 F); Γ multiplies the starting weight of the group before raking to the production margins', results });
  }

  if (SECTION === 'small') {
    // G1: subjects and mean grade of records last updated before the deadline, against the others.
    const { candidates } = evaluatedCandidates();
    const w = rake(candidates);
    const ctx = lib.buildContext(candidates, year, w.weightMap);
    const both = (group, f) => {
      const v = group.map(c => [w.weightMap.get(c.uid) || 0, f(c)]).filter(x => isNum(x[1]));
      const W = sum(v.map(x => x[0]));
      return { unweighted: mean(v.map(x => x[1])), weighted: W ? sum(v.map(x => x[0] * x[1])) / W : null };
    };
    const before = candidates.filter(c => isNum(c.updatedAt) && c.updatedAt < DEADLINE);
    const after = candidates.filter(c => !(isNum(c.updatedAt) && c.updatedAt < DEADLINE));
    const returners = {};
    for (const [label, g] of [['before', before], ['afterOrUnknown', after]]) {
      returners[label] = { records: g.length, subjects: both(g, subjectsTaken), meanNormalizedGrade: both(g, meanGrade) };
    }
    // G2: content hashes of every saved run (grades with sorted keys, preferences and the mirror flag; no identifier or time).
    const canon = r => JSON.stringify([Object.keys(r.scores || {}).sort().map(k => [k, r.scores[k]]), r.wishes, Boolean(r.dup)]);
    const hashes = runOrder.map(runId => {
      const lines = runs.get(runId).records.map(canon).sort();
      return { runId, records: lines.length, contentSHA256: crypto.createHash('sha256').update(lines.join('\n')).digest('hex') };
    });
    // G3: Kish effective sample size of the eligible listers' weights per department.
    const sw = new Map(), sw2 = new Map(), n = new Map();
    for (const c of candidates) {
      const wt = w.weightMap.get(c.uid) || 0;
      for (const wish of ctx.eligibleByUid.get(c.uid) || []) {
        sw.set(wish.gid, (sw.get(wish.gid) || 0) + wt); sw2.set(wish.gid, (sw2.get(wish.gid) || 0) + wt * wt); n.set(wish.gid, (n.get(wish.gid) || 0) + 1);
      }
    }
    const neff = new Map([...sw].map(([g, s]) => [g, s * s / sw2.get(g)]));
    writeDepartments('neff', { neff, eligible: n });
    const onJ2 = J2.map(r => neff.get(r.gid)).filter(isNum);
    save('small', { note: 'exploratory (plan v0.25 G1-G3); grades are counted over subjects with a non-negative normalized grade',
      returners, runContentHashes: hashes,
      neffOnJ2: { departments: onJ2.length, median: quantile(onJ2, 0.5), p10: quantile(onJ2, 0.1), p25: quantile(onJ2, 0.25),
        p75: quantile(onJ2, 0.75), p90: quantile(onJ2, 0.9), below5: onJ2.filter(x => x < 5).length, below10: onJ2.filter(x => x < 10).length } });
  }

  if (SECTION === 'halves') {
    const { candidates } = evaluatedCandidates();
    const N = candidates.length, half = Math.floor(N / 2);
    const from = Number(process.env.HALF_FROM || 0), count = Number(process.env.HALF_COUNT || 40);
    for (let k = from; k < Math.min(40, from + count); k++) {
      // Same seeds as the half-samples of author_checks.mjs, so these are the first 40 of those replicates.
      const rand = lib.mulberry32(20261201 + k);
      const sample = candidates.map(c => [rand(), c]).sort((a, b) => a[0] - b[0]).slice(0, half).map(x => x[1]);
      const w = rake(sample);
      const sim = simulate(sample, w.weightMap);
      writeDepartments(`half6-${k}`, { prediction: sim.v3 });
      console.log(JSON.stringify({ k, converged: w.converged, ...j2Metrics(sim.v3) }));
    }
  }
} finally {
  closeRuntime();
}
