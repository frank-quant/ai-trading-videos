"""Verify exported hashes and recompute test metrics without raw market data or credentials."""
from pathlib import Path
import csv
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parent
RES = ROOT / 'results'

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def metrics(returns):
    nav = peak = 1.0
    drawdown = 0.0
    for r in returns:
        if not math.isfinite(r):
            raise ValueError('Non-finite return')
        nav *= 1 + r
        peak = max(peak, nav)
        drawdown = min(drawdown, nav / peak - 1)
    return {'cumulative_return': nav - 1, 'annual_return': nav ** (250 / len(returns)) - 1,
            'absolute_max_drawdown': drawdown}

def main():
    manifest = json.loads((ROOT / 'MANIFEST.json').read_text(encoding='utf-8'))
    for rel, expected in manifest['files'].items():
        path = ROOT / rel
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Hash mismatch: {rel}')
    print(f'PASS: {len(manifest["files"])} file hashes')
    expected = json.loads((RES / 'test_metrics.json').read_text(encoding='utf-8'))
    dates = benchmark = None
    for p in sorted((RES / 'test_returns').glob('*.csv')):
        rows = read_csv(p)
        ds = [r['date'] for r in rows]
        br = [float(r['benchmark_ret']) for r in rows]
        if dates is None:
            dates, benchmark = ds, br
        if ds != dates or br != benchmark or len(ds) != 424:
            raise ValueError(f'Date/benchmark mismatch: {p.name}')
        actual = metrics([float(r['strategy_ret']) for r in rows])
        for key, value in actual.items():
            if abs(value - expected['strategies'][p.stem][key]) > 1e-10:
                raise ValueError(f'Metric mismatch: {p.stem}/{key}')
        print(f'PASS: {p.stem}, annual {actual["annual_return"]:.2%}, MDD {actual["absolute_max_drawdown"]:.2%}')
    for key,value in metrics(benchmark).items():
        if abs(value-expected['stock_pool_equal_weight'][key])>1e-10:
            raise ValueError(f'Benchmark mismatch: {key}')
    layers=json.loads((RES/'funnel_layers.json').read_text(encoding='utf-8'))
    counts=read_csv(RES/'funnel_counts.csv')
    for row in counts:
        for column,track in [('A','A'),('B','B'),('monkey_43','MONKEY'),('farm20_total','MS')]:
            if int(row[column]) != len(layers['tracks'][track][row['layer'].lower()]):
                raise ValueError(f'Funnel count mismatch: {row["layer"]}/{column}')
    if any(int(v) for k,v in counts[-1].items() if k!='layer'):
        raise ValueError('Unexpected strict survivor count')
    ledger=read_csv(RES/'ledger.csv')
    provenance=json.loads((RES/'provenance.json').read_text(encoding='utf-8'))
    if len(ledger)!=provenance['ledger_rows']:
        raise ValueError('Ledger row count mismatch')
    latest={}
    for row in ledger:
        latest[(row['group'],row['config'],row['start'],row['end'])]=row
    for group,track in [('A','A'),('B','B'),('monkey_43','MONKEY')]:
        base=[row for row in latest.values() if row['group']==group
              and row['start']=='20140101' and row['end']=='20221231'
              and '__' not in row['config']]
        for n in range(1,5):
            passed={row['config'] for row in base if row['status']=='ok'
                    and all(row.get(f'funnel_l{k}')=='1' for k in range(1,n+1))}
            if passed!=set(layers['tracks'][track][f'l{n}']):
                raise ValueError(f'Ledger/funnel mismatch: {group}/L{n}')
    catalog_count=0
    with (RES/'strategy_catalog.jsonl').open(encoding='utf-8') as f:
        for line in f:
            entry=json.loads(line)
            rel=Path(entry['path'])
            if rel.is_absolute() or '..' in rel.parts or rel.parts[0]!='strategies':
                raise ValueError('Invalid strategy archive path')
            catalog_count+=1
    if catalog_count!=provenance['strategy_catalog_entries']:
        raise ValueError('Strategy archive count mismatch')
    print(f'PASS: funnel counts, strict survivors 0; ledger {len(ledger)} rows')
    print(f'PASS: L1-L4 match ledger; {catalog_count} archived strategy configurations')
    print('No downloads or backtests performed.')

if __name__=='__main__':
    main()
