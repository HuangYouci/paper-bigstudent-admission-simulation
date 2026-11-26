"""核對基準公開來源彙總、凍結 DB 與官方學測 15 級分；不讀考生資料。"""
from pathlib import Path
import csv
import hashlib
import json
import sys
import math
import os
import shutil
import sqlite3
import subprocess
from openpyxl import load_workbook

PAPER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from frozen_db import frozen_database_bytes  # noqa: E402
# LibreOffice converts the official XLS files; set SOFFICE to its executable if it is not on PATH.
SOFFICE = os.environ.get('SOFFICE') or shutil.which('soffice') or 'soffice'
SUBJECTS = [('國文', 'gsat_chinese', 'gsat60'), ('英文', 'gsat_english', 'gsat60'),
            ('數學A', 'gsat_mathA', 'gsat60'), ('數學B', 'gsat_mathB', 'gsat60'),
            ('自然', 'gsat_science', 'gsat60'), ('社會', 'gsat_society', 'gsat60'),
            ('數學甲', 'ast_mathA', 'ast'), ('數學乙', 'ast_mathB', 'ast'),
            ('物理', 'ast_physics', 'ast'), ('化學', 'ast_chemistry', 'ast'),
            ('生物', 'ast_biology', 'ast'), ('歷史', 'ast_history', 'ast'),
            ('地理', 'ast_geography', 'ast'), ('公民', 'ast_civics', 'ast')]
LABELS = {label: subject for label, subject, kind in SUBJECTS if kind == 'gsat60'}


def count(value):
    """官方人數僅接受有限非負整數，拒絕布林值。"""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError('官方人數格式不符')
    return int(value)


def parse_gsat(rows):
    """解析官方兩科並排表頭與人數、由低至高累計欄。"""
    output, subjects = {}, None
    for row in rows:
        if str(row[0]).strip() == '級分':
            subjects = [(LABELS[str(row[col]).strip()], col) for col in (1, 7)]
            continue
        level = str(row[0]).strip()
        if not subjects or not level.isdigit() or not 0 <= int(level) <= 15:
            continue
        for subject, col in subjects:
            key = subject, int(level)
            if key in output:
                raise ValueError('官方級分列重複')
            output[key] = count(row[col]), count(row[col + 2])
    if set(output) != {(s, level) for s in LABELS.values() for level in range(16)}:
        raise ValueError('官方六科 16 級分列不完整')
    for subject in LABELS.values():
        cumulative = 0
        for level in range(16):
            people, observed = output[subject, level]
            cumulative += people
            if cumulative != observed:
                raise ValueError('官方累計人數與級分人數不一致')
    return output


def items(row):
    """依既有比較器的科目順序取有限正倍率。"""
    output = []
    for label, subject, kind in SUBJECTS:
        raw = row['採計' + label]
        if raw is None or str(raw).strip() == '':
            continue
        weight = float(raw)
        if not math.isfinite(weight) or weight < 0:
            raise ValueError('採計倍率格式不符')
        if weight > 0:
            output.append(dict(subject=subject, kind=kind, weight=weight))
    return output


def main():
    manifest = json.loads((PAPER / 'data/manifest.json').read_text())
    audit = json.loads((PAPER / 'data/baseline-gsat-margin-audit.json').read_text())
    inputs = json.loads((PAPER / 'data/baseline-inputs.json').read_text())
    raw = frozen_database_bytes()
    db = sqlite3.connect(':memory:')
    db.deserialize(raw)
    db.execute('PRAGMA query_only=ON')
    db.row_factory = sqlite3.Row
    try:
        for key, rows in inputs['distributions'].items():
            year, subject = key.split(':')
            actual = [dict(r) for r in db.execute(
                'SELECT level,people,cum_below FROM score_distribution WHERE D_datayear=? AND subjects=? ORDER BY level',
                (year, subject))]
            if rows != actual:
                raise ValueError('基準分布彙總與凍結 DB 不符')
        for department in inputs['departments']:
            gid = department['gid']
            current = db.execute('SELECT * FROM ast_data WHERE D_datayear=2026 AND dept_group_id=?', (gid,)).fetchall()
            old = db.execute('SELECT * FROM ast_data WHERE D_datayear=2025 AND dept_group_id=?', (gid,)).fetchall()
            if len(current) != 1 or len(old) > 1 or items(current[0]) != department['items']:
                raise ValueError('當年採計彙總不一致或群組鍵重複')
            expected = None
            if old:
                cutoff = float(old[0]['結果分數']) if str(old[0]['結果分數'] or '').strip() else None
                if cutoff is not None and (not math.isfinite(cutoff) or cutoff <= 0):
                    cutoff = None
                expected = dict(cutoff=cutoff, hasSkill=float(old[0]['採計術科'] or 0) > 0, items=items(old[0]))
            if expected != department['prior']:
                raise ValueError('歷年門檻與採計彙總不一致')
        workspace = PAPER / 'dev-only/workspace/gsat15'
        workspace.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        for key in ('TMPDIR', 'TEMP', 'TMP'):
            environment[key] = str(workspace)
        checked = 0
        for year in (2025, 2026):
            academic = year - 1911
            source = PAPER / 'sources/official' / f'{academic}_gsat_score_distribution.xls'
            if hashlib.sha256(source.read_bytes()).hexdigest() != audit['sourceSHA256'][source.name]:
                raise ValueError('官方 XLS 來源雜湊不符')
            target_dir = workspace / str(academic)
            target_dir.mkdir(exist_ok=True)
            target = target_dir / (source.stem + '.xlsx')
            if not target.exists():
                profile = target_dir / 'lo-profile'
                result = subprocess.run([SOFFICE,
                    '-env:UserInstallation=' + profile.as_uri(), '--headless', '--convert-to', 'xlsx',
                    '--outdir', str(target_dir), str(source)], env=environment, capture_output=True, text=True)
                if result.returncode or not target.exists():
                    raise RuntimeError('官方 XLS 轉檔失敗：' + result.stderr[:500])
            book = load_workbook(target, read_only=True, data_only=True)
            try:
                values = parse_gsat(book['22'].iter_rows(max_col=14, values_only=True))
            finally:
                book.close()
            for (subject, level), observed in values.items():
                r = db.execute('SELECT people,cum_below FROM score_distribution WHERE D_datayear=? AND subjects=? AND level=?',
                               (year, subject, level)).fetchone()
                if r is None or tuple(r) != observed:
                    raise ValueError('官方學測 15 級分與凍結 DB 不符')
                checked += 1
        print(json.dumps(dict(departments=len(inputs['departments']),
            distributionRows=sum(map(len, inputs['distributions'].values())), officialCellsChecked=checked,
            mismatches=0), ensure_ascii=False))
    finally:
        db.close()


if __name__ == '__main__':
    main()
