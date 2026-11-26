/**
 * Record-level author checks added after the fifth round of simulated reviews (exploratory; specification:
 * dev-only/review/analysis-plan-v024.md; Supplement S11, S17, S25 and S3).
 *
 * Same inputs, runtime and outputs as author_checks.mjs, whose short helpers it repeats so that the earlier scripts, and
 * the hashes recorded with their outputs, stay unchanged. Runs only on the author's computer; aggregates go to OUT_DIR
 * (author-checks-<section>.json); no department-level value is written.
 *
 * Sections:
 *   dean           on the evaluated input, the whole-person rule of Dean, Goemans and Immorlica (2006b, Theorem 2), which
 *                  rejects a department's lowest-priority record only while the remaining load still reaches the quota,
 *                  and the deployed v2 rule: coverage, error on the released J5 and J2 sets, load against the quota,
 *                  listings rejected above the simulated minimum, and 20 permutations of the initial queue;
 *   aug7           the v2 rule recomputed on the run saved at 20:00 on 7 August (listings rejected above the minimum);
 *   concentration  the largest share of a department's retained mass held by one record (Fractional, evaluated run);
 *   eligibility    eligible listers and distinct records holding mass per department, summarized for released values;
 *   returners      records last updated before the registration deadline against the others (descriptive).
 *
 * Usage: SECTION=<section> EXPORT_FILE=... PRIVATE_DIR=... OUT_DIR=... node author_checks_round5.mjs
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
const SECTION = process.env.SECTION || 'dean';
const DEADLINE = Date.parse('2026-08-08T08:30:00Z'); // 16:30 Taiwan time
const EVALUATED = 'ast_20260815T150000Z';
const PRE_DEADLINE = 'ast_20260808T035958Z';
const LAMBDA = 0.4;
const SEED = 20261126;

fs.mkdirSync(OUT_DIR, { recursive: true });
fs.mkdirSync(PRIVATE_DIR, { recursive: true, mode: 0o700 });
const fileSHA256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const here = path.dirname(fileURLToPath(import.meta.url));
const INPUTS = { exportSHA256: fileSHA256(EXPORT_FILE), benchmarkSnapshotSHA256: fileSHA256(SNAPSHOT),
  releasedDepartmentCsvSHA256: fileSHA256(path.join(paper, 'data/department-benchmark.csv')),
  authorChecksRound5SHA256: fileSHA256(fileURLToPath(import.meta.url)),
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

const J5 = released.filter(r => ['v1', 'v2', 'fractional', 'v3', 'baseline'].every(k => r[k] !== ''))
  .map(r => ({ gid: Number(r.gid), actual: Number(r.actual), weightTotal: Number(r.weightTotal), fractional: Number(r.fractional),
    v2: Number(r.v2), school: r.school }));
assert.equal(J5.length, 1361, 'released J5 set');
const evalOn = (set, pred, key) => {
  const rows = set.filter(r => isNum(pred.get(r.gid)));
  return { covered: rows.length, of: set.length, mae: mean(rows.map(r => Math.abs(pred.get(r.gid) - r.actual) / r.weightTotal)),
    bias: mean(rows.map(r => (pred.get(r.gid) - r.actual) / r.weightTotal)),
    maeReleasedSameSet: key ? mean(rows.map(r => Math.abs(r[key] - r.actual) / r.weightTotal)) : undefined };
};
function shuffled(values, seed) {
  const rand = rng(seed);
  const a = values.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
/** Dean, Goemans and Immorlica (2006b, Theorem 2): tentative acceptance, then rejection of the lowest-priority record
 *  while the load without it would still reach the quota, so a department ends below quota + its last record's weight. */
function deanDA(ctx, order = ctx.candidateUids) {
  const dept = new Map();
  for (const gid of ctx.deptIds) dept.set(gid, { gid, quota: ctx.quotaOf(gid), held: [], load: 0, rejected: [] });
  const st = new Map();
  const queue = [];
  for (const uid of order) {
    const el = ctx.eligibleByUid.get(uid) || [];
    const s = { uid, el, ptr: 0, assigned: null };
    st.set(uid, s);
    if (el.length) queue.push(s);
  }
  let events = 0;
  for (let head = 0; head < queue.length; head++) {
    const c = queue[head];
    if (c.ptr >= c.el.length) continue;
    const wish = c.el[c.ptr];
    const d = dept.get(wish.gid);
    if (!d || d.quota <= 0) { c.ptr++; queue.push(c); continue; }
    events++;
    const cmp = ctx.compareFor(wish.gid);
    const entry = { uid: c.uid, weightedScore: wish.score, wishIndex: c.ptr, rank: wish.rank };
    let lo = 0, hi = d.held.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cmp(d.held[mid], entry) <= 0) lo = mid + 1; else hi = mid; }
    d.held.splice(lo, 0, entry);
    d.load += ctx.weightOf(c.uid);
    c.assigned = entry;
    while (d.held.length && d.load - ctx.weightOf(d.held[d.held.length - 1].uid) >= d.quota - 1e-9) {
      const out = d.held.pop();
      d.load -= ctx.weightOf(out.uid);
      d.rejected.push(out.weightedScore);
      const rs = st.get(out.uid);
      rs.assigned = null; rs.ptr++; queue.push(rs);
    }
  }
  const out = rules.collect(ctx, dept, st, x => x.held.map(h => ({ uid: h.uid, score: h.weightedScore, mass: ctx.weightOf(h.uid) })));
  // No justified envy: a rejected record never outranks the lowest record the department finally holds.
  let envy = 0;
  for (const [gid, d] of dept) {
    const min = out.results.get(gid)?.minScore;
    if (min === null || min === undefined) continue;
    envy += d.rejected.filter(s => s > min).length;
  }
  return { out, events, envy };
}
function loadStats(out, ctx) {
  const rows = [];
  for (const gid of ctx.deptIds) {
    const q = ctx.quotaOf(gid);
    if (q <= 0) continue;
    rows.push({ gid, q, load: out.results.get(gid)?.assignedWeight ?? 0 });
  }
  const over = rows.filter(r => r.load > r.q + 1e-6);
  const ratio = over.map(r => (r.load - r.q) / r.q);
  return { departmentsWithQuota: rows.length, overloaded: over.length, totalExcess: sum(over.map(r => r.load - r.q)),
    maxExcess: over.length ? Math.max(...over.map(r => r.load - r.q)) : 0,
    excessOverQuota: { median: quantile(ratio, 0.5), p90: quantile(ratio, 0.9), max: ratio.length ? Math.max(...ratio) : 0 },
    overloadedAtLeastDouble: ratio.filter(x => x >= 1).length,
    belowQuotaByAtLeastOne: rows.filter(r => r.load < r.q - 1).length,
    totalUnused: sum(rows.map(r => Math.max(0, r.q - r.load))) };
}
function blockingByDepartment(out) {
  const gids = new Set();
  let listings = 0;
  const people = new Set();
  for (const s of out.states.values()) {
    const assignedRank = s.assigned ? s.assigned.rank : Infinity;
    for (const w of s.el) {
      if (w.rank >= assignedRank) continue;
      const min = out.results.get(w.gid)?.minScore;
      if (min === null || min === undefined) continue;
      if (w.score > min) { listings++; people.add(s.uid); gids.add(w.gid); }
    }
  }
  return { listings, records: people.size, departments: gids.size };
}
function orderCheck(run, base, perms = 20) {
  let changedMax = 0, changedMin = Infinity;
  const maes = [];
  for (let k = 0; k < perms; k++) {
    const pred = run(SEED + k + 1);
    let changed = 0;
    for (const gid of GIDS) {
      const a = base.get(gid), b = pred.get(gid);
      if (isNum(a) !== isNum(b) || (isNum(a) && Math.abs(a - b) > 1e-9)) changed++;
    }
    changedMax = Math.max(changedMax, changed); changedMin = Math.min(changedMin, changed);
    maes.push(evalOn(J5, pred).mae);
  }
  return { permutations: perms, departmentsChangedMin: changedMin, departmentsChangedMax: changedMax,
    maeJ5Min: Math.min(...maes), maeJ5Max: Math.max(...maes) };
}
const count = pred => GIDS.filter(gid => isNum(pred.get(gid))).length;

try {
  if (SECTION === 'dean') {
    const { candidates, counts } = prepare(runs.get(EVALUATED).records);
    assert.equal(candidates.length, 4627, 'evaluated records');
    const w = rake(candidates);
    const ctx = lib.buildContext(candidates, year, w.weightMap);
    const dean = deanDA(ctx);
    const deanCut = cutoffs(dean.out, 'marginal');
    const v2 = rules.runBinaryDA(ctx, 'round');
    const v2Cut = cutoffs(v2, 'marginal');
    const frac = rules.runFractionalDA(ctx);
    const fracCut = cutoffs(frac, 'marginal');
    const weights = candidates.map(c => w.weightMap.get(c.uid));
    const quotas = ctx.deptIds.map(gid => ctx.quotaOf(gid)).filter(q => q > 0);
    save('dean', {
      note: 'exploratory (plan v0.24); same input, weights, eligibility and priorities as the evaluated run; cutoffs are the lowest retained record',
      counts, weightsConverged: w.converged, maxWeight: Math.max(...weights), medianQuota: quantile(quotas, 0.5),
      dean: { covered1706: count(deanCut), J5: evalOn(J5, deanCut, 'fractional'), J2: evalOn(J2, deanCut), load: loadStats(dean.out, ctx),
        events: dean.events, justifiedEnvy: dean.envy, blocking: blockingByDepartment(dean.out),
        order: orderCheck(seed => cutoffs(deanDA(ctx, shuffled(ctx.candidateUids, seed)).out, 'marginal'), deanCut) },
      v2: { covered1706: count(v2Cut), J5: evalOn(J5, v2Cut, 'v2'), load: loadStats(v2, ctx), blocking: blockingByDepartment(v2),
        order: orderCheck(seed => cutoffs(rules.runBinaryDA({ ...ctx, candidateUids: shuffled(ctx.candidateUids, seed) }, 'round'), 'marginal'), v2Cut) },
      fractional: { covered1706: count(fracCut), J5: evalOn(J5, fracCut, 'fractional'), load: loadStats(frac, ctx) },
    });
  }

  if (SECTION === 'aug7') {
    const run = runs.get('ast_20260807T120012Z');
    const { candidates, counts } = prepare(run.records);
    const w = rake(candidates);
    const ctx = lib.buildContext(candidates, year, w.weightMap);
    const v2 = rules.runBinaryDA(ctx, 'round');
    const frac = rules.runFractionalDA(ctx);
    save('aug7', { note: 'exploratory (plan v0.24); the saved run of 20:00 on 7 August recomputed with the research code; '
      + 'blocking = listings ranked above the record\'s assignment whose score exceeds the department\'s lowest retained score',
      runId: run.runId, completedAt: run.completedAt, counts, weightsConverged: w.converged,
      v2: { blocking: blockingByDepartment(v2), load: loadStats(v2, ctx), covered1706: count(cutoffs(v2, 'marginal')) },
      fractional: { load: loadStats(frac, ctx), covered1706: count(cutoffs(frac, 'marginal')) } });
  }

  if (SECTION === 'concentration' || SECTION === 'eligibility') {
    const { candidates } = prepare(runs.get(EVALUATED).records);
    const w = rake(candidates);
    const ctx = lib.buildContext(candidates, year, w.weightMap);
    const frac = rules.runFractionalDA(ctx);
    const releasedV3 = new Set(released.filter(r => r.v3 !== '').map(r => Number(r.gid)));
    const releasedOrder = new Set(released.filter(r => r.v1 !== '' || r.v2 !== '' || r.fractional !== '').map(r => Number(r.gid)));
    if (SECTION === 'concentration') {
      const share = [], heavy = [];
      for (const r of J2) {
        const res = frac.results.get(r.gid);
        if (!res || !res.held.length) continue;
        share.push(Math.max(...res.held.map(h => h.mass)) / res.assignedWeight);
        heavy.push(Math.max(...res.held.map(h => ctx.weightOf(h.uid))) >= res.quota ? 1 : 0);
      }
      save('concentration', { note: 'exploratory (plan v0.24); Fractional allocation of the evaluated run on the released J2 set',
        departments: share.length, largestRecordShare: { median: quantile(share, 0.5), p90: quantile(share, 0.9),
          atLeastHalf: share.filter(x => x >= 0.5).length, atLeast90Percent: share.filter(x => x >= 0.9).length },
        departmentsWithARecordWeightAtLeastTheQuota: sum(heavy) });
    } else {
      const eligible = new Map();
      for (const list of ctx.eligibleByUid.values()) for (const wish of list) eligible.set(wish.gid, (eligible.get(wish.gid) || 0) + 1);
      const holders = gid => frac.results.get(gid)?.held.length ?? 0;
      const summarize = set => {
        const g = [...set];
        return { departments: g.length, eligibleBelow5: g.filter(x => (eligible.get(x) || 0) < 5).length,
          eligibleBelow10: g.filter(x => (eligible.get(x) || 0) < 10).length, eligibleBelow20: g.filter(x => (eligible.get(x) || 0) < 20).length,
          holdersBelow5: g.filter(x => holders(x) < 5).length, holdersBelow10: g.filter(x => holders(x) < 10).length };
      };
      save('eligibility', { note: 'exploratory (plan v0.24); counts per department summarized over released values only',
        releasedV3: summarize(releasedV3), releasedV1V2OrFractional: summarize(releasedOrder) });
    }
  }

  if (SECTION === 'returners') {
    const REGION = {
      south: ['南華大學', '國立中山大學', '國立中正大學', '國立嘉義大學', '國立屏東大學', '國立成功大學', '國立臺南大學',
        '國立臺南藝術大學', '國立高雄大學', '國立高雄師範大學', '長榮大學', '義守大學', '高雄醫學大學'],
      east_and_kinmen: ['國立東華大學', '國立臺東大學', '慈濟大學', '國立金門大學'] };
    const info = new Map(released.map(r => {
      const south = REGION.south.includes(r.school) || (r.school === '實踐大學' && r.department.includes('高雄校區'));
      const se = south || REGION.east_and_kinmen.includes(r.school);
      const level = r.baseline !== '' ? Number(r.baseline) / Number(r.weightTotal) : null;
      return [Number(r.gid), { southEast: se, priv: !/^(國立|臺北市立|高雄市立|市立)/.test(r.school), low: level !== null && level < 30 }];
    }));
    const { candidates } = prepare(runs.get(EVALUATED).records);
    const w = rake(candidates);
    const ctx = lib.buildContext(candidates, year, w.weightMap);
    const describe = group => {
      const rows = group.map(c => {
        const el = ctx.eligibleByUid.get(c.uid) || [];
        const known = el.filter(x => info.has(x.gid));
        const grades = Object.values(c.normalizedScores || {}).filter(isNum);
        return { w: w.weightMap.get(c.uid) || 0, listed: c.wishes.length, eligible: el.length,
          priv: known.length ? known.filter(x => info.get(x.gid).priv).length / known.length : null,
          se: known.length ? known.filter(x => info.get(x.gid).southEast).length / known.length : null,
          low: known.length ? known.filter(x => info.get(x.gid).low).length / known.length : null,
          subjects: grades.length, grade: grades.length ? mean(grades) : null };
      });
      const both = key => {
        const v = rows.filter(r => isNum(r[key]));
        const W = sum(v.map(r => r.w));
        return { unweighted: mean(v.map(r => r[key])), weighted: W ? sum(v.map(r => r.w * r[key])) / W : null };
      };
      return { records: rows.length, weightSum: sum(rows.map(r => r.w)), meanWeight: mean(rows.map(r => r.w)),
        listed: both('listed'), eligible: both('eligible'), privateShareOfEligible: both('priv'),
        southEastKinmenShareOfEligible: both('se'), levelBelow30ShareOfEligible: both('low'), subjects: both('subjects'),
        meanNormalizedGrade: both('grade') };
    };
    const before = candidates.filter(c => isNum(c.updatedAt) && c.updatedAt < DEADLINE);
    const after = candidates.filter(c => !(isNum(c.updatedAt) && c.updatedAt < DEADLINE));
    save('returners', { note: 'exploratory (plan v0.24); evaluated run; "before" = last updated before 16:30 on 8 August',
      before: describe(before), afterOrUnknown: describe(after) });
  }
} finally {
  closeRuntime();
}
