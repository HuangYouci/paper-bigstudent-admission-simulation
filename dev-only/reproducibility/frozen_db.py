"""Load the frozen admission database used by the verification scripts.

The database is read from the platform repository at the commit recorded in data/manifest.json
and checked against its SHA-256. Set BIGSTUDENT_REPOSITORY to the repository directory; the
repository is not public, so readers cannot run the verification scripts.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

PAPER = Path(__file__).resolve().parents[2]


def frozen_database_bytes():
    manifest = json.loads((PAPER / 'data/manifest.json').read_text())
    repository = os.environ.get('BIGSTUDENT_REPOSITORY')
    if not repository:
        raise SystemExit('Set BIGSTUDENT_REPOSITORY to the platform repository; the frozen admission database '
                         f"is read from its commit {manifest['verifiableResearchCommit']}.")
    raw = subprocess.check_output(['git', 'show', manifest['verifiableResearchCommit'] + ':lib/database.db'],
                                  cwd=repository)
    if hashlib.sha256(raw).hexdigest() != manifest['sourceHashes']['lib/database.db']:
        raise ValueError('frozen admission database hash does not match data/manifest.json')
    return raw
