import assert from 'node:assert/strict';

/** 依一般生官方門檻重建落點；同分與缺門檻只列可能結果，不代替本人錄取真值。 */
export function reconstructThresholdOutcome(wishes, scores, cutoffs) {
  assert(Array.isArray(wishes) && Array.isArray(scores), '志願與分數必須為陣列');
  assert.equal(wishes.length, scores.length, '志願與分數長度不符');
  assert(wishes.every(gid => Number.isInteger(gid) && gid > 0), '志願代碼格式不符');
  assert(scores.every(score => score === null || (typeof score === 'number' && Number.isFinite(score))), '志願分數格式不符');
  const possible = [];
  let legacy = null;
  let legacyRank = null;
  let reachableTies = 0;
  let reachableMissingCutoffs = 0;
  let strictPassFound = false;
  for (let index = 0; index < wishes.length; index++) {
    const score = scores[index];
    if (score === null) continue;
    const gid = wishes[index];
    const cutoff = cutoffs.get(gid);
    if (cutoff === undefined) {
      reachableMissingCutoffs++;
      possible.push(gid);
      continue;
    }
    assert(typeof cutoff === 'number' && Number.isFinite(cutoff) && cutoff > 0, '官方門檻格式不符');
    if (score < cutoff) continue;
    if (legacy === null) { legacy = gid; legacyRank = index + 1; }
    possible.push(gid);
    if (score === cutoff) { reachableTies++; continue; }
    strictPassFound = true;
    break;
  }
  if (!strictPassFound) possible.push(null);
  return { legacy, legacyRank, possible: [...new Set(possible)], reachableTies, reachableMissingCutoffs };
}

/** 彙總保存的模擬結果與門檻重建落點；只輸出計數，沒有個人識別資料。 */
export function summarizePersonalProxies(records, cutoffs) {
  const counts = { total: 0, bothAssigned: 0, sameDepartment: 0, proxyEarlierWish: 0, proxyLaterWish: 0,
    simulatedOnlyAssigned: 0, proxyOnlyAssigned: 0, bothUnassigned: 0 };
  const uncertainty = { determinate: 0, reachableTieRecords: 0, reachableMissingCutoffRecords: 0,
    agreementLowerCount: 0, agreementUpperCount: 0 };
  const statuses = {};
  let absoluteRankError = 0;
  for (const record of records) {
    const { wishes, scores, status, assignedGid, assignedRank } = record;
    assert(typeof status === 'string', '保存結果缺少狀態');
    statuses[status] = (statuses[status] ?? 0) + 1;
    const simulated = status === 'assigned' ? assignedGid : null;
    if (simulated !== null) {
      assert(Number.isInteger(simulated) && simulated > 0, '保存分發校系格式不符');
      assert(Number.isInteger(assignedRank) && assignedRank > 0 && wishes[assignedRank - 1] === simulated, '保存志願序與分發校系不符');
    } else {
      assert(assignedGid === null, '未分發狀態卻保存分發校系');
    }
    const reconstructed = reconstructThresholdOutcome(wishes, scores, cutoffs);
    counts.total++;
    if (simulated !== null && reconstructed.legacy !== null) {
      counts.bothAssigned++;
      absoluteRankError += Math.abs(assignedRank - reconstructed.legacyRank);
      if (simulated === reconstructed.legacy) counts.sameDepartment++;
      else if (reconstructed.legacyRank < assignedRank) counts.proxyEarlierWish++;
      else counts.proxyLaterWish++;
    } else if (simulated !== null) counts.simulatedOnlyAssigned++;
    else if (reconstructed.legacy !== null) counts.proxyOnlyAssigned++;
    else counts.bothUnassigned++;
    const possibilities = reconstructed.possible;
    if (possibilities.length === 1) uncertainty.determinate++;
    if (reconstructed.reachableTies > 0) uncertainty.reachableTieRecords++;
    if (reconstructed.reachableMissingCutoffs > 0) uncertainty.reachableMissingCutoffRecords++;
    if (possibilities.length === 1 && possibilities[0] === simulated) uncertainty.agreementLowerCount++;
    if (possibilities.includes(simulated)) uncertainty.agreementUpperCount++;
  }
  const ratio = (value, denominator) => denominator > 0 ? value / denominator : null;
  return { counts, statuses, rates: {
    sameDepartmentAmongBothAssigned: ratio(counts.sameDepartment, counts.bothAssigned),
    sameDepartmentAmongAllRecords: ratio(counts.sameDepartment, counts.total),
    sameOutcomeIncludingBothUnassigned: ratio(counts.sameDepartment + counts.bothUnassigned, counts.total),
    meanAbsoluteWishRankDifferenceAmongBothAssigned: ratio(absoluteRankError, counts.bothAssigned),
  }, uncertainty: { ...uncertainty,
    agreementLowerRate: ratio(uncertainty.agreementLowerCount, counts.total),
    agreementUpperRate: ratio(uncertainty.agreementUpperCount, counts.total),
    interpretation: '在保存成績、志願與檢定判定成立的一般生門檻模型下，同分與缺門檻的可能結果界限；不是信賴區間或本人錄取準確率界限。',
  } };
}
