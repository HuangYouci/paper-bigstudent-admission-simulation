/** 唯讀重讀保存梯次，個人輸入與結果僅在記憶體，輸出為不可識別個人的彙總。 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { summarizePersonalProxies } from './personal-proxy.mjs';

const paper = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const repo = process.env.BIGSTUDENT_REPOSITORY;
assert(repo && path.isAbsolute(repo), '請指定平台 repository 絕對路徑');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const manifest = JSON.parse(fs.readFileSync(path.join(paper, 'data/manifest.json'), 'utf8'));
const bytes = fs.readFileSync(path.join(paper, 'sources/benchmark-snapshot.md'));
assert.equal(hash(bytes), manifest.aggregateSourceSHA256, '封存官方門檻來源雜湊不符');
const snapshot = JSON.parse(bytes.toString('utf8').split('```json\n')[1].split('\n```')[0]);
assert.equal(snapshot.runId, manifest.runId, '來源梯次不符');
const cutoffs = new Map(snapshot.rows.map(row => [row.gid, row.actual]));
assert.equal(cutoffs.size, 1706, '官方門檻校系數不符');
const requireRepo = createRequire(path.join(repo, 'package.json'));
const { initializeApp, applicationDefault, deleteApp } = requireRepo('firebase-admin/app');
const { getFirestore } = requireRepo('firebase-admin/firestore');
const app = initializeApp({ credential: applicationDefault(), projectId: 'bigstudent-org' }, 'paper-readonly-personal-proxy');
const cloud = getFirestore(app);
try {
  const fields = ['duplicateOf', 'input.wishes', 'result.status', 'result.assignedDeptGroupId', 'result.assignedWishRank', 'result.wishScores'];
  const snap = await cloud.doc(`statistics/admission_simulation/runs/${manifest.runId}`).collection('candidates').select(...fields).get();
  const records = [];
  let mirrors = 0;
  for (const doc of snap.docs) {
    const data = doc.data();
    if (data.duplicateOf) { mirrors++; continue; }
    const result = data.result;
    assert(result && typeof result === 'object', '缺少保存的模擬結果');
    records.push({ wishes: data.input?.wishes, scores: result.wishScores, status: result.status,
      assignedGid: result.assignedDeptGroupId, assignedRank: result.assignedWishRank });
  }
  assert.equal(snap.size, 4631, '保存文件數改變');
  assert.equal(mirrors, 4, '鏡射文件數改變');
  assert.equal(records.length, 4627, '研究輸入筆數改變');
  const output = { checkedAt: new Date().toISOString(), runId: manifest.runId,
    access: { readOnly: true, projectedFields: fields, totalDocuments: snap.size, excludedMirrors: mirrors,
      contactFieldsRead: false, tokensRead: false, individualRecordsSaved: false },
    officialCutoffSource: { path: 'sources/benchmark-snapshot.md', sha256: hash(bytes), departments: cutoffs.size,
      audit: 'data/official-truth-audit.json' },
    interpretation: '保存模擬結果與官方一般生門檻重建的落點一致性；不是核實會員實際錄取結果的準確率。',
    assumptions: ['平台填報成績與志願成立，並不代表已核實正式成績或志願卡',
      '保存 wishScores 的合格性判定沿用，沒有重新確認正式檢定、術科或特殊身分',
      '舊口徑將同分視為達標；不確定性診斷另保留同分與缺門檻的可能結果',
      '保存文件為目前可讀版本，不是外部不可變封存'],
    ...summarizePersonalProxies(records, cutoffs) };
  fs.writeFileSync(path.join(paper, 'data/personal-proxy-results.json'), JSON.stringify(output, null, 2) + '\n');
  console.log(JSON.stringify({ counts: output.counts, rates: output.rates, uncertainty: output.uncertainty }, null, 2));
} finally {
  await cloud.terminate();
  await deleteApp(app);
}
