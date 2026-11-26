/**
 * Read-only export of the saved 2026 simulation inputs for author-side checks (third revision).
 *
 * Reads, for each saved 2026 run, the run document's metadata and the projected candidate fields
 * duplicateOf, input.scores, input.wishes and input.sourceUpdatedAt. Account identifiers are replaced
 * by keyed hashes whose key exists only in memory during the export, so the file holds no account identifier;
 * grades, ordered preferences and update times are nevertheless close to unique, so the author, who controls the
 * database, could re-identify records by matching them, and the file is personal data. (Comment corrected on
 * 26 November 2026; the code is unchanged.) No name, contact detail or token is read. The file is written to a private folder
 * in the author's Downloads directory (not cloud-synced) with owner-only permissions and is to be
 * deleted after the analyses; it is never committed or uploaded.
 *
 * Usage (macOS, inside the platform repository, with Google application-default credentials):
 *   BIGSTUDENT_REPOSITORY="$PWD" node /path/to/export_runs.mjs
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';

const RUNS = [
  'ast_20260805T175904Z', 'ast_20260806T120005Z', 'ast_20260807T022008Z', 'ast_20260807T120012Z',
  'ast_20260808T035958Z', 'ast_20260808T095000Z', 'ast_20260813T012242Z', 'ast_20260815T150000Z',
];
const repo = process.env.BIGSTUDENT_REPOSITORY;
if (!repo || !path.isAbsolute(repo)) throw new Error('Set BIGSTUDENT_REPOSITORY to the absolute path of the platform repository');
const requireRepo = createRequire(path.join(repo, 'package.json'));
const { initializeApp, applicationDefault, deleteApp } = requireRepo('firebase-admin/app');
const { getFirestore } = requireRepo('firebase-admin/firestore');
const app = initializeApp({ credential: applicationDefault(), projectId: 'bigstudent-org' }, 'paper-readonly-export');
const key = crypto.randomBytes(32);
const pseudonym = uid => crypto.createHmac('sha256', key).update(String(uid)).digest('hex').slice(0, 20);
const millis = value => (value && typeof value.toMillis === 'function') ? value.toMillis()
  : (typeof value === 'number' ? value : (typeof value === 'string' ? Date.parse(value) : null));

const out = { exportedAt: new Date().toISOString(), note: 'Personal data (pseudonymized). Keep on this computer only and delete after the analyses.', runs: [] };
try {
  const db = getFirestore(app);
  for (const runId of RUNS) {
    const ref = db.doc(`statistics/admission_simulation/runs/${runId}`);
    const meta = (await ref.get()).data() || {};
    const snap = await ref.collection('candidates').select('duplicateOf', 'input.scores', 'input.wishes', 'input.sourceUpdatedAt').get();
    const records = [];
    for (const doc of snap.docs) {
      const d = doc.data();
      records.push({ id: pseudonym(doc.id), dup: Boolean(d.duplicateOf), scores: d.input?.scores || {},
        wishes: Array.isArray(d.input?.wishes) ? d.input.wishes : [], updatedAt: millis(d.input?.sourceUpdatedAt) });
    }
    out.runs.push({ runId, sampleCount: meta.sampleCount ?? null, nationalBaselineCount: meta.nationalBaselineCount ?? null,
      algorithmVersion: meta.algorithmVersion ?? null, startedAt: millis(meta.startedAt), completedAt: millis(meta.completedAt),
      documents: snap.size, records });
    console.log(JSON.stringify({ runId, documents: snap.size, withTimestamp: records.filter(r => r.updatedAt !== null).length }));
  }
} finally {
  await deleteApp(app);
}
const folder = path.join(os.homedir(), 'Downloads', 'bigstudent-paper-private');
fs.mkdirSync(folder, { recursive: true, mode: 0o700 });
const file = path.join(folder, 'runs-export.json');
fs.writeFileSync(file, JSON.stringify(out), { mode: 0o600 });
console.log(JSON.stringify({ wrote: file, runs: out.runs.length, bytes: fs.statSync(file).size }));
