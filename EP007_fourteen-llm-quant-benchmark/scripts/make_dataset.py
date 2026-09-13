# -*- coding: utf-8 -*-
"""把所有考场的分析产物合并成一张总表（JSON + CSV）。

之前 dataset_七家汇总 是手搓的；每进一条线就得手改，容易漏。这个脚本从各考场
verified\\ 下的 JSON 产物重新生成，进新线只要重跑一次。

数据来源（全部是已落盘的产物，本脚本不重算任何指标）：
  console_metrics.json  三段夏普/收益 —— **主排名口径**（回测控制台 daily wallet balance）
  alpha_beta.json       beta / R² / alpha年化 / beta拖累 / 净敞口
  mc.json               蒙特卡洛 block bootstrap 盈利概率
  subperiod_M.json      逐月盈亏 / 盈利月数 / 最赚月
  dsr.json              Deflated Sharpe（按各家实际搜索轮数罚）
  cost.json             成本
  test.zip              强平笔数与强平贡献（唯一需要读原始成交的一项）

用法:
  python make_dataset.py                      # 写到 _scorecard\\dataset_全量汇总.{json,csv}
  python make_dataset.py --out-dir <目录>
"""
import argparse, glob, io, json, os, zipfile

BASES = [(r'D:\freqtrade_demo\EP007_env', 'EP007'), (r'D:\freqtrade_demo\EP004_env', 'EP004')]
EXCLUDE = {'ft_gpt_5_6'}          # EP004 没用上的空白考场（EP007 的 _template 就是从它克隆的）
SIDELINE = {'ft_qwen_3_6_plus'}   # 误跑成上一代，标注但不入主榜

NAMES = {
    'ft_glm_5_3': 'GLM-5.3', 'tier_glm_5_3_flash': 'GLM-5.3-Flash',
    'ft_qwen_3_8_max': 'Qwen3.8-Max', 'ft_qwen_3_6_plus': 'Qwen3.6-Plus(误跑)',
    'ft_grok_4_6': 'Grok 4.6', 'ft_gemini_3_8_flash': 'Gemini 3.8 Flash',
    'ft_gpt_5_6_sol': 'GPT-5.6 Sol', 'tier_gpt_5_6_terra': 'GPT-5.6 Terra',
    'tier_gpt_5_6_luna': 'GPT-5.6 Luna', 'tier_gpt_5_6_sol_max': 'GPT-5.6 Sol@ultra',
    'ft_gpt_6_astra': 'GPT-6 Astra@ultra', 'ft_deepseek_v4_pro': 'DeepSeek V4 Pro', 'ft_deepseek_v4_pro_codex': 'DeepSeek V4 Pro@Codex',
    'ft_deepseek_v4_pro_nodocker': 'DeepSeek V4 Pro(作废·无Docker)',
    # ft_deepseek_v4_pro_codex（Codex 桥接跑次）已取消；空目录留在盘上，无 metrics.json 会自动跳过
    'ft_kimi_k3': 'Kimi K3', 'ft_opus_5': 'Opus 5', 'ft_fable_5': 'Fable 5',
    'ft_deepseek': 'DeepSeek V4 Flash',
}
# 不进主榜的线及原因。
# 主榜比的是「各自默认档」；ultra 两条是刻意开的极限档位组（最新模型 + 最顶思考强度的上限在哪），
# 它们互相对照，不跟默认档那批并列。
OFF_BOARD = {
    'ft_qwen_3_6_plus': '误跑成上一代 qwen3.6-plus',
    'ft_deepseek_v4_pro_nodocker': 'Docker 全程不可用，模型自建 pandas 引擎，未使用 Freqtrade —— 作废重跑（台账 C11）',
    # 注：GPT-6 Astra 也跑在 ultra，但它是该型号在本季的唯一跑次 → 进主榜（带档位注脚）；
    #     Sol@ultra 是 GPT-5.6 Sol 的第二次跑，进榜会把同一模型算两次 → 不进。
    'tier_gpt_5_6_sol_max': '同模型第二次跑（GPT-5.6 Sol 已在榜），档位实验 reasoning_effort=ultra',
    # 同一个模型的第二次跑次（换 harness 的对照实验），进主榜等于把 DeepSeek Pro 算两次
    'ft_deepseek_v4_pro_codex': '诊断跑次：同模型换 Codex harness，用于拆分代际/harness 混淆（台账 B10/B11）',
}


def jload(p):
    return json.load(io.open(p, encoding='utf-8-sig')) if os.path.exists(p) else {}


def forced_exit(zpath):
    """强平笔数与强平贡献(占初始资金 %)"""
    if not os.path.exists(zpath):
        return None, None, None
    with zipfile.ZipFile(zpath) as f:
        for n in f.namelist():
            if n.endswith('.json') and '_config' not in n:
                o = json.loads(f.read(n))
                for v in o.get('strategy', {}).values():
                    tr = v.get('trades')
                    if not tr:
                        continue
                    fe = [t for t in tr if t.get('exit_reason') == 'force_exit']
                    pnl = sum(t.get('profit_abs', 0) for t in fe)
                    return len(fe), round(pnl / 100.0, 2), len(tr)
    return None, None, None


def strat_of(env):
    import re
    p = os.path.join(env, 'run.md')
    if not os.path.exists(p):
        return None
    m = re.findall(r'--strategy\s+([A-Za-z_]\w*)', io.open(p, encoding='utf-8', errors='ignore').read())
    return max(set(m), key=m.count) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=r'D:\freqtrade_demo\EP007_env\_scorecard')
    ap.add_argument('--test-end-month', default='2026-07',
                    help='TEST 窗口终点所在月 —— 该桶只含末端强平那一瞬间，不是月份，从月度统计里剔除')
    a = ap.parse_args()

    out = []
    for base, season in BASES:
        for env in sorted(glob.glob(os.path.join(base, 'ft_*')) + glob.glob(os.path.join(base, 'tier_*'))):
            tag = os.path.basename(env)
            if tag in EXCLUDE or not os.path.isdir(os.path.join(env, 'verified')):
                continue
            v = os.path.join(env, 'verified')
            cm, ab, mc = jload(os.path.join(v, 'console_metrics.json')), \
                         jload(os.path.join(v, 'alpha_beta.json')), jload(os.path.join(v, 'mc.json'))
            sp, co = jload(os.path.join(v, 'subperiod_M.json')), jload(os.path.join(v, 'cost.json'))
            ds = jload(os.path.join(v, 'dsr.json'))
            nfe, fepct, ntr = forced_exit(os.path.join(v, 'test.zip'))
            # ⚠️ subperiod 会多出一个 `2026-07` 桶，它不是月份，是**末端强平的那一瞬间**
            # （TEST 窗口终点 2026-07-01 00:00，所有未平仓在此被 force_exit）。
            # 实测：GLM-5.3 该桶 20 笔 / +102.5，与它的强平笔数 20 / 强平贡献 +1.03 完全吻合。
            # 不剔掉的话「最赚月」会被它顶掉（Kimi K3、Sol@ultra 都中招），
            # 而且 EP004 发布过的「Kimi 盈利月 0/12」会变成 1/13，两季对不上。
            # 这部分盈亏已经由 强平笔数/强平贡献 两列单独报告，不重复计入月度。
            rows = [r for r in sp.get('rows', []) if r.get('period') != a.test_end_month]
            pos = [r for r in rows if r.get('pnl', 0) > 0]
            best = max(rows, key=lambda r: r.get('pnl', 0)) if rows else {}
            ret = ab.get('strategy_total_return_pct')

            out.append(dict(
                模型=NAMES.get(tag, tag), tag=tag, 来源=season, 策略类=strat_of(env),
                入主榜=('否' if tag in OFF_BOARD else '是'), 不入榜原因=OFF_BOARD.get(tag),
                # —— 主排名口径（回测控制台 daily wallet balance）——
                valid夏普=cm.get('valid', {}).get('sharpe'),
                test夏普=cm.get('test', {}).get('sharpe'),
                test索提诺=cm.get('test', {}).get('sortino'),
                test回撤=cm.get('test', {}).get('dd'),
                test_p值=cm.get('test', {}).get('pvalue'),
                valid_2xfee夏普=cm.get('valid_2xfee', {}).get('sharpe'),
                费率未偷改=(None if 'valid_ownfee' not in cm else
                        cm['valid_ownfee'].get('sharpe') == cm.get('valid', {}).get('sharpe')),
                # —— 收益与强平 ——
                样本外收益=ret, 强平笔数=nfe, 强平贡献=fepct,
                剔除强平=(round(ret - fepct, 2) if ret is not None and fepct is not None else None),
                总笔数=ntr,
                # —— 归因 ——
                beta=ab.get('beta'), R2=ab.get('r2'), alpha年化=ab.get('alpha_annual_pct'),
                beta拖累=ab.get('beta_drag_pct'), 净敞口=ab.get('net_exposure_pct'),
                # —— 稳健性 ——
                MC盈利概率=mc.get('prob_profit'),
                DSR=ds.get('DSR'), DSR搜索轮数=ds.get('n_trials'), DSR判定=ds.get('verdict'),
                # —— 逐月 ——
                盈利月=(len(pos) if rows else None), 月数=(len(rows) or None),
                最赚月=best.get('period'), 最赚月贡献=(round(best['pnl'] / 100.0, 2) if best.get('pnl') else None),
                正月合计=(round(sum(r['pnl'] for r in rows if r['pnl'] > 0) / 100.0, 2) if rows else None),
                负月合计=(round(sum(r['pnl'] for r in rows if r['pnl'] <= 0) / 100.0, 2) if rows else None),
                # —— 成本 ——
                成本人民币=co.get('cost_cny'), token总量=(co.get('tokens') or {}).get('total_tokens'),
                harness=co.get('harness'), effort=co.get('reasoning_effort'),
            ))

    out.sort(key=lambda r: -(r['test夏普'] if r['test夏普'] is not None else -99))
    os.makedirs(a.out_dir, exist_ok=True)
    pj = os.path.join(a.out_dir, 'dataset_全量汇总.json')
    json.dump(dict(generated='2026-09-06', n=len(out),
                   note='主排名口径 = 回测控制台 Sharpe (daily wallet balance)；'
                        '强平贡献/月度金额均已按初始资金 10000 折算为百分点；'
                        '月度统计已剔除 TEST 终点 2026-07 那个只含末端强平的伪月桶（12 个月）',
                   rows=out), io.open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    import csv
    pc = os.path.join(a.out_dir, 'dataset_全量汇总.csv')
    with io.open(pc, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    print('%d 条线 -> %s\n            -> %s\n' % (len(out), pj, pc))
    h = ('模型', 'test夏普', '样本外收益', 'beta', '净敞口', 'MC盈利概率', '成本人民币', '入主榜')
    wd = [max(len(str(r.get(k))) for r in out + [dict(zip(h, h))]) for k in h]
    print('  '.join(str(k).ljust(wd[i]) for i, k in enumerate(h)))
    print('-' * (sum(wd) + 2 * len(wd)))
    for r in out:
        print('  '.join(str(r.get(k)).ljust(wd[i]) for i, k in enumerate(h)))


if __name__ == '__main__':
    main()
