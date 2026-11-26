/** 研究旁錄：沿用凍結分支次序記錄質量去向，不修改平台或凍結核心。 */
import assert from 'node:assert/strict';
import { isDeepStrictEqual } from 'node:util';

const EPS = 1e-7;

/** 補償加總，降低大量事件的累積捨入誤差。 */
function accumulator() {
  let sum = 0, correction = 0, count = 0, maximum = 0;
  return {
    add(value) {
      const adjusted = value - correction;
      const next = sum + adjusted;
      correction = (next - sum) - adjusted;
      sum = next;
      count++;
      maximum = Math.max(maximum, value);
    },
    snapshot: () => ({ mass: sum, count, maximum }),
  };
}

/** 凍結 collect 由外部注入；回傳研究輸出與彙總質量帳，沒有 I/O。 */
export function traceFractionalAllocation(ctx, collect, { maxEvents = 20_000_000 } = {}) {
  assert.equal(new Set(ctx.candidateUids).size, ctx.candidateUids.length, '考生鍵不可重複');
  const supply = accumulator(), noPreferences = accumulator(), exhausted = accumulator();
  const droppedAtPop = accumulator(), droppedDisplaced = accumulator(), droppedHeld = accumulator();
  const dept = new Map();
  for (const gid of ctx.deptIds) {
    const quota = ctx.quotaOf(gid);
    assert(Number.isFinite(quota) && quota >= 0, '容量必須有限且非負');
    dept.set(gid, { gid, quota, entries: new Map(), rejectScores: new Set() });
  }
  const queue = [];
  for (const uid of ctx.candidateUids) {
    const weight = ctx.weightOf(uid), el = ctx.eligibleByUid.get(uid) || [];
    assert(Number.isFinite(weight) && weight >= 0, '供給必須有限且非負');
    assert.equal(new Set(el.map(w => w.gid)).size, el.length, '有效志願不可重複');
    supply.add(weight);
    if (el.length) queue.push({ uid, wi: 0, mass: weight });
    else noPreferences.add(weight);
  }
  let events = 0;
  while (queue.length) {
    if (++events > maxEvents) throw new Error('研究旁錄未完成：事件數超過上限');
    const p = queue.shift();
    if (p.mass <= EPS) { if (p.mass > 0) droppedAtPop.add(p.mass); continue; }
    const el = ctx.eligibleByUid.get(p.uid) || [];
    if (p.wi >= el.length) { exhausted.add(p.mass); continue; }
    const wish = el[p.wi], d = dept.get(wish.gid);
    if (!d || d.quota <= 0) { queue.push({ uid: p.uid, wi: p.wi + 1, mass: p.mass }); continue; }
    const existing = d.entries.get(p.uid);
    if (existing) existing.mass += p.mass;
    else d.entries.set(p.uid, { uid: p.uid, weightedScore: wish.score, mass: p.mass, wishIndex: p.wi });
    const sorted = [...d.entries.values()].sort(ctx.compareFor(wish.gid));
    let cum = 0;
    for (const e of sorted) {
      const room = d.quota - cum;
      let displaced = 0;
      if (room <= EPS) { displaced = e.mass; e.mass = 0; }
      else if (e.mass <= room) cum += e.mass;
      else { displaced = e.mass - room; e.mass = room; cum = d.quota; }
      if (displaced > EPS) {
        queue.push({ uid: e.uid, wi: e.wishIndex + 1, mass: displaced });
        d.rejectScores.add(e.weightedScore);
      } else if (displaced > 0) droppedDisplaced.add(displaced);
      if (e.mass <= EPS) {
        if (e.mass > 0) droppedHeld.add(e.mass);
        d.entries.delete(e.uid);
      }
    }
  }
  const st = new Map(ctx.candidateUids.map(uid => [uid, { uid, el: ctx.eligibleByUid.get(uid) || [], assigned: null }]));
  const retained = accumulator();
  for (const d of dept.values()) {
    for (const e of d.entries.values()) {
      retained.add(e.mass);
      const s = st.get(e.uid);
      if (!s.assigned || e.wishIndex < s.assigned.wishIndex) {
        s.assigned = { uid: e.uid, weightedScore: e.weightedScore, wishIndex: e.wishIndex, rank: s.el[e.wishIndex].rank };
      }
    }
  }
  const output = collect(ctx, dept, st, d => [...d.entries.values()].map(e => ({ uid: e.uid, score: e.weightedScore, mass: e.mass })));
  output.events = events;
  output.rejectScoresByGid = new Map([...dept].map(([gid, d]) => [gid, d.rejectScores]));
  const accounts = Object.fromEntries(Object.entries({ supply, retained, noPreferences, exhausted, droppedAtPop, droppedDisplaced, droppedHeld }).map(([name, counter]) => [name, counter.snapshot()]));
  const droppedMass = accounts.droppedAtPop.mass + accounts.droppedDisplaced.mass + accounts.droppedHeld.mass;
  const dropEvents = accounts.droppedAtPop.count + accounts.droppedDisplaced.count + accounts.droppedHeld.count;
  const balanceResidual = accounts.supply.mass - accounts.retained.mass - accounts.noPreferences.mass - accounts.exhausted.mass - droppedMass;
  return { output, ledger: { completed: true, events, epsilon: EPS, accounts, droppedMass,
    dropEvents, dropMassBound: EPS * dropEvents, balanceResidual } };
}

/** 每次旁錄與未修改凍結函式核對全部校系、拒絕端點與事件數。 */
export function verifyTrackedOutput(reference, tracked) {
  assert(isDeepStrictEqual(tracked.results, reference.results), '旁錄改變校系配置或邊際資訊');
  assert(isDeepStrictEqual(tracked.rejectScoresByGid, reference.rejectScoresByGid), '旁錄改變拒絕分數集合');
  assert.equal(tracked.events, reference.events, '旁錄改變事件數');
}
