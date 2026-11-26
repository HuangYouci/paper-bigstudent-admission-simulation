# What a Self-Selected Platform Sample Adds to Historical Admission Cutoffs

Research package for the manuscript *What a Self-Selected Platform Sample Adds to Historical Admission Cutoffs: Simulating Taiwan's 2026 University Allocation* by Youci Huang (黃宥琦), National Cheng Kung University, yc@huangyouci.com.

The package contains the public tier of the department files, public admission data for 2024–2026, the fixed analysis outputs, the dated analysis plans, and the code. From the public tier alone, readers can recompute Table 2 of the manuscript and, on the 1,333 departments of $\mathcal J_2$ whose v3 the public tier releases, the main comparison, the comparison with the production engine, and direction agreement (`public_checks.py`). The controlled tier, which holds every released simulated value of the 1,654 departments with at least five listings and from which every statistic in the manuscript is computed, goes to the editor and the reviewers; with it, the code recomputes Tables 2–6 and Figures 1–2 except their record-level entries, and Supplement S7, S14–S23, S29, S30, S33, S34, and the department-level part of S32. Table 7, Figure 3, the record-level rows of Figure 1, and Supplement S20b, S24–S28, and the record-level part of S32 are drawn from the stored aggregates of checks that ran on the author's computer, on an export that was deleted afterward. The package contains no individual candidate record.

## Contents

| Path | Content |
|---|---|
| `data/department-benchmark.csv` | One row per department (1,706): official 2026 cutoff, multiplier total, the historical baseline, quota, platform listing count, history availability, and the simulated cutoffs that each tier releases (dictionary below) |
| `data/engine-2026.csv` | The production engine's reconstructed 2026 cutoffs (`engine_base` before and `engine_final` after its quota adjustment) and the backtest's complete rule (`august_rule`, `august_rule_engine`, which the public tier withholds where it withholds v3) (Supplement S32) |
| `data/institution-sums.csv`, `data/public-tier.json` | Public tier: sums by institution cluster and overall from which Table 2 can be recomputed, the release rule, the counts released and withheld, and the hashes of both tiers' files (Supplement S3) |
| `data/public-checks.json` | What `public_checks.py` recomputes from the public tier |
| `data/weighting-granularity-departments.csv` | Controlled tier only: v3 cutoffs under the six calibration settings of Supplement Table S16b |
| `data/archived-run-results.json` | Run-level summaries of the eight saved 2026 runs of 5–15 August 2026 (algorithm versions v1–v3), computed without the withheld departments; the runs' department values are not released (below) |
| `data/history-2024.csv`, `data/history-inputs.json`, `data/combination-tables.json` | Public 2024–2026 cutoffs, quotas, subject rules, score distributions, and official cumulative tables by subject combination, used by the checks of Supplement S18, S19, S21, and S23; `relinked_baseline` gives the baseline of the 27 departments that a later archive links to a 2025 predecessor (S23) |
| `data/official-*`, `data/historical-*`, `data/baseline-*` | Checks of the official cutoffs, subject multipliers, admitted counts, and score distributions used, and the inputs of the historical baseline (public sources only); `official-rules-audit.*` is described in Supplement S23 |
| `data/*-results.json`, `data/*-diagnostics.json`, `data/*-checks.json`, `data/practice-baseline.json`, `data/results.md` | Stored reference outputs reported in the manuscript and supplement, including `robustness-checks.json`, `subgroup-checks.json`, `interval-checks.json`, and `decision-checks.json` (Supplement S21–S23) |
| `data/personal-proxy-results.json` | Aggregate counts for the individual comparison (Supplement S20) |
| `data/author-checks.json`, `data/author-stats.json`, `data/bootstrap-summary.json` | Aggregates, at full precision and with provenance records, of the record-level checks of Section 6.5 and Supplement S20b and S24–S28: export reproduction, record update times and changes, reruns of three allocation rules on each saved run's records, half-samples, resampling, the Bayesian bootstrap, the learning curve, calibration alternatives and fit, coverage of score bands, selection bounds and preference tilts, the comparison with the official combination tables and its composition and capture parts, deduplicated grades, placements by score, integer populations, truncated lists, subsamples, and tie-break redraws; the reruns' department values are not released |
| `data/author-checks-round5.json` | Aggregates of the record-level checks added after the fifth simulated review (plan v0.24): whole-person rules compared with divisible mass on the evaluated input (Supplement S11), the recomputed run of 7 August, concentration of retained mass and eligible listers per department (S3), records last updated before the deadline (S25), the paired ratio of the noon rerun's gain to the evaluated run's, and convergence counts (S26) |
| `data/author-checks-round6.json` | Aggregates of the checks added after the sixth simulated review (plan v0.25): the production engine rebuilt and compared, preference lists generated from public information, 2025 quotas, each account's earliest saved list, applicant-level placements by method, the wider tilt grid, self-centered frame and truncation reruns, sampling variances from 40 half-samples with department values, effective sample sizes, and content hashes of the saved runs (Supplement S32) |
| `data/sixth-review.json` | Department-level checks added after the sixth simulated review: common shocks, decision-time weighting, quota-weighted subgroups and coverage, cutpoints, needless caution, encompassing in both directions, Wilson intervals for S20b, margins by level, the plan v0.18 bootstrap result, the gain by size of quota change, display rules, stricter release sets, filling status, REML heterogeneity, partial pooling, departments without history, and year shifts (Table 5, Supplement S32) |
| `data/platform-exact.json`, `data/platform-exact-platform.json` | The platform's divisible-mass function against an exact rational-arithmetic textbook procedure on 480 synthetic markets (Supplement S17), and the platform function's stored output on those markets, so that `platform_exact.py compare` can be rerun without the platform repository |
| `data/revision-checks.json` | Tails, robust slopes, gains without single departments, decision value (pinball loss, CRPS, risk margins), errors by region, level and sector, interval coverage by group, and level shifts (Supplement S29–S30) |
| `data/seventh-review.json` | Department-level checks added after the seventh simulated review: the quota-adjusted history, the gains of Tables 5 and 6 against three history-based predictions from joint resamples with simultaneous intervals and shares, transport to the 2024–2025 mix of changes, the common shift by group, decision-time weighting with earlier runs, detection on the same departments, and multiplicity (Supplement S33–S34) |
| `data/suppression.json` | Disclosure rule and hashes of the released files (below) |
| `data/manifest.json` | Run identifier, calibration diagnostics, and hashes of the department file, the analysis plans, and the platform modules |
| `dev-only/review/analysis-plan-*.md` | Dated analysis plans (in Chinese); the v0.18 and v0.22 plans were executed in November 2026 (Supplement S15, S24) |
| `dev-only/reproducibility/` | Analysis, verification, and plotting code, with unit tests |
| `figures/` | Figures 1–3 of the manuscript (`overview`, `demand`, `timeline`), the five-method ablation chart, and the difference between v3 and the baseline by number of listings (`coverage`); Figure 3 and the record-level rows of Figure 1 are drawn from the stored record-level aggregates |

## Disclosure control

A simulated cutoff is an order statistic: every v1, v2 and Fractional cutoff, and the 146 v3 cutoffs that interpolation leaves unchanged, equal the weighted score of one platform record. The department files are therefore released in two tiers (Supplement S3). The controlled tier withholds the simulated values and the simulated filling status of the 52 departments with fewer than five platform listings, rounds every other simulated value to two decimals, and leaves out the department values of the earlier saved runs; every statistic in the manuscript is computed from it, and it goes to the editor and the reviewers only. The public tier, which the public repository holds, is written from it by `make_public_tier.py`: it withholds every v1, v2, and Fractional value and the alternative calibrations, releases v3 only at the 1,384 departments that meet the platform's own display rule (at least 18 eligible listings) and whose v3 differs from Fractional, so that no public value equals one record's weighted score, and adds institution-level sums for Table 2. Statistics on sets that include withheld values, such as the 1,521 departments of $\mathcal J_2$, are published as aggregates. Because a full-precision statistic on a small set, or on a set with one withheld department, can be solved for that department's v3, `redact_public_outputs.py` rounds the stored analysis outputs of the public tier to two decimal places and suppresses cells that report fewer than ten departments; the controlled tier keeps them at full precision, and Figure 2B plots only departments whose v3 is public. Differencing the rounded aggregates against the public files can still narrow some withheld v3 values to within a few tenths of a grade. Statistics over records are released only for cells of at least ten records. `compare_outputs.py` confirms that rerunning the scripts on the controlled tier reproduces every stored output.

## Reproducing the results

The analysis scripts need Python 3.10 or later and only the standard library. They write to `out/`, leaving the stored reference outputs in `data/` untouched:

```sh
python3 dev-only/reproducibility/public_checks.py         # Public tier only: Table 2 and the main comparisons on the public departments
python3 dev-only/reproducibility/analyze.py               # Controlled tier from here on: Table 2, the difference by listings, Tables S14c-S14d (about 1 min)
python3 dev-only/reproducibility/demand_signal.py         # Primary outcome (Table 3, first row), Table 4, Figure 2 (about 3 min)
python3 dev-only/reproducibility/granularity_and_bias.py  # Tables S16b-S16c, biases by level (S30g)
python3 dev-only/reproducibility/exploratory_checks.py    # Supplement S18 (about 2 min)
python3 dev-only/reproducibility/history_checks.py        # Rivals of Section 6.3, Supplement S18-S19 (about 4 min)
python3 dev-only/reproducibility/practice_baseline.py     # Exact-table conversions (S18)
python3 dev-only/reproducibility/reference_allocation.py  # Separate re-implementation of Section 4: the example of Section 4.3 and synthetic markets (S17)
python3 dev-only/reproducibility/subgroup_checks.py       # Detection and combination by track, level and sector (S21)
python3 dev-only/reproducibility/interval_checks.py       # Prediction intervals and event probabilities (Section 6.2, S22)
python3 dev-only/reproducibility/robustness_checks.py     # Rule changes, weights, permutation reference, rivals, transitory bounds (S19, S21)
python3 dev-only/reproducibility/decision_checks.py       # Table 3, flags, stratum weights, linkage, filling status (S16, S22, S23)
python3 dev-only/reproducibility/revision_checks.py       # Tails, robust slopes, decision value, region and level, contrasts, support, specifications (S22, S29, S30; about 3 min)
python3 dev-only/reproducibility/sixth_review.py          # Department-level checks of the sixth review (S32)
python3 dev-only/reproducibility/seventh_review.py        # Tables 5-6 against three history-based predictions, S33, S34 (about 1 min)
python3 dev-only/reproducibility/seventh_tables.py        # Tables 5-6 and S33-S34 as markdown, from the stored outputs
python3 dev-only/reproducibility/author_tables.py         # Table 7 and the tables of S20b, S22a, S24-S30 from the stored aggregates
python3 dev-only/reproducibility/s32_tables.py           # Supplement S32 from the stored aggregates
python3 dev-only/reproducibility/compare_outputs.py       # Differences between out/ and the stored data/
```

The figures and the tests need further packages:

```sh
pip install reportlab rlPyCairo openpyxl pdfplumber
python3 dev-only/reproducibility/make_figures.py          # Figures, written to out/figures/
python3 -m unittest discover -s dev-only/reproducibility -p 'test_*.py'
```

Each analysis script checks the SHA-256 of the department file against `data/manifest.json` and, on the public tier, stops with a message if it needs withheld values; the tests run the checks that each tier supports. `make_public_tier.py --out DIR` writes the public tier from the controlled one, and `redact_public_outputs.py DIR/data` then coarsens its stored analysis outputs. `reproduce_baseline.py` rebuilds the historical baseline from public aggregates with zero error.

Some steps cannot be rerun by readers. `prepare_history.py` extracted the public 2024–2026 data from the platform's archive of official data; `verify_official_rules.py` read the official 2026 outcome table, which is not redistributed; `suppress_small_cells.py` produced the released files from the full ones; `archived_run_summary.py` summarized the saved runs from their unreleased department values. `author_checks_round6.mjs` and `author_round6_stats.py` (plan v0.25) rebuilt the production engine with the platform's functions and reran the simulation on the pseudonymized export; they wrote only the aggregates of `data/author-checks-round6.json`, and the engine's department values are released in `data/engine-2026.csv`. The verification scripts (`verify_*.py`) read the frozen admission database from the platform repository (set `BIGSTUDENT_REPOSITORY`) and the official source files, which are not redistributed, and need LibreOffice (set `SOFFICE` if it is not on `PATH`). The Node scripts (`replay.mjs`, `weighting-granularity.mjs`, `market-diagnostics.mjs`, `archived_runs.mjs`, `run-personal-proxy.mjs`, `inspect_runs.mjs`) regenerate candidate-level simulations. They are included for transparency but need the platform repository, whose module hashes they check against `data/manifest.json`, and read access to the platform database through Google application-default credentials. `stress.mjs`, `stress-diagnostics.mjs`, `platform_exact.mjs`, and the `*.test.mjs` files use only synthetic markets but import the allocation code from the platform repository; `platform_exact.py dump` writes the markets and `platform_exact.py compare` checks the platform's output against the exact procedure. `export_runs.mjs` wrote the pseudonymized export of the saved inputs, and `run_timestamps.mjs` (not yet run) reads, read-only and without any field, the server-assigned creation and update times of the saved runs' documents; `author_runtime.mjs` (which records the hash of every loaded platform file), `author_checks.mjs`, `author_checks_extra.mjs`, `author_checks_round5.mjs`, `author_stats.py`, and `author_round5_stats.py` produced the record-level aggregates from it on the author's computer, and `merge_author_outputs.py` merged them into the released files (Supplement S24). They need that export, which was deleted after the analyses, as well as the platform repository. The department-level predictions themselves, the diagnostic columns of Table S16b, the full-market audit and mass ledger of Section 6.1, and Supplement S5, S13, and S16a come from these non-public steps.

## Data dictionary for `data/department-benchmark.csv`

| Column | Meaning |
|---|---|
| `gid` | Department identifier, stable across years (`dept_group_id`) |
| `school`, `department` | Institution and department names (Chinese) |
| `actual` | Official 2026 ordinary-admission cutoff $C_j^*$ (weighted total) |
| `weightTotal` | Multiplier total $B_j$ |
| `v1`, `v2`, `fractional`, `v3` | Simulated cutoffs of the four simulation versions, rounded to two decimals; blank when missing or withheld (the public tier leaves `v1`, `v2`, and `fractional` blank everywhere, and `v3`, `archived_v3`, and `quota_status` blank where the display rule fails or v3 equals Fractional) |
| `baseline` | Historical baseline $\widehat C^{\mathrm H}_j$; blank when no usable 2025 cutoff |
| `unchangedWeights` | Subjects and multipliers unchanged between 2025 and 2026 |
| `archived_v3` | The platform's saved two-decimal v3 value; blank when missing or withheld |
| `official_quota` | Official 2026 quota $q_j$ |
| `applicant_count` | Platform listings $L_j$ (records listing the department) |
| `confidence` | Platform label: `normal` with at least 18 eligible listings (records whose screening standards, English listening requirement, and weighted subjects allow the department), otherwise `insufficient` |
| `quota_status` | The simulation's filling status: `filled` (retained mass equals the quota), `underfilled` (positive retained mass below the quota), or `no_assigned_candidate` (no retained mass); blank when withheld |
| `prior_record_count`, `prior_positive_cutoff_count`, `prior_2025_positive_cutoff`, `no_history_in_snapshot` | History availability in the frozen archive for 2024–2025 |

Errors in the manuscript are $(\widehat C_j-C_j^*)/B_j$, in weighted-average grades. Section 4.7 defines the combination of v3 and the baseline at $\lambda=0.4$ and the departures $D_j$ and $S_j$. Error statistics use the controlled tier, so the 52 departments withheld there enter coverage counts but no error statistic.

## Data protection

Candidate records are stored in the platform's cloud database. The scripts that read them did so read-only and did not read contact details or authentication tokens. The replay and granularity scripts held examination grades, ordered preferences, stored simulation results, and duplicate markers only in memory and wrote or printed only department-level outputs and aggregates. For the record-level checks, the author exported the inputs of the eight saved runs once, with account identifiers replaced by keyed hashes; because grades, preferences, and update times are close to unique, the export was treated as personal data, kept and analyzed on the author's computer, and deleted with its intermediate files after the analyses (Supplement S24). Only aggregates left that computer; the AI assistants that ran the scripts worked under the author's account, so this separation was procedural rather than technical. In `data/market-diagnostics.json`, subject-participation patterns with fewer than five records are merged into one group; department values are released only as described above. Individual records are not released. Section 3.4 of the manuscript describes the basis for research use.

## Sources

Official cutoffs, quotas, subject rules, score distributions and combination tables come from the University Admissions Committee (www.uac.edu.tw) and the College Entrance Examination Center (www.ceec.edu.tw); full citations are in the manuscript. These third-party official data are redistributed in extract for verification only.

## License

Data and documentation: CC BY 4.0 (`LICENSE-DATA`), except the third-party official data noted above. Code: MIT (`LICENSE`).
