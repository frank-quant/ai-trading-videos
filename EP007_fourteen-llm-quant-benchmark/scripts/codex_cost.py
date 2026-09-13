# -*- coding: utf-8 -*-
"""从 Codex 会话日志折算成本 —— GPT 三档 + DeepSeek 桥接通用。

Codex（CLI 与 Desktop 写同一份日志）在 ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl 里记：
  turn_context : model / model_provider / reasoning_effort
  event_msg token_count.info.total_token_usage:
      input_tokens(含缓存) / cached_input_tokens / cache_write_input_tokens
      output_tokens(含 reasoning) / reasoning_output_tokens / total_tokens

按 cwd 匹配考场目录，取该会话最后一条 total_token_usage（累计值）。

用法:
  python codex_cost.py --env D:\\freqtrade_demo\\EP007_env\\ft_gpt_5_6_sol
  python codex_cost.py --env ... --model gpt-5.6-terra      # 手动覆盖档位单价
"""
import argparse, glob, json, os, re
from datetime import datetime

# 官网目录价 USD / 百万 token
# cw = 缓存写单价；不给则默认按 1.25× 未命中输入
PRICES = {
    'gpt-5.6-sol':   dict(inp=4.0,  cached=0.40, out=20.0),
    'gpt-5.6-terra': dict(inp=2.0,  cached=0.20, out=12.0),
    'gpt-5.6-luna':  dict(inp=0.20, cached=0.02, out=1.20),
    # GPT-6 Astra（2026-09-04 发布）：缓存写 $12.5 比输入 $10 还贵,不能按 1.25× 估
    'gpt-6-astra':   dict(inp=10.0, cached=1.00, out=50.0, cw=12.5),
    # DeepSeek 桥接走 Codex,单价用人民币另算,这里给占位
    # 官网 USD 目录价（2026-09-06 查证）。DeepSeek 有峰谷两档,这里填低谷价;
    # 峰时翻倍 = inp 1.32 / cached 0.044 / out 3.96。
    # ⚠️ 用哪档记成本是未决口径问题,见操作手册 §0.3 与台账 C6。
    # （Codex 桥接跑次已取消,本条目当前无人使用,保留以防复用。）
    'deepseek-v4-pro': dict(inp=0.66, cached=0.022, out=1.98),
}
FX = 7.2


def sessions_root():
    return os.path.join(os.path.expanduser('~'), '.codex', 'sessions')


def scan(env_path):
    """返回 cwd 命中该考场的会话列表"""
    want = os.path.normcase(os.path.abspath(env_path))
    out = []
    for f in glob.glob(os.path.join(sessions_root(), '**', 'rollout-*.jsonl'), recursive=True):
        meta = model = provider = effort = None
        cwd = None
        last_usage = None
        try:
            with open(f, encoding='utf-8', errors='ignore') as fh:
                for line in fh:
                    if '"session_meta"' in line and cwd is None:
                        m = re.search(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"', line)
                        if m:
                            cwd = m.group(1).encode().decode('unicode_escape')
                        meta = line
                    if '"turn_context"' in line and model is None:
                        mm = re.search(r'"model"\s*:\s*"([^"]+)"', line)
                        mp = re.search(r'"model_provider"\s*:\s*"([^"]+)"', line)
                        me = re.search(r'"reasoning_effort"\s*:\s*"([^"]+)"', line)
                        if mm:
                            model, provider, effort = mm.group(1), (mp.group(1) if mp else None), (me.group(1) if me else None)
                    if 'total_token_usage' in line:
                        j = re.search(r'"total_token_usage"\s*:\s*(\{[^}]*\})', line)
                        if j:
                            last_usage = json.loads(j.group(1))
        except Exception:
            continue
        if cwd and os.path.normcase(os.path.abspath(cwd)) == want and last_usage:
            out.append(dict(file=f, model=model, provider=provider, effort=effort,
                            usage=last_usage, mtime=os.path.getmtime(f)))
    return sorted(out, key=lambda x: x['mtime'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', required=True)
    ap.add_argument('--model', default=None, help='覆盖单价用的模型键')
    ap.add_argument('--fx', type=float, default=FX)
    ap.add_argument('--since', default=None, help='只算这个时间之后的会话, 格式 MM-DD HH:MM')
    ap.add_argument('--only-model', default=None, help='只算该 model 的会话(排除 codex-auto-review 等)')
    a = ap.parse_args()

    ss = scan(a.env)
    if not ss:
        raise SystemExit('没找到 cwd 指向 %s 的 Codex 会话' % a.env)

    if a.since:
        cut = datetime.strptime(str(datetime.now().year) + '-' + a.since, '%Y-%m-%d %H:%M').timestamp()
        ss = [s for s in ss if s['mtime'] >= cut]
    if a.only_model:
        skipped = [s for s in ss if s['model'] != a.only_model]
        for s in skipped:
            print('  [跳过] %s  model=%s  total=%s' %
                  (datetime.fromtimestamp(s['mtime']).strftime('%m-%d %H:%M'),
                   s['model'], f"{s['usage'].get('total_tokens', 0):,}"))
        ss = [s for s in ss if s['model'] == a.only_model]
    if not ss:
        raise SystemExit('筛选后没有会话了')

    tot = dict(input_tokens=0, cached_input_tokens=0, cache_write_input_tokens=0,
               output_tokens=0, reasoning_output_tokens=0, total_tokens=0)
    print('命中 %d 个会话:' % len(ss))
    for s in ss:
        u = s['usage']
        print('  %s  model=%s effort=%s provider=%s  total=%s' %
              (datetime.fromtimestamp(s['mtime']).strftime('%m-%d %H:%M'),
               s['model'], s['effort'], s['provider'], f"{u.get('total_tokens', 0):,}"))
        for k in tot:
            tot[k] += u.get(k, 0)

    key = a.model or ss[-1]['model']
    if key not in PRICES:
        raise SystemExit('没有 %s 的单价，用 --model 指定' % key)
    p = PRICES[key]

    cw_price = p.get('cw', p['inp'] * 1.25)
    uncached = tot['input_tokens'] - tot['cached_input_tokens'] - tot['cache_write_input_tokens']
    cost = (uncached / 1e6 * p['inp'] + tot['cached_input_tokens'] / 1e6 * p['cached']
            + tot['cache_write_input_tokens'] / 1e6 * cw_price
            + tot['output_tokens'] / 1e6 * p['out'])

    print('\n=== 用量合计 ===')
    print('  未命中输入 : %12d  × $%.2f/M' % (uncached, p['inp']))
    print('  缓存命中   : %12d  × $%.2f/M' % (tot['cached_input_tokens'], p['cached']))
    print('  缓存写入   : %12d  × $%.2f/M %s' % (tot['cache_write_input_tokens'], cw_price,
                                             '(官网价)' if 'cw' in p else '(1.25× 输入)'))
    print('  输出       : %12d  × $%.2f/M  (含 reasoning %s)' %
          (tot['output_tokens'], p['out'], f"{tot['reasoning_output_tokens']:,}"))
    print('  合计 token : %12d' % tot['total_tokens'])
    print('  缓存命中率 : %.1f%%' % (100 * tot['cached_input_tokens'] / tot['total_tokens']))
    print('\n  成本: $%.4f = ¥%.2f  (@%.1f)' % (cost, cost * a.fx, a.fx))

    out = dict(model=key, harness='Codex (%s)' % (ss[-1]['provider'] or '?'),
               reasoning_effort=ss[-1]['effort'], env=os.path.basename(a.env),
               tokens=tot, uncached_input_tokens=uncached,
               unit_price_usd_per_M=p, cache_write_multiplier=1.25,
               cache_hit_rate_pct=round(100 * tot['cached_input_tokens'] / tot['total_tokens'], 1),
               cost_usd=round(cost, 4), cost_cny=round(cost * a.fx, 2), fx=a.fx,
               api_calls=None, sessions=len(ss),
               cost_basis='Codex 会话日志 total_token_usage × 官网目录价（等效成本；Plus 订阅无逐笔账单）',
               model_verified='会话日志 turn_context.model = %s，reasoning_effort = %s' % (ss[-1]['model'], ss[-1]['effort']),
               session_files=[os.path.basename(s['file']) for s in ss])
    p2 = os.path.join(a.env, 'verified', 'cost.json')
    os.makedirs(os.path.dirname(p2), exist_ok=True)
    json.dump(out, open(p2, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('\n-> ' + p2)


if __name__ == '__main__':
    main()
