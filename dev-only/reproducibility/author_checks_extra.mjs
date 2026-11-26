/**
 * Additional record-level author checks of the fifth revision (exploratory; Supplement S20, S25, S27, S28).
 *
 * Same inputs, runtime and outputs as author_checks.mjs, whose short helpers it repeats so that author_checks.mjs, and
 * the hashes recorded with its outputs, stay unchanged. Runs only on the author's computer; aggregates go to OUT_DIR
 * (author-checks-<section>.json) and department-level simulated cutoffs to PRIVATE_DIR.
 *
 * Sections:
 *   placements  each record's simulated placement (the earliest preference at which the simulation retains any of its
 *               mass, the platform's display rule) under divisible mass and under the whole-person v2 rule, against the
 *               placement reconstructed from the official cutoffs, by quintile of the record's mean grade (quintiles of
 *               the calibrated weights), for the evaluated run and the last run before the deadline;
 *   changes     whether the grades, the preferences or both differ between a record's version in the last run before the
 *               deadline and its evaluated version, by update time;
 *   dedupe      v3 rerun keeping one record (the most recently updated) per identical vector of grades;
 *   jointpairs  for the departments with equal multipliers whose combination table is official, the error of the v3
 *               cutoff in examinee counts split into the calibrated records' composition and the remaining capture rate.
 *
 * Usage: SECTION=<section> EXPORT_FILE=... PRIVATE_DIR=... OUT_DIR=... node author_checks_extra.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { paper, lib, rules, scoring, cleaning, closeRuntime, provenance, manifest } from './author_runtime.mjs';

const EXPORT_FILE = process.env.EXPORT_FILE;
const PRIVATE_DIR = process.env.PRIVATE_DIR;
const OUT_DIR = process.env.OUT_DIR || path.join(paper, 'out');
const SNAPSHOT = process.env.BENCHMARK_SNAPSHOT || path.join(paper, 'sources/benchmark-snapshot.md');
const SECTION = process.env.SECTION || 'changes';
const DEADLINE = Date.parse('2026-08-08T08:30:00Z'); // 16:30 Taiwan time
const EVALUATED = 'ast_20260815T150000Z';
const PRE_DEADLINE = 'ast_20260808T035958Z';
const LAMBDA = 0.4;
const SEED = 20261127;

fs.mkdirSync(OUT_DIR, { recursive: true });
fs.mkdirSync(PRIVATE_DIR, { recursive: true, mode: 0o700 });
const fileSHA256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const here = path.dirname(fileURLToPath(import.meta.url));
const INPUTS = { exportSHA256: fileSHA256(EXPORT_FILE), benchmarkSnapshotSHA256: fileSHA256(SNAPSHOT),
  releasedDepartmentCsvSHA256: fileSHA256(path.join(paper, 'data/department-benchmark.csv')),
  authorChecksExtraSHA256: fileSHA256(fileURLToPath(import.meta.url)),
  authorRuntimeSHA256: fileSHA256(path.join(here, 'author_runtime.mjs')) };
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
const year = lib.loadYear(2026);
const benchmark = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8').split('```json\n')[1].split('\n```')[0]);
const GIDS = benchmark.rows.map(row => row.gid);
const released = readCsv(path.join(paper, 'data/department-benchmark.csv'));
const OFFICIAL = new Map(released.map(r => [Number(r.gid), Number(r.actual)]));
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
const rake = cands => lib.solveWeights(cands, 2026, lib.PRODUCTION_BANDS, c => c.normalizedScores, 39213);
const cutoffs = (out, mode) => new Map(GIDS.map(gid => [gid, lib.cutoffOf(out, gid, mode)]));
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
const scoreKey = scores => JSON.stringify(Object.keys(scores || {}).sort().map(k => [k, scores[k]]));
const wishKey = wishes => JSON.stringify(wishes);
/** Seeded generator (mulberry32). */
function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

try {
  if (SECTION === 'placements') {
    const report = {};
    for (const [label, runId] of [['evaluated', EVALUATED], ['preDeadline', PRE_DEADLINE]]) {
      const { candidates } = prepare(runs.get(runId).records);
      const w = rake(candidates);
      const ctx = lib.buildContext(candidates, year, w.weightMap);
      const outs = { divisible: rules.runFractionalDA(ctx), wholePerson: rules.runBinaryDA(ctx, 'round') };
      // Quintiles of the record's mean grade over the subjects it took, cut at quintiles of the calibrated weights.
      const meanGrade = c => mean(Object.values(c.normalizedScores).filter(v => isNum(v) && v >= 0));
      const sorted = candidates.map(c => [meanGrade(c), w.weightMap.get(c.uid)]).sort((a, b) => a[0] - b[0]);
      const total = sum(sorted.map(x => x[1]));
      const cuts = [];
      let acc = 0, k = 1;
      for (const [g, wt] of sorted) { acc += wt; while (k < 5 && acc >= (k * total) / 5) { cuts.push(g); k++; } }
      const quintile = g => cuts.filter(c => g > c).length + 1;
      // Reconstruction from the official cutoffs: the first eligible preference whose official cutoff the weighted score
      // reaches (ties admitted); departments without an official cutoff do not admit.
      const reconstruct = c => {
        const el = ctx.eligibleByUid.get(c.uid) || [];
        let tie = false;
        for (const wish of el) {
          const cut = OFFICIAL.get(wish.gid);
          if (!isNum(cut)) continue;
          if (wish.score >= cut) { if (Math.abs(wish.score - cut) < 1e-9) tie = true; return { index: wish.wishIndex, tie }; }
        }
        return { index: null, tie };
      };
      report[label] = { runId, records: candidates.length, quintileCuts: cuts };
      for (const [rule, out] of Object.entries(outs)) {
        const blank = () => ({ records: 0, weight: 0, same: 0, simulationEarlier: 0, simulationLater: 0, simulationOnly: 0,
          reconstructionOnly: 0, neither: 0, tieAtOfficialCutoff: 0 });
        const byQ = { all: blank(), 1: blank(), 2: blank(), 3: blank(), 4: blank(), 5: blank() };
        for (const c of candidates) {
          const s = out.states.get(c.uid)?.assigned;
          const sim = s ? s.wishIndex : null;
          const rec = reconstruct(c);
          const kind = sim === null && rec.index === null ? 'neither' : sim === null ? 'reconstructionOnly' : rec.index === null
            ? 'simulationOnly' : sim === rec.index ? 'same' : sim < rec.index ? 'simulationEarlier' : 'simulationLater';
          for (const key of ['all', String(quintile(meanGrade(c)))]) {
            byQ[key].records++; byQ[key].weight += w.weightMap.get(c.uid); byQ[key][kind]++;
            if (rec.tie) byQ[key].tieAtOfficialCutoff++;
          }
        }
        report[label][rule] = byQ;
      }
    }
    save('placements', { note: 'counts of records; simulationEarlier means the simulation places the record at an earlier (more '
      + 'preferred) listed department than the official cutoffs would, i.e. it is more optimistic; simulationOnly means the '
      + 'simulation places a record that the official cutoffs would leave unplaced', report });
  }

  if (SECTION === 'changes') {
    const own = run => new Map(run.records.filter(r => !r.dup).map(r => [r.id, r]));
    const pre = own(runs.get(PRE_DEADLINE)), ev = own(runs.get(EVALUATED));
    const blank = () => ({ identical: 0, gradesOnly: 0, preferencesOnly: 0, both: 0, preferenceSetUnchanged: 0, listLengthChange: [] });
    const out = { beforeDeadline: blank(), afterDeadline: blank(), missing: blank() };
    for (const [id, r] of ev) {
      const p = pre.get(id);
      if (!p) continue;
      const group = r.updatedAt === null ? 'missing' : r.updatedAt <= DEADLINE ? 'beforeDeadline' : 'afterDeadline';
      const g = scoreKey(p.scores) !== scoreKey(r.scores), wv = wishKey(p.wishes) !== wishKey(r.wishes);
      const o = out[group];
      if (!g && !wv) { o.identical++; continue; }
      if (g && wv) o.both++; else if (g) o.gradesOnly++; else o.preferencesOnly++;
      if (wv) {
        if (JSON.stringify([...p.wishes].sort((a, b) => a - b)) === JSON.stringify([...r.wishes].sort((a, b) => a - b))) o.preferenceSetUnchanged++;
        o.listLengthChange.push(r.wishes.length - p.wishes.length);
      }
    }
    for (const o of Object.values(out)) {
      const d = o.listLengthChange;
      o.listLengthChange = { changed: d.length, mean: mean(d), lengthened: d.filter(x => x > 0).length, shortened: d.filter(x => x < 0).length };
    }
    save('changes', { note: 'records present in both the last pre-deadline run and the evaluated run (mirror copies excluded), '
      + 'by the update time of the evaluated version', byUpdate: out });
  }

  if (SECTION === 'dedupe') {
    const { candidates, counts } = prepare(runs.get(EVALUATED).records);
    const groups = new Map();
    for (const c of candidates) {
      const key = scoreKey(c.normalizedScores);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(c);
    }
    const kept = [];
    for (const list of groups.values()) {
      list.sort((a, b) => (b.updatedAt ?? -Infinity) - (a.updatedAt ?? -Infinity));
      kept.push(list[0]);
    }
    const w = rake(kept);
    const ctx = lib.buildContext(kept, year, w.weightMap);
    const out = rules.runFractionalDA(ctx);
    const v3 = cutoffs(out, 'fw');
    writeDepartments('variant-dedupe-grades', { prediction: v3, fractional: cutoffs(out, 'marginal'), listings: listings(kept) });
    const sizes = [...groups.values()].map(l => l.length);
    save('dedupe', { counts, gradeVectors: groups.size, groupsWithSeveralRecords: sizes.filter(s => s > 1).length,
      recordsInSuchGroups: sum(sizes.filter(s => s > 1)), recordsRemoved: candidates.length - kept.length, kept: kept.length,
      raking: { converged: w.converged, iterations: w.iterations, nEff: w.nEff, sumW: w.sumW }, j2: j2Metrics(v3) });
  }

  if (SECTION === 'jointpairs') {
    const { candidates } = prepare(runs.get(EVALUATED).records);
    const main = rake(candidates);
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
    const countAbove = (rows, total) => interpolate(rows.map(r => r.level), rows.map(r => r.cum_above - r.people / 2), total);
    const cache = new Map();
    function platformTable(subjects) {
      const key = subjects.join('+');
      if (cache.has(key)) return cache.get(key);
      const maxLevel = 60 * subjects.length;
      const people = new Array(maxLevel + 1).fill(0);
      for (const c of candidates) {
        let total = 0, ok = true;
        for (const s of subjects) { const v = c.normalizedScores[s]; if (!isNum(v) || v < 0) { ok = false; break; } total += v; }
        if (ok) people[total] += main.weightMap.get(c.uid);
      }
      const rows = [];
      let above = sum(people);
      for (let level = 0; level <= maxLevel; level++) { rows.push({ level, people: people[level], cum_above: above }); above -= people[level]; }
      cache.set(key, rows);
      return rows;
    }
    const byGid = new Map(J2.map(r => [r.gid, r]));
    const levelBand = g => (g < 30 ? '0-30' : g < 40 ? '30-40' : g < 45 ? '40-45' : g < 50 ? '45-50' : '50-60');
    const j2ByLevel = {};
    for (const r of J2) { const b = levelBand(r.baseline / r.weightTotal); j2ByLevel[b] = (j2ByLevel[b] || 0) + 1; }
    const deps = [];
    for (const d of departments) {
      const r = byGid.get(d.gid);
      if (!r || !d.items?.length || new Set(d.items.map(i => i.weight)).size !== 1) continue;
      const official = tables[`2026:${comboKey(d.items)}`];
      if (!official) continue;
      const m = d.items[0].weight, K = d.items.length;
      const subjects = d.items.map(i => field(i.subject));
      const p = platformTable(subjects);
      const tStar = r.actual / m, tHat = r.releasedV3 / m;
      const N = t => countAbove(official, t), Nh = t => countAbove(p, t);
      if (!(N(tStar) > 0 && N(tHat) > 0 && Nh(tStar) > 0 && Nh(tHat) > 0)) continue;
      // Total change (in grades) that moves the official count at the official cutoff by 5%.
      let step = 0;
      while (step < 60 * K && N(tStar + step + 0.1) > 0.95 * N(tStar)) step += 0.1;
      deps.push({ school: r.school, level: levelBand(r.baseline / r.weightTotal), e: (r.releasedV3 - r.actual) / r.weightTotal,
        compStar: Math.log(Nh(tStar) / N(tStar)), compHat: Math.log(Nh(tHat) / N(tHat)), total: Math.log(N(tHat) / N(tStar)),
        capture: Math.log(Nh(tHat) / N(tStar)), gradesFor5Percent: step / K });
    }
    const varOf = x => { const mx = mean(x); return mean(x.map(v => (v - mx) ** 2)); };
    const cov = (x, y) => { const mx = mean(x), my = mean(y); return mean(x.map((v, i) => (v - mx) * (y[i] - my))); };
    const rank = v => { const idx = v.map((x, i) => [x, i]).sort((a, b) => a[0] - b[0]); const r = new Array(v.length); let k = 0;
      while (k < idx.length) { let j = k; while (j + 1 < idx.length && idx[j + 1][0] === idx[k][0]) j++; for (let t = k; t <= j; t++) r[idx[t][1]] = (k + j) / 2; k = j + 1; } return r; };
    const pearson = (x, y) => cov(x, y) / Math.sqrt(varOf(x) * varOf(y));
    const spearman = (x, y) => pearson(rank(x), rank(y));
    const T = deps.map(d => d.total), C = deps.map(d => d.compHat), A = deps.map(d => d.capture);
    // Institution-cluster interval for the Spearman correlation of composition at the official cutoff with the v3 error.
    const schools = [...new Set(deps.map(d => d.school))];
    const bySchool = new Map(schools.map(s => [s, deps.filter(d => d.school === s)]));
    const rand = rng(SEED);
    const draws = [];
    for (let b = 0; b < 2000; b++) {
      const pick = schools.map(() => bySchool.get(schools[Math.floor(rand() * schools.length)])).flat();
      draws.push(spearman(pick.map(d => d.compStar), pick.map(d => d.e)));
    }
    const levels = {};
    for (const band of ['0-30', '30-40', '40-45', '45-50', '50-60']) {
      const u = deps.filter(d => d.level === band);
      levels[band] = { departments: u.length, shareOfJ2Band: u.length / (j2ByLevel[band] || 1),
        medianGradesFor5Percent: quantile(u.map(d => d.gradesFor5Percent), 0.5),
        meanAbsTotal: u.length ? mean(u.map(d => Math.abs(d.total))) : null,
        meanAbsComposition: u.length ? mean(u.map(d => Math.abs(d.compHat))) : null };
    }
    save('jointpairs', { note: 'total = log of official examinees at or above the v3 cutoff over those at or above the official cutoff; '
      + 'composition = log of calibrated record mass over official examinees at or above the same total; capture = total + composition '
      + 'at the v3 cutoff (log of calibrated mass at the v3 cutoff over official examinees at the official cutoff); released v3 values',
      departments: deps.length, schools: schools.length,
      meanAbs: { total: mean(T.map(Math.abs)), compositionAtOfficialCutoff: mean(deps.map(d => Math.abs(d.compStar))),
        compositionAtV3Cutoff: mean(C.map(Math.abs)), capture: mean(A.map(Math.abs)) },
      variance: { total: varOf(T), compositionAtV3Cutoff: varOf(C), capture: varOf(A), covarianceCaptureComposition: cov(A, C) },
      correlationTotalWithComposition: pearson(T, C), correlationTotalWithCapture: pearson(T, A),
      spearmanCompositionWithError: { value: spearman(deps.map(d => d.compStar), deps.map(d => d.e)),
        interval: [quantile(draws, 0.025), quantile(draws, 0.975)], repetitions: 2000, seed: SEED },
      levels });
  }
} finally {
  closeRuntime();
}
