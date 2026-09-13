# -*- coding: utf-8 -*-
"""⑤ 横向比较用的数据层：把14 个模型的全量指标拉齐成一张表。

两个考场（EP004_env / EP007_env）的 verified 产物合并读取，
主榜以 `dataset_全量汇总.json` 的「入主榜 == 是」为准。

⚠️ 两套夏普别混：
    console_metrics.json → Sharpe (daily wallet balance)，主榜口径
    seg_*.json           → EP004ValidLoss._sharpe_daily，虚报检查口径
本模块一律用主榜口径（`test_sharpe` / `valid_sharpe`）。
"""
import io, json, os

FT = os.path.join('D:', os.sep, 'freqtrade_demo')
SC = os.path.join(FT, 'EP007_env', '_scorecard')

# 模型 → 厂商（画 logo 用）
VENDOR = {
    'Qwen3.8-Max': '阿里', 'GPT-6 Astra@ultra': 'OpenAI', 'GPT-5.6 Sol': 'OpenAI',
    'GPT-5.6 Terra': 'OpenAI', 'GPT-5.6 Luna': 'OpenAI', 'GPT-5.6 Sol@ultra': 'OpenAI',
    'DeepSeek V4 Flash': 'DeepSeek', 'DeepSeek V4 Pro': 'DeepSeek',
    'DeepSeek V4 Pro@Codex': 'DeepSeek', 'Fable 5': 'Anthropic', 'Opus 5': 'Anthropic',
    'Gemini 3.8 Flash': 'Google', 'GLM-5.3': '智谱', 'GLM-5.3-Flash': '智谱',
    'Grok 4.6': 'xAI', 'Kimi K3': '月之暗面',
}
# 画面上用的短名（14 条并排时全名太长）
SHORT = {
    'Qwen3.8-Max': 'Qwen3.8-Max', 'GPT-6 Astra@ultra': 'GPT-6 Astra',
    'GPT-5.6 Sol': 'GPT-5.6 Sol', 'GPT-5.6 Terra': 'GPT-5.6 Terra',
    'GPT-5.6 Luna': 'GPT-5.6 Luna', 'GPT-5.6 Sol@ultra': 'GPT-5.6 Sol@ultra',
    'DeepSeek V4 Flash': 'DeepSeek V4 Flash', 'DeepSeek V4 Pro': 'DeepSeek V4 Pro',
    'DeepSeek V4 Pro@Codex': 'V4 Pro @ Codex', 'Fable 5': 'Fable 5', 'Opus 5': 'Opus 5',
    'Gemini 3.8 Flash': 'Gemini 3.8 Flash', 'GLM-5.3': 'GLM-5.3',
    'GLM-5.3-Flash': 'GLM-5.3-Flash', 'Grok 4.6': 'Grok 4.6', 'Kimi K3': 'Kimi K3',
}
# 周期 / 搜索轮数 / 取不取 argmax —— 出处：_scorecard/argmax_对照表.md、各家 config
TF = {'Qwen3.8-Max': '1d', 'GPT-6 Astra@ultra': '4h', 'GPT-5.6 Sol': '4h',
      'GPT-5.6 Terra': '4h', 'GPT-5.6 Luna': '4h', 'DeepSeek V4 Flash': '1d',
      'DeepSeek V4 Pro': '1d', 'Fable 5': '4h', 'Opus 5': '4h',
      'Gemini 3.8 Flash': '4h', 'GLM-5.3': '1d', 'GLM-5.3-Flash': '1d',
      'Grok 4.6': '1d', 'Kimi K3': '1d'}
ROUNDS = {'Qwen3.8-Max': 300, 'GPT-6 Astra@ultra': 160, 'GPT-5.6 Sol': 300,
          'GPT-5.6 Terra': 60, 'GPT-5.6 Luna': 120, 'DeepSeek V4 Flash': 500,
          'DeepSeek V4 Pro': 400, 'Fable 5': 300, 'Opus 5': 300,
          'Gemini 3.8 Flash': 300, 'GLM-5.3': 400, 'GLM-5.3-Flash': 597,
          'Grok 4.6': 80, 'Kimi K3': 398}
# 交卷那一轮在自己搜索里的名次（1 = 取了 argmax）
RANK = {'Qwen3.8-Max': 1, 'GPT-6 Astra@ultra': 1, 'GPT-5.6 Sol': 1, 'GPT-5.6 Terra': 1,
        'GPT-5.6 Luna': 1, 'DeepSeek V4 Flash': 1, 'DeepSeek V4 Pro': 1,
        'Grok 4.6': 1, 'GLM-5.3-Flash': 1,
        'Fable 5': 5, 'Opus 5': 7, 'GLM-5.3': 2, 'Gemini 3.8 Flash': 23, 'Kimi K3': 99}


def _load(root, f, sub='verified'):
    p = os.path.join(root, sub, f) if sub else os.path.join(root, f)
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else None


def load(main_only=True):
    """返回 [dict, ...]，按主榜样本外夏普从高到低排序。"""
    rows = json.load(io.open(os.path.join(SC, 'dataset_全量汇总.json'),
                             encoding='utf-8'))['rows']
    out = []
    for r in rows:
        if main_only and r['入主榜'] != '是':
            continue
        tag = r['tag']
        root = None
        for env in ('EP007_env', 'EP004_env'):
            p = os.path.join(FT, env, tag)
            if os.path.isdir(os.path.join(p, 'verified')):
                root = p
                break
        if root is None:
            continue
        m = r['模型']
        c = _load(root, 'console_metrics.json')
        st = _load(root, 'seg_test.json')['metrics']
        ab = _load(root, 'alpha_beta.json')
        mc = _load(root, 'mc.json')
        ds = _load(root, 'dsr.json')
        co = _load(root, 'cost.json')
        sub = _load(root, 'subperiod_M.json')
        out.append(dict(
            name=m, short=SHORT.get(m, m), vendor=VENDOR.get(m), tag=tag, root=root,
            src=r['来源'],
            test_sharpe=c['test']['sharpe'], valid_sharpe=c['valid']['sharpe'],
            test_ret=c['test']['ret'], test_dd=c['test']['dd'],
            pvalue=c['test']['pvalue'],
            alpha=ab['alpha_annual_pct'], beta=ab['beta'], r2=ab['r2'],
            net_exp=ab['net_exposure_pct'], final_equity=ab['final_equity'],
            alpha_c=ab['alpha_contrib_pct'], beta_d=ab['beta_drag_pct'],
            pnl_long=st['pnl_long'], pnl_short=st['pnl_short'],
            mc_prob=mc['prob_profit'] * 100, mc_p50=mc['final_P50'],
            dsr=ds['DSR'], n_trials=ds['n_trials'],
            obs_sharpe=ds['observed_sharpe_annual'],
            luck=ds['expected_max_sharpe_annual_by_luck'],
            cost=co['cost_cny'],
            n_trades=st['n_trades'], n_long=st['n_long'], n_short=st['n_short'],
            turnover=st['turnover_per_year'],
            months=sub['rows'] if sub else [],
            profit_months=r['盈利月'],
            ex_force=r['剔除强平'], force_n=r['强平笔数'], force_pt=r['强平贡献'],
            tf=TF.get(m), rounds=ROUNDS.get(m), pick_rank=RANK.get(m),
        ))
    out.sort(key=lambda x: -x['test_sharpe'])
    for i, x in enumerate(out, 1):
        x['rank'] = i
    return out


MARKET_TOTAL = -44.95   # 20 币等权基准，全窗口口径，出处 verified/alpha_beta.json


def equity_curve(row):
    """逐月累计净值（%）。

    用**考题口径**：日收益 = 当日盈亏 / 固定 10000（台账 B6），
    所以累计就是 ret_pct 直接相加，不复利。
    实测：14 个模型都能精确还原 dataset_全量汇总.json 的「样本外收益」。
    """
    cum, out = 0.0, [('起点', 0.0)]
    for r in row['months']:
        cum += r['ret_pct']
        out.append((r['period'], cum))
    return out


def periods(rows):
    """月份标签序列（14 个模型一致）。"""
    return [r['period'] for r in rows[0]['months']]
