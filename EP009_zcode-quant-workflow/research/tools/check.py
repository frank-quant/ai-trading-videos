"""Run checks in an isolated directory; never add test rows to the research ledger."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--full', action='store_true', help='Also run checks requiring downloaded raw data')
    args = ap.parse_args()
    output = ROOT / 'setup_checks'
    output.mkdir(exist_ok=True)
    if args.full and not (ROOT / 'data/raw/daily.parquet').is_file():
        ap.error('Full audit requires data/raw; download and check data first.')
    env = os.environ.copy()
    env.pop('TUSHARE_TOKEN', None)
    env.pop('EP010_MAX_END', None)
    env['PYTHONUTF8'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    (output / 'tmp').mkdir(exist_ok=True)
    env['TMP'] = str(output / 'tmp')
    env['TEMP'] = str(output / 'tmp')
    for var in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[var] = '1'
    tests = [
        ('download_contract', ['tests/test_fetch_contract.py']),
        ('funnel', ['engine/funnel.py', 'selftest']),
        ('compare', ['engine/compare.py', '--selftest']),
        ('download_help', ['tools/fetch_tushare.py', '--help']),
    ]
    if args.full:
        tests += [('engine', ['engine/selftest.py']), ('sealed', ['tests/sealed_test.py']),
                  ('newspaper', ['tests/newspaper_test.py'])]
    rows = []
    with tempfile.TemporaryDirectory(prefix='sandbox_', dir=output) as folder:
        sandbox = Path(folder)
        for directory in ('engine', 'parts', 'tests', 'strategies/examples'):
            shutil.copytree(ROOT / directory, sandbox / directory,
                            ignore=shutil.ignore_patterns('__pycache__'))
        (sandbox / 'tools').mkdir()
        shutil.copyfile(ROOT / 'tools/fetch_tushare.py', sandbox / 'tools/fetch_tushare.py')
        for directory in ('data/raw', 'data/sealed', 'ledger', 'reports', 'notes'):
            (sandbox / directory).mkdir(parents=True, exist_ok=True)
        if args.full:
            # Tests read raw data only. Copy files so no test can modify the research source.
            for p in (ROOT / 'data/raw').glob('*.parquet'):
                shutil.copyfile(p, sandbox / 'data/raw' / p.name)
        for name, command in tests:
            print(f'Checking {name} ...', flush=True)
            started = time.monotonic()
            with (output / (name + '.log')).open('w', encoding='utf-8') as log:
                result = subprocess.run([sys.executable, '-X', 'utf8', *command], cwd=sandbox,
                                        env=env, stdout=log, stderr=subprocess.STDOUT)
            rows.append({'check': name, 'returncode': result.returncode,
                         'seconds': round(time.monotonic() - started, 2), 'log': name + '.log'})
            print(f'{name}: {"PASS" if result.returncode == 0 else "FAIL"}', flush=True)
            if result.returncode:
                break
    passed = all(r['returncode'] == 0 for r in rows) and len(rows) == len(tests)
    (output / 'check_result.json').write_text(json.dumps({
        'status': 'PASS' if passed else 'FAIL', 'full': args.full,
        'python': sys.version.split()[0], 'checks': rows,
        'scope': 'Engineering checks; not proof of alpha or a substitute for independent audit.'
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if passed else 1

if __name__ == '__main__':
    raise SystemExit(main())
