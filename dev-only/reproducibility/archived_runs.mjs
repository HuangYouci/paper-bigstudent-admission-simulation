/** 比較保存梯次的校系門檻；不讀取候選人資料、不重建歷史部署。 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const repo = process.env.BIGSTUDENT_REPOSITORY;
if (!repo) throw new Error('請設定 BIGSTUDENT_REPOSITORY');
const paper = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const metadata = JSON.parse(fs.readFileSync(path.join(paper, 'data/run-metadata-audit.json')));
const benchmark = JSON.parse(fs.readFileSync(path.join(paper, 'sources/benchmark-snapshot.md'), 'utf8').split('```json\n')[1].split('\n```')[0]);
const requireRepo = createRequire(path.join(repo, 'package.json'));
const { initializeApp, applicationDefault, deleteApp } = requireRepo('firebase-admin/app');
const { getFirestore } = requireRepo('firebase-admin/firestore');
const app = initializeApp({ credential: applicationDefault(), projectId: 'bigstudent-org' }, 'paper-archive-readonly');
const predictions = new Map();
const rows = [];
try {
  for (const run of metadata.rows) {
    const parts = await getFirestore(app).doc(`statistics/admission_simulation/runs/${run.runId}`).collection('parts').select('data').get();
    const depts = new Map();
    for (const part of parts.docs) {
      if (!part.id.startsWith('departments_')) continue;
      const data = part.data().data;
      assert(data && typeof data === 'object', '校系分片格式不符');
      for (const [gid, values] of Object.entries(data)) {
        assert(!depts.has(Number(gid)), '分片出現重複校系');
        const value = run.algorithmVersion === 'ast-da-v3' ? values.publishedCutoff : values.minimumAssignedScore;
        assert(value === null || value === undefined || Number.isFinite(value), '保存門檻不是有限數值');
        depts.set(Number(gid), value ?? null);
      }
    }
    const supported = benchmark.rows.filter(row => depts.get(row.gid) !== null && depts.has(row.gid));
    assert(supported.length > 0, '梯次沒有可比對校系');
    const paired = supported.filter(row => row.baseline !== null);
    const mae = (input, key) => input.reduce((sum, row) => sum + Math.abs((key === 'baseline' ? row.baseline : depts.get(row.gid)) - row.actual) / row.weightTotal, 0) / input.length;
    rows.push({ ...run, departmentDocuments: depts.size, cutoffField: run.algorithmVersion === 'ast-da-v3' ? 'publishedCutoff' : 'minimumAssignedScore',
      timeOrderValid: Boolean(run.startedAt && run.completedAt && new Date(run.completedAt) >= new Date(run.startedAt)),
      supported: supported.length, ownMAE: mae(supported), paired: paired.length, pairedMAE: mae(paired), pairedBaselineMAE: mae(paired, 'baseline') });
    predictions.set(run.runId, depts);
  }
  const valid = rows.filter(row => row.timeOrderValid);
  const common = benchmark.rows.filter(row => row.baseline !== null && valid.every(run => predictions.get(run.runId).has(row.gid) && predictions.get(run.runId).get(row.gid) !== null));
  const commonMetrics = { n: common.length, baselineMAE: common.reduce((sum, row) => sum + Math.abs(row.baseline - row.actual) / row.weightTotal, 0) / common.length,
    runs: valid.map(run => ({ runId: run.runId, mae: common.reduce((sum, row) => sum + Math.abs(predictions.get(run.runId).get(row.gid) - row.actual) / row.weightTotal, 0) / common.length })) };
  const columns = ['gid', 'actual', 'weightTotal', 'baseline', ...rows.map(row => row.runId)];
  const csv = [columns.join(','), ...benchmark.rows.map(row => [row.gid, row.actual, row.weightTotal, row.baseline ?? '', ...rows.map(run => predictions.get(run.runId).get(row.gid) ?? '')].join(','))].join('\n') + '\n';
  fs.writeFileSync(path.join(paper, 'data/archived-run-cutoffs.csv'), csv);
  const result = { checkedAt: new Date().toISOString(), rows, commonMetrics,
    note: '資料為目前可讀的歷史文件，並非經外部認證不可變封存。版本與樣本隨梯次同時改變；固定集合比較仍不能將差異解讀為單一因果效果。時間順序異常梯次不納入共同時間序列。歷史基準仍為事後凍結重建。' };
  fs.writeFileSync(path.join(paper, 'data/archived-run-results.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
} finally {
  await deleteApp(app);
}
