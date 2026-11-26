/** 唯讀檢查梯次時間鏈；不查詢個人成績或聯絡欄位。 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const repo = process.env.BIGSTUDENT_REPOSITORY;
if (!repo) throw new Error('請指定 BIGSTUDENT_REPOSITORY');
const requireRepo = createRequire(path.join(repo, 'package.json'));
const { initializeApp, applicationDefault, deleteApp } = requireRepo('firebase-admin/app');
const { getFirestore } = requireRepo('firebase-admin/firestore');
const app = initializeApp({ credential: applicationDefault(), projectId: 'bigstudent-org' }, 'paper-run-metadata-readonly');
const deadline = new Date('2026-08-08T08:30:00Z');
try {
  const snap = await getFirestore(app).collection('statistics/admission_simulation/runs')
    .select('startedAt', 'completedAt', 'sampleCount', 'algorithmVersion', 'status').get();
  const rows = snap.docs.map(doc => {
    const d = doc.data();
    return { runId: doc.id, startedAt: d.startedAt?.toDate().toISOString() || null,
      completedAt: d.completedAt?.toDate().toISOString() || null, sampleCount: d.sampleCount ?? null,
      algorithmVersion: d.algorithmVersion ?? null, status: d.status ?? null };
  }).filter(row => row.runId.startsWith('ast_2026')).sort((a, b) => (a.completedAt || '').localeCompare(b.completedAt || ''));
  const beforeDeadline = rows.filter(row => row.completedAt && new Date(row.completedAt) <= deadline);
  const result = { checkedAt: new Date().toISOString(), queryScope: '2026 分科梯次；來源文件目前可查，不表示不可變時間認證',
    deadline: deadline.toISOString(), totalRunDocuments: snap.size, ast2026RunCount: rows.length,
    beforeDeadlineCount: beforeDeadline.length, latestBeforeDeadline: beforeDeadline.at(-1) || null, rows };
  const paper = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  fs.writeFileSync(path.join(paper, 'data/run-metadata-audit.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify({ totalRunDocuments: snap.size, ast2026RunCount: rows.length, beforeDeadlineCount: beforeDeadline.length, latestBeforeDeadline: result.latestBeforeDeadline }));
} finally {
  await deleteApp(app);
}
