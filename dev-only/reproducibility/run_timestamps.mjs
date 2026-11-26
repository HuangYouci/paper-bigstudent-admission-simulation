/**
 * Server-assigned timestamps of the eight saved 2026 runs (added after the fifth simulated review; optional).
 *
 * Firestore assigns each document's createTime and updateTime on the server; clients cannot set them. This script
 * reads, read-only, for each saved run: the run document's createTime and updateTime and its completion time; the
 * createTime and updateTime of the department result shards (parts/departments_*), requested with an empty field mask
 * so that no department value is read; and the earliest and latest createTime and updateTime over the candidate
 * documents, also with an empty field mask, so that no grade, preference, or identifier is read or printed. It prints
 * aggregates only and writes them to out/run-timestamps.json. A shard or candidate updateTime before the results
 * (17 August 2026, 09:00 Taiwan time) shows that the stored outputs were not rewritten after the outcomes were known.
 *
 * Usage (macOS, inside the platform repository, with Google application-default credentials):
 *   BIGSTUDENT_REPOSITORY="$PWD" node /path/to/run_timestamps.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const RUNS = [
  'ast_20260805T175904Z', 'ast_20260806T120005Z', 'ast_20260807T022008Z', 'ast_20260807T120012Z',
  'ast_20260808T035958Z', 'ast_20260808T095000Z', 'ast_20260813T012242Z', 'ast_20260815T150000Z',
];
const RESULTS = Date.parse('2026-08-17T01:00:00Z');
const repo = process.env.BIGSTUDENT_REPOSITORY;
if (!repo || !path.isAbsolute(repo)) throw new Error('Set BIGSTUDENT_REPOSITORY to the absolute path of the platform repository');
const requireRepo = createRequire(path.join(repo, 'package.json'));
const { initializeApp, applicationDefault, deleteApp } = requireRepo('firebase-admin/app');
const { getFirestore } = requireRepo('firebase-admin/firestore');
const app = initializeApp({ credential: applicationDefault(), projectId: 'bigstudent-org' }, 'paper-readonly-timestamps');
const iso = t => (t ? t.toDate().toISOString() : null);
const range = docs => {
  const c = docs.map(d => d.createTime.toMillis()), u = docs.map(d => d.updateTime.toMillis());
  return docs.length ? { documents: docs.length, earliestCreate: new Date(Math.min(...c)).toISOString(),
    latestCreate: new Date(Math.max(...c)).toISOString(), earliestUpdate: new Date(Math.min(...u)).toISOString(),
    latestUpdate: new Date(Math.max(...u)).toISOString(), updatedAfterResults: u.filter(x => x >= RESULTS).length } : { documents: 0 };
};
const out = { readAt: new Date().toISOString(), resultsAnnounced: new Date(RESULTS).toISOString(), runs: [] };
try {
  const db = getFirestore(app);
  for (const runId of RUNS) {
    const ref = db.doc(`statistics/admission_simulation/runs/${runId}`);
    const run = await ref.get();
    const meta = run.data() || {};
    const parts = await ref.collection('parts').select().get();
    const candidates = await ref.collection('candidates').select().get();
    const completed = meta.completedAt && typeof meta.completedAt.toDate === 'function' ? meta.completedAt.toDate().toISOString() : null;
    out.runs.push({ runId, runCreateTime: iso(run.createTime), runUpdateTime: iso(run.updateTime), completedAt: completed,
      departmentShards: range(parts.docs), candidateDocuments: range(candidates.docs) });
    console.log(JSON.stringify(out.runs.at(-1)));
  }
} finally {
  await deleteApp(app);
}
const paper = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
fs.mkdirSync(path.join(paper, 'out'), { recursive: true });
fs.writeFileSync(path.join(paper, 'out/run-timestamps.json'), JSON.stringify(out, null, 2) + '\n');
console.log(JSON.stringify({ wrote: path.join(paper, 'out/run-timestamps.json') }));
