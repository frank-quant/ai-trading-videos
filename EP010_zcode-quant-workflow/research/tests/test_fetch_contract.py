"""Offline checks for data splitting, immutable output and credential requirements."""
from pathlib import Path
import os
import runpy
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

class FetchContract(unittest.TestCase):
    def setUp(self):
        output = ROOT / 'setup_checks'
        output.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='fetch_contract_', dir=output)
        self.root = Path(self.temp.name)
        script = self.root / 'tools/fetch_tushare.py'
        script.parent.mkdir()
        shutil.copyfile(ROOT / 'tools/fetch_tushare.py', script)
        self.module = runpy.run_path(str(script), run_name='fetch_contract')

    def tearDown(self):
        self.temp.cleanup()

    def test_split_and_hash(self):
        frame = pd.DataFrame({'trade_date': ['20241231', '20250102'],
                              'ts_code': ['000001.SZ'] * 2, 'close': [10.0, 11.0]})
        manifest = {'files': {}}
        self.module['finalize_group']('daily', frame, manifest, unit_count=1)
        self.assertEqual(manifest['files']['raw/daily.parquet']['date_max'], '20241231')
        self.assertEqual(manifest['files']['sealed/daily.parquet']['date_min'], '20250102')
        import hashlib
        raw = self.root / 'data/raw/daily.parquet'
        self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(),
                         manifest['files']['raw/daily.parquet']['sha256'])

    def test_refuse_overwrite(self):
        frame = pd.DataFrame({'trade_date': ['20241231'],
                              'ts_code': ['000001.SZ'], 'close': [10.0]})
        manifest = {'files': {}}
        self.module['finalize_group']('daily', frame, manifest, unit_count=1)
        raw = self.root / 'data/raw/daily.parquet'
        original = raw.read_bytes()
        frame['close'] = 12.0
        with self.assertRaises(self.module['StopFetch']):
            self.module['finalize_group']('daily', frame, manifest, unit_count=1)
        self.assertEqual(raw.read_bytes(), original)

    def test_missing_token_stops_before_network(self):
        with patch.dict(os.environ, {'TUSHARE_TOKEN': ''}):
            with self.assertRaises(SystemExit) as result:
                self.module['main']()
        self.assertNotEqual(result.exception.code, 0)

    def test_error_exit_saves_recent_progress(self):
        # An error before the 50-unit checkpoint must still persist completed units.
        for message, expected_calls in [('权限不足', 2), ('每分钟请求频率限制', 2),
                                        ('temporary failure', 4)]:
            with self.subTest(message=message):
                state = {'groups': {g: {'status': 'done'}
                                    for g in self.module['GROUP_ORDER'] if g != 'daily'},
                         'pool': ['000001.SZ', '000002.SZ'], 'flow_dates': ['20241231']}
                calls = []
                def query(api, **params):
                    calls.append(params)
                    if len(calls) == 1:
                        return pd.DataFrame({'trade_date': ['20241231'],
                                             'ts_code': ['000001.SZ'], 'close': [10.0]})
                    raise RuntimeError(message + ' fake-token-for-test')
                fake = types.SimpleNamespace(query=query)
                namespace = self.module['main'].__globals__
                with patch.dict(os.environ, {'TUSHARE_TOKEN': 'fake-token-for-test'}), \
                     patch('tushare.pro_api', return_value=fake), \
                     patch.dict(namespace, {'load_state': lambda: state}), \
                     patch.object(self.module['time'], 'sleep'):
                    with self.assertRaises(self.module['StopFetch']) as error:
                        self.module['main']()
                import json
                saved = json.loads((self.root / 'data/_fetch_state.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['groups']['daily']['done'], ['000001.SZ'])
                self.assertEqual(len(calls), expected_calls)
                self.assertNotIn('fake-token-for-test', str(error.exception))

if __name__ == '__main__':
    unittest.main(verbosity=2)
