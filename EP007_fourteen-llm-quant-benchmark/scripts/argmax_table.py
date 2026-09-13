# -*- coding: utf-8 -*-
"""全场「交卷参数 vs valid argmax」对照表 —— 决策质量轴的原始证据"""
import glob, io, json, os, re, sys

ROOT = r'D:\freqtrade_demo\EP007_env'
EP004 = r'D:\freqtrade_demo\EP004_env'


def jload(p):
    return json.load(io.open(p, encoding='utf-8-sig'))


def final_params(env, cls):
    """按优先级找模型交卷时记录的最终参数"""
    # 1) Freqtrade 标准参数文件
    for p in glob.glob(os.path.join(env, 'strategies', '*.json')):
        try:
            o = jload(p)
        except Exception:
            continue
        if o.get('strategy_name') == cls or os.path.basename(p) == cls + '.json':
            return o.get('params', {}).get('buy', {}), os.path.basename(p)
    # 2) config.json 里的各种写法
    try:
        c = jload(os.path.join(env, 'config.json'))
    except Exception:
        return {}, 'config读不到'
    for path in (('strategy_parameters', cls), ('params', 'buy'), ('params', 'strategy'),
                 ('strategy_params',), ('buy_params',)):
        d = c
        for k in path:
            d = d.get(k, {}) if isinstance(d, dict) else {}
        if d:
            return d, 'config.json:' + '.'.join(path)
    # 3) 策略类里的 buy_params 字面量
    f = os.path.join(env, 'strategies', cls + '.py')
    if os.path.exists(f):
        txt = io.open(f, encoding='utf-8', errors='ignore').read()
        m = re.search(r'buy_params\s*(?::[^=]*)?=\s*\{(.*?)\}', txt, re.S)
        if m:
            try:
                return json.loads('{' + m.group(1).replace("'", '"').rstrip().rstrip(',') + '}'), '类内 buy_params'
            except Exception:
                pass
        # 4) Parameter(default=)
        d = {}
        for mm in re.finditer(r'(\w+)\s*=\s*\w*Parameter\(([^\n]*?)default\s*=\s*([\d.]+)', txt):
            v = float(mm.group(3))
            if 'optimize=False' in mm.group(2):
                continue
            d[mm.group(1)] = int(v) if v == int(v) else v
        if d:
            return d, '策略 default（无参数文件）'
    return {}, '找不到'


def eqp(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-6
    except Exception:
        return str(a) == str(b)


def strat_of(env):
    """从 run.md 里抓 --strategy"""
    for f in ('run.md', 'RUN.md'):
        p = os.path.join(env, f)
        if os.path.exists(p):
            t = io.open(p, encoding='utf-8', errors='ignore').read()
            m = re.findall(r'--strategy\s+([A-Za-z_]\w*)', t)
            if m:
                return max(set(m), key=m.count)
    return None


rows = []
envs = sorted(glob.glob(os.path.join(ROOT, 'ft_*')) + glob.glob(os.path.join(ROOT, 'tier_*'))) + \
       sorted(glob.glob(os.path.join(EP004, 'ft_*')))
for env in envs:
    hp = os.path.join(env, 'hyperopt_results.json')
    if not os.path.exists(hp):
        continue
    name = os.path.basename(env)
    try:
        h = jload(hp)
        t = [x for x in h['trials'] if isinstance(x.get('valid_sharpe'), (int, float))]
    except Exception as e:
        rows.append((name, 'hyperopt读失败: %s' % e, '', '', '', '', ''))
        continue
    if not t:
        rows.append((name, '无有效 trial', '', '', '', '', ''))
        continue
    best = max(t, key=lambda x: x['valid_sharpe'])
    cls = strat_of(env)
    p, src = final_params(env, cls) if cls else ({}, '找不到策略名')
    # 逐 trial 按它自己的键集判定：
    #  - 参数文件常含 optimize=False 的冻结键，不在 trial.params 里（Opus 5 有 3 个）
    #  - Astra 把三个策略族的搜索合并进同一个 trials 列表，各族键集不同
    # 所以要求「该 trial 的全部搜索键都在交卷参数里且取值相同」，而不是反过来全键匹配。
    def match(x):
        kt = set(x['params'])
        return kt and kt <= set(p) and all(eqp(x['params'][k], p[k]) for k in kt)

    hit = [x for x in t if p and match(x)]
    if not hit and p:
        # 降级：交卷参数是从策略源码正则抓的 default 时，可能漏掉非数字默认值的键，
        # 于是没有任何 trial 的键集能被完全覆盖。此时取「交集最大且交集内全部相等」的 trial。
        cand = [(len(set(x['params']) & set(p)), x) for x in t
                if all(eqp(x['params'][k], p[k]) for k in set(x['params']) & set(p))]
        cand = [c for c in cand if c[0] >= 2]
        if cand:
            best_n = max(c[0] for c in cand)
            hit = [x for n, x in cand if n == best_n]
            src += ' (交集%d键近似)' % best_n
    rank = sorted(t, key=lambda z: -z['valid_sharpe'])
    if hit:
        x = hit[0]
        pos = next((i + 1 for i, z in enumerate(rank) if z['epoch'] == x['epoch']), None)
        took = 'YES' if abs(x['valid_sharpe'] - best['valid_sharpe']) < 1e-9 else 'no'
        rows.append((name, cls, len(t), '%+.4f' % best['train_sharpe'], '%.4f' % best['valid_sharpe'],
                     'e%d train%+.4f valid%.4f (第%s名)' % (x['epoch'], x['train_sharpe'], x['valid_sharpe'], pos),
                     took, src))
    else:
        rows.append((name, cls, len(t), '%+.4f' % best['train_sharpe'], '%.4f' % best['valid_sharpe'],
                     '未匹配上 %s' % json.dumps(p, ensure_ascii=False)[:60], '?', src))

hdr = ('考场', '策略类', 'N', 'argmax_train', 'argmax_valid', '交卷轮', '取argmax', '参数来源')
w = [max(len(str(r[i])) for r in rows + [hdr]) for i in range(len(hdr))]
line = lambda r: '  '.join(str(r[i]).ljust(w[i]) for i in range(len(hdr)))
print(line(hdr))
print('-' * (sum(w) + 2 * len(w)))
for r in rows:
    print(line(r))
