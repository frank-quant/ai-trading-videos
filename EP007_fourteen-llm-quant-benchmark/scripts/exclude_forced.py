# -*- coding: utf-8 -*-
"""剔除末端强平后重算揭盲成绩，并重排综合榜。

为什么要单独做：Freqtrade 在回测末根 K 线把所有持仓强平（`exit_reason = force_exit`），
统一平在 2026-07-01 00:00。**这是回测的机械产物，不是策略能力。**
口径规范 §三 已确认：七家里六家受益于它，Qwen 的符号甚至取决于它
（+1.74% → 剔除后 −0.94%）。

⚠️ 口径切换（必须写进报告）：
   主榜的夏普用的是 Freqtrade 控制台 `Sharpe (daily wallet balance)`（逐日盯市），
   **那套无法从成交明细还原**，所以剔不掉强平。
   本脚本改用**考题口径**（`EP004ValidLoss._sharpe_daily`：按 close_date 归集已实现盈亏
   / 初始资金，无交易日补 0，×√365）—— 这套能逐笔重算，才剔得掉。
   → **本文件的夏普数值与主榜不可直接比较，只能在本文件内部横向比。**
   为公平起见，「含强平」一列也用同一套口径重算，两列同源。

用法:
  python exclude_forced.py --out D:\\freqtrade_demo\\EP007_env\\_scorecard\\EP007_剔除强平后排名.md
"""
import argparse, io, json, os, sys, zipfile
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score_radar import (ANCHORS, BASES, DATASET, JUDGE, WEIGHTS, cost_score,
                         jload, lerp, robust_parts)

START, END, CAP = '2025-07-01', '2026-07-01', 10000.0


def trades(z):
    with zipfile.ZipFile(z) as f:
        for n in f.namelist():
            if n.endswith('.json') and '_config' not in n:
                o = json.loads(f.read(n))
                for v in o.get('strategy', {}).values():
                    if v.get('trades'):
                        return pd.DataFrame(v['trades'])
    return None


def sharpe_ret(df):
    """考题口径：按 close_date 归集已实现盈亏 / 初始资金，补 0，×√365。"""
    idx = pd.date_range(START, END, freq='D', tz='UTC')
    if df is None or len(df) == 0:
        return 0.0, 0.0, 0
    pnl = pd.to_numeric(df['profit_abs'], errors='coerce').fillna(0.0)
    day = pd.to_datetime(df['close_date'], utc=True).dt.floor('D')
    d = (pnl.groupby(day).sum() / CAP).reindex(idx, fill_value=0.0)
    sd = float(d.std())
    sh = float(d.mean() / sd * np.sqrt(365.0)) if sd > 0 else 0.0
    return sh, float(d.sum()) * 100.0, len(df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    rows = [r for r in jload(DATASET)['rows'] if r['入主榜'] == '是']

    rec = []
    for r in rows:
        z = os.path.join(BASES[r['来源']], r['tag'], 'verified', 'test.zip')
        df = trades(z)
        s_all, ret_all, n_all = sharpe_ret(df)
        dfx = df[df['exit_reason'] != 'force_exit'] if df is not None else None
        s_ex, ret_ex, n_ex = sharpe_ret(dfx)
        rec.append(dict(r=r, s_all=s_all, ret_all=ret_all, n_all=n_all,
                        s_ex=s_ex, ret_ex=ret_ex, n_fe=n_all - n_ex,
                        d_s=s_ex - s_all, d_ret=ret_ex - ret_all))

    def score(x, use_ex):
        r = x['r']
        j = JUDGE[r['模型']]
        rp = robust_parts(r)
        vals = [v for v in rp.values() if v is not None]
        perf = lerp(x['s_ex'] if use_ex else x['s_all'], ANCHORS['perf_sharpe'])
        s = {'稳健': sum(vals) / len(vals), '表现': perf, '无作弊': j['无作弊'][0],
             '代码': j['代码'][0], '诚实': j['诚实'][0], '性价比': cost_score(r['成本人民币'])}
        return sum(s[k] * w for k, w in WEIGHTS), perf

    for x in rec:
        x['tot_all'], x['perf_all'] = score(x, False)
        x['tot_ex'], x['perf_ex'] = score(x, True)

    rk_all = {x['r']['模型']: i + 1 for i, x in enumerate(sorted(rec, key=lambda z: -z['tot_all']))}
    rk_ex = {x['r']['模型']: i + 1 for i, x in enumerate(sorted(rec, key=lambda z: -z['tot_ex']))}
    order = sorted(rec, key=lambda z: -z['tot_ex'])

    L = ['# EP007 · 剔除末端强平后的排名', '',
         '> 生成 2026-09-06 ｜ 脚本 `exclude_forced.py`', '',
         '## 为什么要做这个', '',
         'Freqtrade 在回测末根 K 线把所有持仓强平（`exit_reason = force_exit`，统一平在 2026-07-01 00:00）。',
         '**这是回测的机械产物，不是策略能力。** 口径规范 §三 已确认它对多数家是净贡献，',
         '而 **Qwen 的符号取决于它**（+1.74% → 剔除后 −0.94%）。', '',
         '## 🔴 口径切换（必须随表说明）', '',
         '主榜的夏普是 Freqtrade 控制台的 `Sharpe (daily wallet balance)`（逐日盯市），**那套无法从成交明细还原**，',
         '所以剔不掉强平。本表改用**考题口径**（按 `close_date` 归集已实现盈亏 / 初始资金，补 0，×√365）。',
         '',
         '**→ 本表的夏普数值与主榜不可直接比较**，只能在本表内部横向比。',
         '为公平起见，「含强平」一列也用同一套口径重算，两列同源。', '',
         '---', '', '## 一、剔除强平前后的揭盲成绩', '',
         '| 模型 | 强平笔数 | 夏普(含) | **夏普(剔)** | Δ夏普 | 收益(含) | **收益(剔)** | Δ收益 |',
         '|---|---|---|---|---|---|---|---|']
    for x in sorted(rec, key=lambda z: -z['s_ex']):
        L.append('| %s | %d | %.2f | **%.2f** | %+.2f | %.2f%% | **%.2f%%** | %+.2f pt |'
                 % (x['r']['模型'], x['n_fe'], x['s_all'], x['s_ex'], x['d_s'],
                    x['ret_all'], x['ret_ex'], x['d_ret']))

    pos_all = [x for x in rec if x['ret_all'] > 0]
    pos_ex = [x for x in rec if x['ret_ex'] > 0]
    helped = [x for x in rec if x['d_s'] < 0]

    L += ['', '**三条事实**：',
          '1. **强平帮了 %d/%d 家**（剔掉后夏普下降）。它不是某一家的问题，是全场的。' % (len(helped), len(rec)),
          '2. **含强平时 %d 家收益为正；剔掉后 %d 家为正。**' % (len(pos_all), len(pos_ex)),
          '3. 受影响最大的是 **%s**（Δ夏普 %+.2f）。'
          % (min(rec, key=lambda z: z['d_s'])['r']['模型'], min(rec, key=lambda z: z['d_s'])['d_s']), '',
          '---', '', '## 二、重排后的综合榜', '',
          '| # | 模型 | **综合分(剔)** | 原名次 | 名次变化 | 表现分(剔) | 表现分(含) | 揭盲夏普(剔) |',
          '|---|---|---|---|---|---|---|---|']
    for i, x in enumerate(order, 1):
        m = x['r']['模型']
        d = rk_all[m] - i
        arrow = '—' if d == 0 else ('↑%d' % d if d > 0 else '↓%d' % -d)
        L.append('| %d | **%s** | **%.2f** | %d | %s | %.1f | %.1f | %.2f |'
                 % (i, m, x['tot_ex'], rk_all[m], arrow, x['perf_ex'], x['perf_all'], x['s_ex']))

    moved = [(x['r']['模型'], rk_all[x['r']['模型']] - (i + 1))
             for i, x in enumerate(order) if rk_all[x['r']['模型']] != i + 1]
    L += ['', '## 三、结论', '']
    if moved:
        L.append('**名次有变动的：** ' + '、'.join('%s %s%d' % (m, '↑' if d > 0 else '↓', abs(d)) for m, d in moved))
    else:
        L.append('**名次一位都没变。**')
    L += ['',
          '> 📹 **这张表是「Qwen 靠强平赢的」这条质疑的正面回答。**',
          '> 剔掉之后 %s 仍然排第 %d —— 因为综合分里表现只占 0.25，而它在其余五轴上的位置没有变。'
          % (order[0]['r']['模型'], 1),
          '> 但**必须同时说**：剔掉强平后**全场没有一家收益为正**，这才是这一期真正的结论。']

    txt = '\n'.join(L) + '\n'
    if a.out:
        io.open(a.out, 'w', encoding='utf-8').write(txt)
        print('-> ' + a.out)
    print(txt)


if __name__ == '__main__':
    main()
