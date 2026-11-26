/**
 * Runs the platform's frozen divisible-mass function on the synthetic markets written by `platform_exact.py dump`
 * and writes its allocation for `platform_exact.py compare`. Synthetic markets only; no personal data.
 *
 * Usage: BIGSTUDENT_REPOSITORY=... node platform_exact.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { pathToFileURL, fileURLToPath } from 'node:url';

const repo = process.env.BIGSTUDENT_REPOSITORY;
if (!repo) throw new Error('Set BIGSTUDENT_REPOSITORY');
const file = path.join(repo, 'dev-only/simulation-weighting/da-rules.mjs');
const { runFractionalDA } = await import(pathToFileURL(file));
const paper = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const input = JSON.parse(fs.readFileSync(path.join(paper, 'out/platform-exact-markets.json'), 'utf8'));

const markets = [];
for (const m of input.markets) {
  const weights = new Map(m.candidates.map(c => [c.id, c.weight]));
  const eligible = new Map(m.candidates.map(c => [c.id, c.prefs.map(([gid, score], i) => ({ gid, score, rank: i + 1, wishIndex: i }))]));
  const quotas = new Map(Object.entries(m.capacity).map(([d, q]) => [Number(d), q]));
  const ctx = { candidateUids: m.candidates.map(c => c.id), eligibleByUid: eligible, weightOf: uid => weights.get(uid),
    quotaOf: gid => quotas.get(gid) ?? 0, deptIds: [...quotas.keys()],
    compareFor: () => (a, b) => b.weightedScore - a.weightedScore || a.uid - b.uid };
  const out = runFractionalDA(ctx);
  const held = {}, rejected = {};
  for (const [gid, r] of out.results) held[gid] = Object.fromEntries(r.held.map(h => [h.uid, h.mass]));
  for (const [gid, set] of out.rejectScoresByGid) rejected[gid] = [...set];
  markets.push({ label: m.label, index: m.index, held, rejected, events: out.events });
}
const head = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo }).toString().trim();
fs.writeFileSync(path.join(paper, 'out/platform-exact-platform.json'), JSON.stringify({
  function: 'dev-only/simulation-weighting/da-rules.mjs runFractionalDA', platformHead: head,
  daRulesSHA256: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), node: process.version, markets }));
console.log(JSON.stringify({ markets: markets.length, platformHead: head }));
