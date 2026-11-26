/** 依穩定配置定義獨立檢查質量可行性及阻擋邊。 */
import assert from 'node:assert/strict';

/** 檢查固定嚴格比序下的配置；可保留不合格診斷而不拋錯。 */
export function auditAllocation(context, output, { validate = true } = {}) {
  const byUid = new Map(context.candidateUids.map(uid => [uid, []]));
  for (const wishes of context.eligibleByUid.values()) {
    assert.equal(new Set(wishes.map(w => w.gid)).size, wishes.length, '有效志願不可重複');
  }
  let maxCapacityExcess = 0, maxSupplyExcess = 0, minimumMass = Infinity, blockingPairs = 0;
  let maxBlockingMass = 0, positiveBlockingEdges = 0, eligibleEdges = 0, maxReportedWeightDifference = 0;
  for (const [gid, result] of output.results) {
    const actualWeight = result.held.reduce((sum, h) => sum + h.mass, 0);
    maxCapacityExcess = Math.max(maxCapacityExcess, actualWeight - context.quotaOf(gid));
    maxReportedWeightDifference = Math.max(maxReportedWeightDifference, Math.abs(actualWeight - result.assignedWeight));
    for (const held of result.held) {
      assert(Number.isFinite(held.mass), '配置質量必須有限');
      minimumMass = Math.min(minimumMass, held.mass);
      const position = context.eligibleByUid.get(held.uid)?.findIndex(w => w.gid === gid);
      assert(position !== undefined && position >= 0, '配置出現非合格志願');
      byUid.get(held.uid).push({ gid, position, mass: held.mass });
    }
  }
  for (const uid of context.candidateUids) {
    const holdings = byUid.get(uid);
    const supply = context.weightOf(uid);
    maxSupplyExcess = Math.max(maxSupplyExcess, holdings.reduce((sum, h) => sum + h.mass, 0) - supply);
    for (const [position, wish] of context.eligibleByUid.get(uid).entries()) {
      const ownMass = holdings.find(h => h.gid === wish.gid)?.mass || 0;
      const betterSupply = holdings.filter(h => h.position <= position).reduce((sum, h) => sum + h.mass, 0);
      const compare = context.compareFor(wish.gid);
      const contender = { uid, weightedScore: wish.score };
      const preferredMass = output.results.get(wish.gid).held.filter(h => compare({ ...h, weightedScore: h.score }, contender) <= 0).reduce((sum, h) => sum + h.mass, 0);
      const blockingMass = Math.max(0, Math.min(supply - ownMass,
        supply - betterSupply, context.quotaOf(wish.gid) - preferredMass));
      eligibleEdges++;
      maxBlockingMass = Math.max(maxBlockingMass, blockingMass);
      positiveBlockingEdges += Number(blockingMass > 0);
      blockingPairs += Number(blockingMass > 1e-6);
    }
  }
  if (validate) assert(maxCapacityExcess <= 1e-6 && maxSupplyExcess <= 1e-6 && minimumMass >= 0 && maxReportedWeightDifference <= 1e-6, '配置可行性稽核失敗');
  if (validate) assert.equal(blockingPairs, 0, '穩定配置稽核失敗');
  return { maxCapacityExcess, maxSupplyExcess, minimumMass: minimumMass === Infinity ? null : minimumMass,
    blockingPairs, maxBlockingMass, positiveBlockingEdges, eligibleEdges, maxReportedWeightDifference, tolerance: 1e-6,
    note: '全部合格邊上限為個人供給；連續阻擋量使用完整比序與較好志願，微小正值可能是浮點誤差。不可行配置僅作診斷。' };
}
