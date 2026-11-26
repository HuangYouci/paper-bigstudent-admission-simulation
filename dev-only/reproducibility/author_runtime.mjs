/**
 * Frozen runtime for the author-side record-level checks (author_checks.mjs).
 *
 * Verifies the audited platform modules against data/manifest.json, loads the frozen admission database
 * read-only from its version-control object, and imports the platform's allocation code. better-sqlite3 is
 * a native module, so NODE_MODULES_FROM may name a package.json whose node_modules holds a build for the
 * machine running the checks (for example a Linux virtual machine on the author's computer).
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createRequire, registerHooks } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';

export const paper = process.env.PAPER_DIR || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const repo = process.env.BIGSTUDENT_REPOSITORY;
if (!repo || !path.isAbsolute(repo)) throw new Error('Set BIGSTUDENT_REPOSITORY to the absolute path of the platform repository');
export const manifest = JSON.parse(fs.readFileSync(path.join(paper, 'data/manifest.json'), 'utf8'));
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
for (const [name, expected] of Object.entries(manifest.sourceHashes)) {
  if (name === 'lib/database.db') continue;
  assert.equal(sha256(fs.readFileSync(path.join(repo, name))), expected, `platform module differs from the manifest: ${name}`);
}
const frozen = execFileSync('git', ['show', `${manifest.verifiableResearchCommit}:lib/database.db`], { cwd: repo, maxBuffer: 300_000_000 });
assert.equal(sha256(frozen), manifest.sourceHashes['lib/database.db'], 'frozen database hash mismatch');
const Database = createRequire(process.env.NODE_MODULES_FROM || path.join(repo, 'package.json'))('better-sqlite3');
const sqlite = new Database(frozen, { readonly: true });
sqlite.pragma('query_only = ON');
globalThis.__paperReadonlyDatabase = sqlite;
// Every platform file that the checks load is hashed, so that the outputs record exactly which code produced them.
const loaded = new Map();
const repoURL = pathToFileURL(repo + path.sep).href;
const recordFile = url => {
  if (url.startsWith(repoURL) && !loaded.has(url)) loaded.set(url.slice(repoURL.length), sha256(fs.readFileSync(fileURLToPath(url))));
};
recordFile(pathToFileURL(path.join(repo, 'dev-only/simulation-weighting/ts-alias-hook.mjs')).href);
await import(pathToFileURL(path.join(repo, 'dev-only/simulation-weighting/ts-alias-hook.mjs')));
registerHooks({
  load(url, context, nextLoad) {
    if (url === pathToFileURL(path.join(repo, 'src/lib/university-data.js')).href) {
      return { format: 'module', shortCircuit: true, source: 'export const db = globalThis.__paperReadonlyDatabase;' };
    }
    recordFile(url);
    return nextLoad(url, context);
  },
});
// The backtest library caches Firestore reads in LAB_CACHE_DIR; these checks never call that loader.
process.env.LAB_CACHE_DIR = path.join(process.env.PRIVATE_DIR || path.join(paper, 'dev-only/workspace'), 'unused-cache');
export const lib = await import(pathToFileURL(path.join(repo, 'dev-only/backtest-v3/lib.mjs')));
export const rules = await import(pathToFileURL(path.join(repo, 'dev-only/simulation-weighting/da-rules.mjs')));
export const scoring = await import(pathToFileURL(path.join(repo, 'src/lib/simulation/ast/scoring.ts')));
export const cleaning = await import(pathToFileURL(path.join(repo, 'src/lib/simulation/ast/candidate-cleaning.ts')));
export const { MARGINAL_SUBJECTS } = await import(pathToFileURL(path.join(repo, 'src/lib/simulation/ast/weighting.ts')));
export const { calculateScaledQuotas } = await import(pathToFileURL(path.join(repo, 'src/lib/simulation/ast/quota.ts')));
export const databaseSHA256 = sha256(frozen);
const git = args => { try { return execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim(); } catch { return null; } };
/** Provenance of a run: platform commit and uncommitted changes, every loaded platform file, and the runtime. */
export function provenance() {
  return { platformHead: git(['rev-parse', 'HEAD']), platformUncommittedChanges: git(['status', '--porcelain', '--untracked-files=no']),
    loadedPlatformFiles: Object.fromEntries([...loaded].sort()), databaseSHA256: sha256(frozen), node: process.version,
    betterSqlite3: (() => { try { return createRequire(process.env.NODE_MODULES_FROM || path.join(repo, 'package.json'))('better-sqlite3/package.json').version; } catch { return null; } })(),
    platform: `${process.platform} ${process.arch}` };
}
export function closeRuntime() {
  sqlite.close();
  delete globalThis.__paperReadonlyDatabase;
}
