# -*- coding: utf-8 -*-
"""⑤ 横向比较的图（14 个模型并排）。

跟 arena_chart / card / figure 同一套皮，2560×1440。
判据照 EP004：比大小 / 看差距 / 看关系 → 图；查数值 / 多指标对照 → 表。

产出：
    F50_样本外盈利曲线.png     14 个模型日频净值 + 20 币等权大盘（动图跑完的完整状态）
    F50_样本外盈利曲线.gif     184 帧 / 40ms，1280×720，预览用
    F50_序列帧/               184 张 2560×1440，剪辑用，25fps = 7.4 秒
    F51_自主选择.png          四宫格：搜索轮数 / 周期 / 策略家族 / 取不取 argmax
    F58_瀑布图.png            alpha / beta / 实际收益，Fable 5 与 Qwen 并排
    F59_多空贡献.png          14 个模型的多头一侧 vs 空头一侧
    F52_alpha_beta.png        ⭐ 四象限散点，这一段最该看懂的一张
    F53_剔除强平.png          哑铃图：含强平 → 剔强平，14 个模型
    F54_预测力森林图.png       六个揭盲前指标的 r 与 95% CI，零轴竖线
    F55_蒙卡回收.png          蒙卡盈利概率（对数轴）× 最终名次，1% 分界线
    F56_DSR失灵.png           DSR × 样本外夏普，标出最高两条和最低那条
    F57_同模型两次.png         两次跑的对照 + 前四名挤在 0.37 里的对比带
"""
import io
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch
from matplotlib.lines import Line2D

from arena_chart import (BG, BAR, GOLD, INK, GREY, GRID, SERIF, SANS, MONO,
                         FIGW, FIGH, DPI, LOGO_DIR, LOGO_FILE, _place)
from figure import _frame, _save, GREEN, RED
from cross_data import load, equity_curve, periods, MARKET_TOTAL

MKT = '#C2410C'          # 大盘线专用色
OUT = os.path.join('D:', os.sep, 'quant-videos', 'EP007_六模型横测第二季',
                   '07_cover', 'cards', '50_横向比较')
SRC = 'SOURCE: EP007 · 14 MODELS · SAME EXAM (MD5-IDENTICAL) · FRANK-QUANT'
R = load()
BY = {r['short']: r for r in R}


def _panel(ax, x0, y0, x1, y1):
    """在总画布上开一块子区，返回 (转换函数 fx, fy)。"""
    def fx(t):
        return x0 + (x1 - x0) * t

    def fy(t):
        return y0 + (y1 - y0) * t
    return fx, fy


def _fam(s):
    """含中文走黑体，纯数字/英文走等宽。"""
    return SANS if any('\u4e00' <= c <= '\u9fff' for c in str(s)) else MONO


def _logo(ax, fig, vendor, x, y, h, align=(0.5, 0.5)):
    lf = LOGO_FILE.get(vendor)
    if lf:
        _place(ax, fig, os.path.join(LOGO_DIR, lf + '.png'), x, y, h, align=align)


# ============================================================
# F50 · 14 个模型日频净值 + 大盘（静图 + 动图）
# ============================================================
def _daily():
    """读预算好的逐日盯市权益；大盘取回测归档里的 20 币等权收盘均价。"""
    import numpy as np
    import zipfile
    import pandas as pd
    p = os.path.join('D:', os.sep, 'freqtrade_demo', 'EP007_env',
                     '_scorecard', 'daily_equity.npz')
    z = np.load(p, allow_pickle=True)
    days = [str(x) for x in z['days']]
    curves = {r['short']: z['e_' + r['tag']] for r in R}
    # 大盘：Freqtrade 在回测时自己写的 market_change.feather
    zp = os.path.join(R[0]['root'], 'verified', 'test.zip')
    with zipfile.ZipFile(zp) as f:
        n = [x for x in f.namelist() if x.endswith('market_change.feather')][0]
        d = pd.read_feather(io.BytesIO(f.read(n)))
    m = d.set_index(pd.DatetimeIndex(d['date']).strftime('%Y-%m-%d'))['mean']
    m = (m / m.iloc[0] - 1) * 100
    mkt = m.reindex(days).ffill().bfill().values
    return days, curves, mkt


def net_curves(animate=False):
    import numpy as np
    days, curves, mkt = _daily()
    n = len(days)
    lo = min(min(float(c.min()) for c in curves.values()), float(mkt.min())) - 4
    hi = max(max(float(c.max()) for c in curves.values()), float(mkt.max())) + 5

    L, Rt, B, T = 0.072, 0.688, 0.175, 0.735

    def draw(upto):
        fig, ax = _frame(
            '样本外测试集盈利曲线',
            note='NOTE: DAILY MARK-TO-MARKET EQUITY · SAME OLS INPUT AS alpha/beta',
            source=SRC)

        def X(i):
            return L + (Rt - L) * i / (n - 1)

        def Y(v):
            return B + (T - B) * (v - lo) / (hi - lo)

        for v in range(int(lo // 10) * 10, int(hi) + 10, 10):
            if lo <= v <= hi:
                ax.plot([L, Rt], [Y(v), Y(v)], color=GRID, lw=0.8, zorder=1)
                ax.text(L - 0.010, Y(v), '%d%%' % v, ha='right', va='center',
                        fontsize=13, fontname=MONO, color=GREY)
        ax.add_patch(Rectangle((L, B), Rt - L, Y(0) - B, fc=RED, alpha=.045,
                               ec='none', zorder=0))
        ax.plot([L, Rt], [Y(0), Y(0)], color=INK, lw=2.0, alpha=.8, zorder=3)

        # x 轴：每两个月一格
        for i, d in enumerate(days):
            if d.endswith('-01') and int(d[5:7]) % 2 == 1:
                ax.plot([X(i), X(i)], [B, B + 0.008], color=GREY, lw=1.0)
                ax.text(X(i), B - 0.030, d[2:7], ha='center', va='center',
                        fontsize=12, fontname=MONO, color=GREY)

        k = min(upto, n - 1)
        xs = [X(i) for i in range(k + 1)]
        # 大盘（虚线，画在最底层）
        ax.plot(xs, [Y(v) for v in mkt[:k + 1]], color=MKT, lw=3.4,
                solid_capstyle='round', zorder=5)
        for r in R:
            c = curves[r['short']]
            win = c[-1] > 0
            ax.plot(xs, [Y(v) for v in c[:k + 1]], color=GOLD if win else BAR,
                    lw=3.2 if win else 1.5, alpha=1.0 if win else .48,
                    solid_capstyle='round', zorder=6 if win else 4)

        if upto >= n - 1:
            ax.plot([X(n - 1)], [Y(float(mkt[-1]))], 'o', ms=9, color=MKT, zorder=6)
            # 标在曲线中段上方，别去挤右边那列名字
            mi = int(n * 0.62)
            ax.text(X(mi), Y(float(mkt[mi])) - 0.032,
                    '20 币等权大盘　收在 %+.1f%%' % mkt[-1],
                    ha='center', va='top', fontsize=16, fontname=SANS,
                    color=MKT, fontweight='bold')
            end = sorted(R, key=lambda r: -float(curves[r['short']][-1]))
            step = (T - B) / len(end)
            for j2, r in enumerate(end):
                yy = T - step * (j2 + 0.5)
                v = float(curves[r['short']][-1])
                win = v > 0
                ax.plot([Rt + 0.006, Rt + 0.030], [Y(v), yy], color=GREY,
                        lw=0.8, alpha=.45, zorder=3)
                _logo(ax, fig, r['vendor'], Rt + 0.040, yy, 0.030)
                ax.text(Rt + 0.062, yy, r['short'], ha='left', va='center',
                        fontsize=13.5, fontname=SANS,
                        color=INK if win else '#4A4A4A',
                        fontweight='bold' if win else 'normal')
                ax.text(0.968, yy, '%+.2f%%' % v, ha='right', va='center',
                        fontsize=14.5, fontname=MONO,
                        color=GOLD if win else (RED if v < -20 else '#4A4A4A'),
                        fontweight='bold' if win else 'normal')
        return fig, ax

    if not animate:
        fig, ax = draw(n - 1)
        _save(fig, os.path.join(OUT, 'F50_样本外盈利曲线.png'))
        return

    if animate == 'frames':
        # 2K 序列帧：拖进时间线设 25fps，无损、好调速度
        d = os.path.join(OUT, 'F50_序列帧')
        os.makedirs(d, exist_ok=True)
        for old_f in os.listdir(d):
            if old_f.endswith('.png'):
                os.remove(os.path.join(d, old_f))
        steps = list(range(0, n, 2))
        if steps[-1] != n - 1:
            steps.append(n - 1)
        for i, k in enumerate(steps, 1):
            f, _ = draw(k)
            f.savefig(os.path.join(d, 'F50_%04d.png' % i), facecolor=BG)
            plt.close(f)
            if i % 40 == 0:
                print('   %d / %d' % (i, len(steps)))
        print('-> F50_序列帧/  (%d 张, 2560×1440, 按 25fps 摆 = %.1f 秒)'
              % (len(steps), len(steps) / 25.0))
        return

    from PIL import Image
    steps = list(range(0, n, 2))
    if steps[-1] != n - 1:
        steps.append(n - 1)
    imgs = []
    for k in steps:
        f, _ = draw(k)
        f.canvas.draw()
        w, h = f.canvas.get_width_height()
        imgs.append(Image.frombuffer('RGBA', (w, h), f.canvas.buffer_rgba(),
                                     'raw', 'RGBA', 0, 1)
                    .convert('RGB').resize((1280, 720), Image.LANCZOS))
        plt.close(f)
    dur = [40] * len(imgs)
    dur[-1] = 3000
    imgs[0].save(os.path.join(OUT, 'F50_样本外盈利曲线.gif'), save_all=True,
                 append_images=imgs[1:], duration=dur, loop=0, optimize=True)
    print('-> F50_样本外盈利曲线.gif  (%d 帧, %d ms/帧, 1280×720)'
          % (len(imgs), dur[0]))


# ============================================================
# F58 · 瀑布图：alpha 是本事，beta 是代价（EP004 同款）
# ============================================================
def waterfall():
    fig, ax = _frame(
        '同样是亏，亏的性质不一样',
        title2_hl='一个是仓位押错，', title2_rest=' 一个是选股本身赚了钱',
        note='NOTE: alpha / beta DECOMPOSITION OF OUT-OF-SAMPLE RETURN', source=SRC)

    def one(x0, x1, r, cap):
        items = [('alpha\n（选股本身）', r['alpha_contrib'], GREEN if r['alpha_contrib'] > 0 else RED),
                 ('beta\n（跟大盘的代价）', r['beta_drag'], RED),
                 ('实际收益', r['test_ret'], GOLD)]
        B_, T_ = 0.215, 0.660
        lo, hi = -17, 9

        def Y(v):
            return B_ + (T_ - B_) * (v - lo) / (hi - lo)

        for v in range(-15, 10, 5):
            ax.plot([x0, x1], [Y(v), Y(v)], color=GRID, lw=0.8, zorder=1)
        ax.plot([x0, x1], [Y(0), Y(0)], color=INK, lw=1.8, alpha=.8, zorder=4)
        w = (x1 - x0) / 3.6
        run = 0.0
        for i, (lab, v, col) in enumerate(items):
            cx = x0 + (x1 - x0) * (i + 0.5) / 3
            if i < 2:
                bot, top = run, run + v
                run += v
            else:
                bot, top = 0.0, v
            ax.add_patch(Rectangle((cx - w / 2, Y(min(bot, top))), w,
                                   abs(Y(top) - Y(bot)), fc=col, ec='none', zorder=5))
            thin = abs(Y(top) - Y(bot)) < 0.052
            if thin:
                yy = max(Y(top), Y(bot)) + 0.030
                ax.text(cx, yy, '%+.1f%%' % v, ha='center', va='center',
                        fontsize=21, fontname=MONO, color=col,
                        fontweight='bold', zorder=6)
            else:
                ax.text(cx, (Y(bot) + Y(top)) / 2, '%+.1f%%' % v, ha='center',
                        va='center', fontsize=21, fontname=MONO, color='white',
                        fontweight='bold', zorder=6)
            ax.text(cx, B_ - 0.048, lab.replace('\\n', chr(10)), ha='center', va='top',
                    fontsize=13.5, fontname=SANS, color='#4A4A4A', linespacing=1.5)
            if i < 2:
                ax.plot([cx + w / 2, cx + (x1 - x0) / 3 - w / 2], [Y(run), Y(run)],
                        color=GREY, lw=1.4, ls=':', zorder=4)
        _logo(ax, fig, r['vendor'], x0 + 0.010, T_ + 0.062, 0.042)
        ax.text(x0 + 0.036, T_ + 0.062, r['short'], ha='left', va='center',
                fontsize=19, fontname=SANS, color=INK, fontweight='bold')
        ax.text(x1, T_ + 0.062, cap, ha='right', va='center',
                fontsize=15, fontname=SANS, color='#8A6D00', fontweight='bold')

    for r in R:
        r['alpha_contrib'] = r['alpha_c']
        r['beta_drag'] = r['beta_d']
    one(0.075, 0.470, BY['Fable 5'], '选股是真本事，仓位押错了方向')
    one(0.560, 0.955, BY['Qwen3.8-Max'], '两样都不差，所以它活下来了')
    _save(fig, os.path.join(OUT, 'F58_瀑布图.png'))


# ============================================================
# F59 · 多空两侧各赚了多少（EP004 同款）
# ============================================================
def long_short():
    fig, ax = _frame(
        '多空两侧各赚了多少（大盘 -45%）',
        note='NOTE: PnL BY SIDE · OUT-OF-SAMPLE', source=SRC)

    L, Rt, B, T = 0.230, 0.930, 0.185, 0.690
    rows = sorted(R, key=lambda r: -(r['pnl_short'] / 100.0))
    lo = min(min(r['pnl_long'], r['pnl_short']) for r in rows) / 100.0 - 4
    hi = max(max(r['pnl_long'], r['pnl_short']) for r in rows) / 100.0 + 4

    def X(v):
        return L + (Rt - L) * (v - lo) / (hi - lo)

    for v in range(-35, 20, 5):
        if lo <= v <= hi:
            ax.plot([X(v), X(v)], [B, T], color=GRID, lw=0.8, zorder=1)
            ax.text(X(v), B - 0.032, '%+d%%' % v, ha='center', va='center',
                    fontsize=12.5, fontname=MONO, color=GREY)
    ax.plot([X(0), X(0)], [B, T + 0.014], color=INK, lw=2.2, alpha=.85, zorder=5)

    step = (T - B) / len(rows)
    h = step * 0.34
    for i, r in enumerate(rows):
        yc = T - step * (i + 0.5)
        for v, col, off in [(r['pnl_long'] / 100.0, '#5A6B8C', +h * 0.55),
                            (r['pnl_short'] / 100.0, RED if r['pnl_short'] < 100 else GREEN,
                             -h * 0.55)]:
            ax.add_patch(Rectangle((min(X(0), X(v)), yc + off - h * 0.46),
                                   abs(X(v) - X(0)), h * 0.92,
                                   fc=col, ec='none', zorder=4))
            ax.text(X(v) + (0.008 if v > 0 else -0.008), yc + off, '%+.1f%%' % v,
                    ha='left' if v > 0 else 'right', va='center',
                    fontsize=12, fontname=MONO, color='#3A3A3A')
        _logo(ax, fig, r['vendor'], L - 0.196, yc, 0.030)
        ax.text(L - 0.176, yc, r['short'], ha='left', va='center',
                fontsize=13, fontname=SANS, color='#3A3A3A')

    ax.add_patch(Rectangle((L + 0.020, T + 0.038), 0.022, 0.016,
                           fc='#5A6B8C', ec='none'))
    ax.text(L + 0.050, T + 0.046, '多头一侧', ha='left', va='center',
            fontsize=14, fontname=SANS, color=INK)
    ax.add_patch(Rectangle((L + 0.170, T + 0.038), 0.022, 0.016, fc=GREEN, ec='none'))
    ax.text(L + 0.200, T + 0.046, '空头一侧', ha='left', va='center',
            fontsize=14, fontname=SANS, color=INK)
    bad = [r for r in R if r['pnl_short'] < 100]
    if bad:
        ax.text(Rt, T + 0.046, '空头几乎没赚到钱的：%s' % '、'.join(x['short'] for x in bad),
                ha='right', va='center', fontsize=14, fontname=SANS, color=RED)
    _save(fig, os.path.join(OUT, 'F59_多空贡献.png'))


# ============================================================
# F52 · alpha–beta 四象限
# ============================================================
def alpha_beta():
    fig, ax = _frame(
        '收益归因：alpha 是本事，beta 是运气',
        title2_hl='14 个模型里只有 4 个', title2_rest=' 做出了正的 alpha',
        note='NOTE: OLS OF DAILY MARK-TO-MARKET EQUITY VS 20-COIN BENCHMARK', source=SRC)

    L, Rt, B, T = 0.085, 0.672, 0.180, 0.730
    bx = [r['beta'] for r in R]
    ay = [r['alpha'] for r in R]
    xlo, xhi = -0.02, max(bx) * 1.10
    ylo, yhi = min(ay) - 4, max(ay) + 5

    def X(v):
        return L + (Rt - L) * (v - xlo) / (xhi - xlo)

    def Y(v):
        return B + (T - B) * (v - ylo) / (yhi - ylo)

    # 象限底色：alpha>0 淡绿，alpha<0 淡红
    ax.add_patch(Rectangle((L, Y(0)), Rt - L, T - Y(0), fc=GREEN, alpha=.05, ec='none'))
    ax.add_patch(Rectangle((L, B), Rt - L, Y(0) - B, fc=RED, alpha=.045, ec='none'))
    # 网格
    for v in range(-30, 11, 5):
        if ylo <= v <= yhi:
            ax.plot([L, Rt], [Y(v), Y(v)], color=GRID, lw=0.8, zorder=1)
            ax.text(L - 0.010, Y(v), '%+d%%' % v, ha='right', va='center',
                    fontsize=13, fontname=MONO, color=GREY)
    for v in [0.0, 0.1, 0.2, 0.3, 0.4]:
        if xlo <= v <= xhi:
            ax.plot([X(v), X(v)], [B, T], color=GRID, lw=0.8, zorder=1)
            ax.text(X(v), B - 0.030, '%.1f' % v, ha='center', va='center',
                    fontsize=13, fontname=MONO, color=GREY)
    ax.plot([L, Rt], [Y(0), Y(0)], color=INK, lw=2.0, alpha=.8, zorder=3)

    ax.text(L, T + 0.028, 'alpha 年化（选股本身的超额）', ha='left', va='center',
            fontsize=15, fontname=SANS, color=INK)
    ax.text(Rt, B - 0.062, 'beta（跟着大盘走的程度）→', ha='right', va='center',
            fontsize=15, fontname=SANS, color=INK)

    # 点 + logo
    # 每个模型：(dx, dy, 'l' 标签在点右边 / 'r' 在点左边)
    NUDGE = {
        'Fable 5':            (0.026, 0.000, 'l'),
        'Qwen3.8-Max':        (-0.026, 0.000, 'r'),
        'GPT-5.6 Sol':        (0.024, 0.012, 'l'),
        'GPT-5.6 Terra':      (0.024, 0.000, 'l'),
        'DeepSeek V4 Flash':  (-0.024, 0.000, 'r'),
        'Gemini 3.8 Flash':   (0.024, -0.016, 'l'),
        'GPT-6 Astra':        (-0.026, -0.018, 'r'),
        'GPT-5.6 Luna':       (-0.026, 0.000, 'r'),
        'GLM-5.3':            (0.026, -0.018, 'l'),
        'Grok 4.6':           (0.026, 0.018, 'l'),
        'DeepSeek V4 Pro':    (-0.026, 0.020, 'r'),
        'GLM-5.3-Flash':      (0.026, -0.018, 'l'),
        'Opus 5':             (-0.026, 0.000, 'r'),
        'Kimi K3':            (0.026, 0.000, 'l'),
    }
    for r in R:
        x, y = X(r['beta']), Y(r['alpha'])
        star = r['short'] in ('Fable 5', 'Opus 5', 'Qwen3.8-Max', 'Kimi K3')
        ax.plot([x], [y], 'o', ms=13 if star else 9,
                color=GOLD if star else BAR, mec=INK if star else 'none',
                mew=1.4 if star else 0, zorder=6, alpha=1 if star else .8)
        dx, dy, side = NUDGE.get(r['short'], (0.024, 0.012, 'l'))
        if side == 'l':
            _logo(ax, fig, r['vendor'], x + dx - 0.015, y + dy, 0.026)
            ax.text(x + dx, y + dy, r['short'], ha='left', va='center',
                    fontsize=13.5 if star else 12.5, fontname=SANS,
                    color=INK if star else '#5A5A5A',
                    fontweight='bold' if star else 'normal', zorder=6)
        else:
            _logo(ax, fig, r['vendor'], x + dx + 0.015, y + dy, 0.026)
            ax.text(x + dx, y + dy, r['short'], ha='right', va='center',
                    fontsize=13.5 if star else 12.5, fontname=SANS,
                    color=INK if star else '#5A5A5A',
                    fontweight='bold' if star else 'normal', zorder=6)

    # 右侧四条结论
    cy = 0.700
    for tt, cc, bold in [
            ('右上 · 手艺好，仓位莽', INK, True),
            ('Fable 5　alpha +7.8% 全场最高，', '#4A4A4A', False),
            ('但净敞口 32.7%，被大盘拖到 −7.5%', '#4A4A4A', False),
            ('', INK, False),
            ('左下 · 仓位对了，选股失效', INK, True),
            ('Opus 5　beta 0.029 全场最中性，', '#4A4A4A', False),
            ('alpha −20.1%', '#4A4A4A', False),
            ('', INK, False),
            ('左上 · 两样都不差', INK, True),
            ('Qwen3.8-Max　alpha +5.9% 第二，', '#4A4A4A', False),
            ('beta 0.078 也在低位', '#4A4A4A', False),
            ('', INK, False),
            ('最底下 · 方向是反的', INK, True),
            ('Kimi K3　alpha −29.4% 全场最低', '#4A4A4A', False)]:
        if tt:
            ax.text(0.720, cy, tt, ha='left', va='center',
                    fontsize=16 if bold else 14, fontname=SANS,
                    color=cc, fontweight='bold' if bold else 'normal')
        cy -= 0.036
    _save(fig, os.path.join(OUT, 'F52_alpha_beta.png'))


# ============================================================
# F54 · 六个揭盲前指标的预测力（森林图）
# ============================================================
FOREST = [   # 指标, r, CI 下, CI 上   —— 出处 _scorecard/揭盲前指标的预测力.md
    ('蒙卡盈利概率', +0.633, +0.20, +0.86),
    ('DSR（Deflated Sharpe）', +0.198, -0.33, +0.63),
    ('成本（¥）', +0.139, -0.38, +0.59),
    ('搜索轮数', -0.086, -0.56, +0.43),
    ('valid 夏普', -0.163, -0.61, +0.36),
    ('valid @ 2× 费率夏普', -0.245, -0.66, +0.29),
]


def forest():
    fig, ax = _frame(
        '揭盲前的六个指标，哪个真能预测结果',
        title2_hl='五个的区间横跨零，', title2_rest=' 只有一个不含零',
        note='NOTE: PEARSON r WITH 95% CI', source='SOURCE: EP007 · 16 RUNS (14 MODELS + 2 EXTRA) · FRANK-QUANT')

    L, Rt, B, T = 0.240, 0.900, 0.190, 0.700

    def X(v):
        return L + (Rt - L) * (v + 1) / 2.0

    for v in [-1, -0.5, 0, 0.5, 1]:
        ax.plot([X(v), X(v)], [B - 0.012, T], color=GRID, lw=0.9, zorder=1)
        ax.text(X(v), B - 0.042, '%+.1f' % v if v else '0', ha='center', va='center',
                fontsize=13, fontname=MONO, color=GREY)
    ax.plot([X(0), X(0)], [B - 0.012, T + 0.010], color=INK, lw=2.2, alpha=.85, zorder=4)
    ax.text(X(0), T + 0.034, '零 —— 跨过这个模型就等于「跟没关系区分不开」',
            ha='center', va='center', fontsize=14.5, fontname=SANS, color=INK)

    step = (T - B) / len(FOREST)
    for i, (name, r, lo, hi) in enumerate(FOREST):
        y = T - step * (i + 0.5)
        good = lo > 0 or hi < 0
        col = GREEN if good else '#6B6B6B'
        ax.plot([X(lo), X(hi)], [y, y], color=col, lw=4.5 if good else 3.0,
                alpha=1 if good else .55, solid_capstyle='round', zorder=5)
        for e in (lo, hi):
            ax.plot([X(e), X(e)], [y - 0.014, y + 0.014], color=col,
                    lw=2.4 if good else 1.8, alpha=1 if good else .55, zorder=5)
        ax.plot([X(r)], [y], 'o', ms=13 if good else 9, color=col,
                mec=BG, mew=1.6, zorder=6)
        ax.text(L - 0.020, y, name, ha='right', va='center',
                fontsize=17 if good else 15.5, fontname=SANS,
                color=INK if good else '#4A4A4A',
                fontweight='bold' if good else 'normal')
        ax.text(Rt + 0.020, y, ('r = %+.3f' % r), ha='left', va='center',
                fontsize=13.5, fontname=MONO, color=col)
        if good:
            ax.add_patch(FancyBboxPatch(
                (L - 0.210, y - 0.030), 0.196 + (Rt - L) + 0.006, 0.060,
                boxstyle='round,pad=0.004,rounding_size=0.008',
                fc='none', ec=GREEN, lw=2.0, zorder=3))
    _save(fig, os.path.join(OUT, 'F54_预测力森林图.png'))


# ============================================================
# F51 · 14 个模型的自主选择（取代旧 C12）
# ============================================================
# 策略家族按源码核的：12 条继承脚手架的 CrossSectionalBase，
# Grok 自己从 IStrategy 从头写了横截面，Gemini 写的是逐币趋势跟踪。
# GOAL.md 原文：「The strategy family is entirely your choice」+
#              「OPTIONAL SCAFFOLD (use it or ignore it)」
FAMILY = {'Gemini 3.8 Flash': ('趋势跟踪', True)}      # 其余都是横截面
SCRATCH = {'Grok 4.6', 'Gemini 3.8 Flash'}             # 没用脚手架基类


def _lines():
    """策略代码行数 / design.md 行数。"""
    out = {}
    import json
    rows = json.load(io.open(os.path.join(
        'D:' + os.sep, 'freqtrade_demo', 'EP007_env', '_scorecard',
        'dataset_全量汇总.json'), encoding='utf-8'))['rows']
    cls = {r['模型']: r['策略类'] for r in rows}
    for r in R:
        def nl(p):
            try:
                return len(io.open(p, encoding='utf-8', errors='ignore').read().split(chr(10)))
            except Exception:
                return 0
        out[r['short']] = (nl(os.path.join(r['root'], 'strategies', cls[r['name']] + '.py')),
                           nl(os.path.join(r['root'], 'design.md')))
    return out


def choices():
    LN = _lines()
    fig, ax = _frame('14 个模型的自主选择',
                     note='NOTE: EVERY COLUMN CHOSEN BY THE MODEL, NOT BY ME', source=SRC)

    T, B = 0.700, 0.155
    rows = sorted(R, key=lambda r: -r['rounds'])
    step = (T - B) / len(rows)

    # 列：(表头, 中心 x, 条形起点, 条形终点, 数字右对齐 x, 最大值)
    NAME_X, TF_X, FAM_X, PICK_X = 0.055, 0.243, 0.308, 0.385
    COLS = [('搜索轮数', 0.470, 0.425, 0.510, 0.545, 640),
            ('策略代码', 0.640, 0.598, 0.678, 0.708, 220),
            ('设计文档', 0.800, 0.760, 0.838, 0.868, 350),
            ('样本外笔数', 0.925, 0.878, 0.918, 0.968, 3500)]

    # 表头
    for lab, cx, _b0, _b1, _nx, _mx in COLS:
        ax.text(cx, T + 0.046, lab, ha='center', va='center',
                fontsize=15, fontname=SANS, color=INK, fontweight='bold')
    for lab, cx in [('周期', TF_X), ('策略家族', FAM_X), ('交卷名次', PICK_X)]:
        ax.text(cx, T + 0.046, lab, ha='center', va='center',
                fontsize=15, fontname=SANS, color=INK, fontweight='bold')
    ax.plot([0.030, 0.970], [T + 0.022, T + 0.022], color=INK, lw=1.3, alpha=.55)

    for k, r in enumerate(rows):
        y = T - step * (k + 0.5)
        if k % 2 == 1:
            ax.add_patch(Rectangle((0.030, y - step * 0.46), 0.940, step * 0.92,
                                   fc='#EDEAE1', ec='none', zorder=0))
        _logo(ax, fig, r['vendor'], 0.040, y, 0.030)
        ax.text(0.060, y, r['short'], ha='left', va='center',
                fontsize=13.5, fontname=SANS, color=INK)

        # 周期
        d = r['tf'] == '1d'
        ax.text(TF_X, y, '日线' if d else '4 小时', ha='center', va='center',
                fontsize=13.5, fontname=SANS, color=BAR if d else '#7B8FC7',
                fontweight='bold')
        # 策略家族（自己从头写的加个星号）
        fam, odd = FAMILY.get(r['short'], ('横截面', False))
        mark = fam + ('＊' if r['short'] in SCRATCH else '')
        ax.text(FAM_X, y, mark, ha='center', va='center',
                fontsize=13.5, fontname=SANS,
                color=RED if odd else ('#8A6D00' if r['short'] in SCRATCH else '#4A4A4A'),
                fontweight='bold' if (odd or r['short'] in SCRATCH) else 'normal')
        # 交卷名次
        p = r['pick_rank']
        ax.text(PICK_X, y, '第 %d' % p, ha='center', va='center',
                fontsize=13.5, fontname=SANS,
                color='#8A6D00' if p == 1 else GREEN,
                fontweight='bold' if p > 1 else 'normal')

        vals = [r['rounds'], LN[r['short']][0], LN[r['short']][1], r['n_trades']]
        for (lab, _cx, b0, b1, nx, mx), v in zip(COLS, vals):
            w = (b1 - b0) * min(v / mx, 1.0)
            ax.add_patch(Rectangle((b0, y - step * 0.20), w, step * 0.40,
                                   fc=BAR, alpha=.75, ec='none', zorder=3))
            ax.text(nx, y, '{:,}'.format(v), ha='right', va='center',
                    fontsize=13, fontname=MONO, color=INK)

    ax.text(0.030, 0.100,
            '＊ = 没用脚手架里那个可选的横截面基类，自己从 IStrategy 从头写。'
            '考题原文：策略家族完全由你决定，脚手架用不用随你。',
            ha='left', va='center', fontsize=13.5, fontname=SANS, color='#5B5B5B')
    _save(fig, os.path.join(OUT, 'F51_自主选择.png'))
# ============================================================
# F53 · 剔掉末端强平（哑铃图）
# ============================================================
def force_exit():
    fig, ax = _frame(
        '剔除强平后收益',
        note='NOTE: EXAM-CONVENTION RETURN · force_exit REMOVED', source=SRC)

    L, Rt, B, T = 0.255, 0.930, 0.175, 0.700
    vals = [(r, r['test_ret'], r['ex_force']) for r in R]
    vals.sort(key=lambda x: -x[1])
    lo = min(min(a, b) for _, a, b in vals) - 3
    hi = max(max(a, b) for _, a, b in vals) + 3

    def X(v):
        return L + (Rt - L) * (v - lo) / (hi - lo)

    for v in range(-35, 6, 5):
        if lo <= v <= hi:
            ax.plot([X(v), X(v)], [B, T], color=GRID, lw=0.8, zorder=1)
            ax.text(X(v), B - 0.030, '%d%%' % v, ha='center', va='center',
                    fontsize=12.5, fontname=MONO, color=GREY)
    ax.plot([X(0), X(0)], [B, T + 0.014], color=INK, lw=2.2, alpha=.85, zorder=5)

    step = (T - B) / len(vals)
    for i, (r, a, b) in enumerate(vals):
        y = T - step * (i + 0.5)
        worse = b < a
        ax.plot([X(a), X(b)], [y, y], color='#B0AEA6', lw=2.2, zorder=3)
        ax.plot([X(a)], [y], 'o', ms=9, color=BAR, zorder=6)
        ax.plot([X(b)], [y], 'D', ms=8,
                color=RED if worse else GREEN, zorder=6)
        _logo(ax, fig, r['vendor'], L - 0.165, y, 0.030)
        ax.text(L - 0.146, y, r['short'], ha='left', va='center',
                fontsize=13, fontname=SANS, color='#3A3A3A')
        if r['short'] == 'Qwen3.8-Max':
            ax.add_patch(FancyBboxPatch(
                (X(min(a, b)) - 0.016, y - 0.020), abs(X(a) - X(b)) + 0.032, 0.040,
                boxstyle='round,pad=0.003,rounding_size=0.006',
                fc='none', ec=GOLD, lw=2.2, zorder=7))
            ax.text(X(min(a, b)) - 0.026, y, '唯一从正翻回负的', ha='right',
                    va='center', fontsize=13.5, fontname=SANS,
                    color='#8A6D00', fontweight='bold')

    # 图例
    ax.plot([L + 0.030], [T + 0.050], 'o', ms=9, color=BAR)
    ax.text(L + 0.046, T + 0.050, '含强平（主榜口径）', ha='left', va='center',
            fontsize=14, fontname=SANS, color=INK)
    ax.plot([L + 0.220], [T + 0.050], 'D', ms=8, color=RED)
    ax.text(L + 0.236, T + 0.050, '剔掉强平', ha='left', va='center',
            fontsize=14, fontname=SANS, color=INK)
    nworse = sum(1 for _, a, b in vals if b < a)
    ax.text(0.030, 0.108, '14 个模型里 %d 个剔掉之后变差 —— 这不是某一家的问题，'
            '全场都在吃这口红利。' % nworse,
            ha='left', va='center', fontsize=14, fontname=SANS, color='#5B5B5B')
    _save(fig, os.path.join(OUT, 'F53_剔除强平.png'))


# ============================================================
# F55 · 蒙卡回收（唯一有预测力的那个指标）
# ============================================================
def mc_recall():
    fig, ax = _frame(
        '开头让你记的那个模型：百分之一',
        title2_hl='最终的后七名，', title2_rest=' 一个不漏全在这个模型以下',
        note='NOTE: BLOCK BOOTSTRAP 5000 ITERS · BLOCK 10', source=SRC)

    import math
    L, Rt, B, T = 0.100, 0.880, 0.185, 0.700

    def X(p):
        v = math.log10(max(p, 0.004))
        return L + (Rt - L) * (v - math.log10(0.004)) / (math.log10(20) - math.log10(0.004))

    def Y(rank):
        return T - (T - B) * (rank - 1) / 13.0

    for p, lab in [(0.01, '0.01%'), (0.1, '0.1%'), (1, '1%'), (10, '10%')]:
        ax.plot([X(p), X(p)], [B, T + 0.010], color=GRID, lw=0.9, zorder=1)
        ax.text(X(p), B - 0.032, lab, ha='center', va='center',
                fontsize=13, fontname=MONO, color=GREY)
    ax.plot([X(1), X(1)], [B - 0.010, T + 0.030], color=RED, lw=2.4, alpha=.8, zorder=4)
    ax.text(X(1), T + 0.052, '1% 分界线', ha='center', va='center',
            fontsize=15, fontname=SANS, color=RED, fontweight='bold')
    # 后七名的横带
    ax.add_patch(Rectangle((L, Y(14) - 0.020), Rt - L, Y(8) - Y(14) + 0.040,
                           fc=GOLD, alpha=.10, ec='none', zorder=0))
    ax.text(Rt - 0.008, Y(8) + 0.026, '最终后七名', ha='right', va='center',
            fontsize=15, fontname=SANS, color='#8A6D00', fontweight='bold')

    for r in R:
        x, y = X(r['mc_prob']), Y(r['rank'])
        odd = r['short'] == 'DeepSeek V4 Flash'
        ax.plot([x], [y], 'o', ms=13 if odd else 10,
                color=GREEN if odd else BAR, mec=INK if odd else 'none',
                mew=1.4 if odd else 0, zorder=6)
        side = -1 if r['mc_prob'] > 1.2 else 1
        _logo(ax, fig, r['vendor'], x + side * 0.020, y, 0.026)
        ax.text(x + side * 0.036, y, r['short'],
                ha='left' if side > 0 else 'right', va='center',
                fontsize=12.5, fontname=SANS, color='#3A3A3A')
    ax.text(L, T + 0.052, '← 蒙卡盈利概率（对数轴）', ha='left', va='center',
            fontsize=14.5, fontname=SANS, color=INK)
    ax.text(L - 0.012, T, '第 1 名', ha='right', va='center',
            fontsize=13, fontname=SANS, color=GREY)
    ax.text(L - 0.012, B, '第 14 名', ha='right', va='center',
            fontsize=13, fontname=SANS, color=GREY)
    ax.text(Rt, B - 0.075,
            '唯一的例外：DeepSeek V4 Flash 蒙卡 0.88%，最终第 5',
            ha='right', va='center', fontsize=14, fontname=SANS, color=GREEN)
    _save(fig, os.path.join(OUT, 'F55_蒙卡回收.png'))


# ============================================================
# F56 · DSR 失灵
# ============================================================
def dsr_fail():
    fig, ax = _frame(
        '专门为过拟合设计的那个指标',
        title2_hl='它排最高的两条，', title2_rest=' 样本外垫底',
        note='NOTE: DEFLATED SHARPE RATIO VS OUT-OF-SAMPLE SHARPE', source=SRC)

    L, Rt, B, T = 0.100, 0.880, 0.190, 0.700
    xs = [r['dsr'] for r in R]
    ys = [r['test_sharpe'] for r in R]

    def X(v):
        return L + (Rt - L) * (v - 0.0) / 1.05

    def Y(v):
        return B + (T - B) * (v - (min(ys) - 0.4)) / ((max(ys) + 0.5) - (min(ys) - 0.4))

    for v in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        ax.plot([X(v), X(v)], [B, T], color=GRID, lw=0.8, zorder=1)
        ax.text(X(v), B - 0.032, '%.1f' % v, ha='center', va='center',
                fontsize=13, fontname=MONO, color=GREY)
    for v in [-4, -3, -2, -1, 0]:
        ax.plot([L, Rt], [Y(v), Y(v)], color=GRID, lw=0.8, zorder=1)
        ax.text(L - 0.012, Y(v), '%+d' % v, ha='right', va='center',
                fontsize=13, fontname=MONO, color=GREY)
    ax.plot([L, Rt], [Y(0), Y(0)], color=INK, lw=2.0, alpha=.85, zorder=4)
    ax.plot([X(0.95), X(0.95)], [B, T], color=RED, lw=2.0, ls=(0, (5, 3)), zorder=4)
    ax.text(X(0.95), T + 0.028, 'DSR ≥ 0.95 判定「统计显著」', ha='right', va='center',
            fontsize=14, fontname=SANS, color=RED)

    STAR = {'Grok 4.6', 'GLM-5.3-Flash', 'GPT-6 Astra'}
    # 中间 0.6~0.9 那一团挤得厉害，逐条指定 (dx, dy, 标签在点的哪一侧)
    NUD = {
        'Qwen3.8-Max':       (-0.022, 0.032, 'r'),
        'GPT-6 Astra':       (0.022, 0.000, 'l'),
        'GPT-5.6 Sol':       (0.022, 0.026, 'l'),
        'GPT-5.6 Terra':     (0.000, -0.034, 'c'),
        'DeepSeek V4 Flash': (0.022, 0.010, 'l'),
        'Fable 5':           (-0.022, 0.000, 'r'),
        'Gemini 3.8 Flash':  (-0.022, 0.000, 'r'),
        'GLM-5.3':           (0.006, 0.032, 'l'),
        'DeepSeek V4 Pro':   (-0.022, 0.000, 'r'),
        'Opus 5':            (0.022, 0.000, 'l'),
        'Grok 4.6':          (-0.022, 0.000, 'r'),
        'GPT-5.6 Luna':      (0.022, 0.000, 'l'),
        'GLM-5.3-Flash':     (-0.022, 0.000, 'r'),
        'Kimi K3':           (0.022, 0.024, 'l'),
    }
    for r in R:
        x, y = X(r['dsr']), Y(r['test_sharpe'])
        st = r['short'] in STAR
        ax.plot([x], [y], 'o', ms=13 if st else 9,
                color=GOLD if st else BAR, mec=INK if st else 'none',
                mew=1.4 if st else 0, zorder=6)
        dx, dy, side = NUD.get(r['short'], (0.022, 0.024, 'l'))
        fs = 13.5 if st else 12.5
        col = INK if st else '#5A5A5A'
        bold = 'bold' if st else 'normal'
        if side == 'l':
            _logo(ax, fig, r['vendor'], x + dx - 0.014, y + dy, 0.026)
            ax.text(x + dx, y + dy, r['short'], ha='left', va='center',
                    fontsize=fs, fontname=SANS, color=col, fontweight=bold, zorder=7)
        elif side == 'r':
            _logo(ax, fig, r['vendor'], x + dx + 0.014, y + dy, 0.026)
            ax.text(x + dx, y + dy, r['short'], ha='right', va='center',
                    fontsize=fs, fontname=SANS, color=col, fontweight=bold, zorder=7)
        else:
            _logo(ax, fig, r['vendor'], x - 0.052, y + dy, 0.026)
            ax.text(x - 0.036, y + dy, r['short'], ha='left', va='center',
                    fontsize=fs, fontname=SANS, color=col, fontweight=bold, zorder=7)
    ax.text(L, T + 0.028, '样本外夏普 ↑', ha='left', va='center',
            fontsize=14.5, fontname=SANS, color=INK)
    ax.text(Rt, B - 0.072, 'DSR（越高＝越「不像是搜出来的」）→',
            ha='right', va='center', fontsize=14.5, fontname=SANS, color=INK)
    ax.text(L, B - 0.072,
            '只能说「没有可检测的预测力」，不能说「负相关」—— 区间横跨零',
            ha='left', va='center', fontsize=13.5, fontname=SANS, color=GREY)
    _save(fig, os.path.join(OUT, 'F56_DSR失灵.png'))


# ============================================================
# F57 · 同一个模型跑两次
# ============================================================
def twice():
    from cross_data import load as _load_all
    ALL = {r['name']: r for r in _load_all(main_only=False)}
    a = ALL['DeepSeek V4 Pro']          # dsh
    b = ALL['DeepSeek V4 Pro@Codex']    # Codex

    fig, ax = _frame(
        '同一个模型，同一张卷子，考两次',
        title2_hl='差了 2.07 个夏普，', title2_rest=' 而榜上每一行只考了一次',
        note='NOTE: SAME MODEL · SAME EXAM · SAME DEFAULT TIER · DIFFERENT harness',
        source=SRC)

    L, Rt, B, T = 0.095, 0.545, 0.205, 0.690
    ys = [x['test_sharpe'] for x in R] + [b['test_sharpe']]
    lo, hi = min(ys) - 0.35, 0.35

    def Y(v):
        return B + (T - B) * (v - lo) / (hi - lo)

    for v in [-4, -3, -2, -1, 0]:
        ax.plot([L, Rt], [Y(v), Y(v)], color=GRID, lw=0.8, zorder=1)
        ax.text(L - 0.012, Y(v), '%+d' % v, ha='right', va='center',
                fontsize=13, fontname=MONO, color=GREY)
    ax.plot([L, Rt], [Y(0), Y(0)], color=INK, lw=2.0, alpha=.85, zorder=4)

    # 逐字稿里那四条：Sol / Terra / DeepSeek V4 Flash / Fable 5
    BAND = ('GPT-5.6 Sol', 'GPT-5.6 Terra', 'DeepSeek V4 Flash', 'Fable 5')
    bv = [x['test_sharpe'] for x in R if x['short'] in BAND]
    t_hi, t_lo = max(bv), min(bv)
    ax.add_patch(Rectangle((L, Y(t_lo)), Rt - L, Y(t_hi) - Y(t_lo),
                           fc=BAR, alpha=.16, ec=BAR, lw=1.2, zorder=2))
    ax.text(Rt - 0.010, Y((t_hi + t_lo) / 2) + 0.030,
            '主榜挨着的 4 个全挤在这条带子里', ha='right', va='center',
            fontsize=14, fontname=SANS, color=BAR, fontweight='bold')
    ax.text(Rt - 0.010, Y((t_hi + t_lo) / 2) - 0.006, '%.2f' % (t_hi - t_lo),
            ha='right', va='center', fontsize=20, fontname=MONO,
            color=BAR, fontweight='bold')

    x1, x2 = L + 0.105, L + 0.290
    for x, r, lab, col in [(x1, a, '第一次 · dsh', BAR), (x2, b, '第二次 · Codex', RED)]:
        v = r['test_sharpe']
        ax.plot([x], [Y(v)], 'o', ms=17, color=col, mec=BG, mew=2, zorder=7)
        ax.text(x, Y(v) + 0.044, '%+.2f' % v, ha='center', va='center',
                fontsize=23, fontname=MONO, color=col, fontweight='bold')
        ax.text(x, B - 0.036, lab, ha='center', va='center',
                fontsize=15, fontname=SANS, color=INK)
    ax.annotate('', xy=(x2, Y(b['test_sharpe'])), xytext=(x1, Y(a['test_sharpe'])),
                xycoords=ax.transAxes, textcoords=ax.transAxes,
                arrowprops=dict(arrowstyle='-|>', color=RED, lw=2.6,
                                shrinkA=14, shrinkB=14), zorder=6)
    mid = (Y(a['test_sharpe']) + Y(b['test_sharpe'])) / 2
    ax.text((x1 + x2) / 2 + 0.024, mid, '2.07', ha='left', va='center',
            fontsize=27, fontname=MONO, color=RED, fontweight='bold')
    _logo(ax, fig, 'DeepSeek', L + 0.020, T + 0.048, 0.046)
    ax.text(L + 0.048, T + 0.048, 'DeepSeek V4 Pro', ha='left', va='center',
            fontsize=18, fontname=SANS, color=INK, fontweight='bold')

    # ---- 右侧三列对照 ----
    CX = (0.615, 0.795, 0.960)          # 项 / 第一次 / 第二次
    rows = [('样本外夏普', '−1.40', '−3.47'),
            ('要是进主榜', '第 9 名', '倒数第一'),
            ('策略类', 'CrossSectionalMomentum', 'XSMultiFactor'),
            ('搜索轮数', '400', '196'),
            ('净敞口', '13.9%', '35.0%'),
            ('花费', '¥3.55', '¥2.33')]
    yy = T + 0.048
    ax.text(CX[1], yy, '第一次 · dsh', ha='center', va='center',
            fontsize=15, fontname=SANS, color=INK, fontweight='bold')
    ax.text(CX[2], yy, '第二次 · Codex', ha='right', va='center',
            fontsize=15, fontname=SANS, color=RED, fontweight='bold')
    yy -= 0.030
    ax.plot([CX[0] - 0.010, CX[2]], [yy, yy], color=INK, lw=1.3, alpha=.55)
    for k, c1, c2 in rows:
        yy -= 0.062
        ax.text(CX[0], yy, k, ha='left', va='center',
                fontsize=15, fontname=SANS, color='#4A4A4A')
        small = 0.72 if len(c1) > 14 else 1.0
        ax.text(CX[1], yy, c1, ha='center', va='center',
                fontsize=15 * small, fontname=_fam(c1), color=INK)
        ax.text(CX[2], yy, c2, ha='right', va='center',
                fontsize=15 * small, fontname=_fam(c2), color=RED)
    _save(fig, os.path.join(OUT, 'F57_同模型两次.png'))


# 六轴分数：_scorecard/EP007_综合排名.md（score_radar.py）
SCORE = {
    'Qwen3.8-Max': (7.88, 6.3, 8.0, 10.0, 7.5, 9.0, 6.2),
    'GPT-6 Astra': (7.64, 5.1, 7.3, 10.0, 10.0, 9.5, 2.2),
    'GPT-5.6 Sol': (7.61, 6.5, 7.2, 10.0, 8.5, 8.0, 4.1),
    'GPT-5.6 Terra': (7.37, 6.5, 6.2, 10.0, 8.5, 7.5, 5.7),
    'Fable 5': (6.92, 6.7, 6.1, 10.0, 5.0, 9.0, 2.1),
    'GLM-5.3': (6.89, 5.6, 4.2, 10.0, 8.5, 9.0, 5.9),
    'Opus 5': (6.76, 5.5, 4.2, 10.0, 9.0, 10.0, 0.0),
    'DeepSeek V4 Flash': (6.58, 5.7, 6.1, 10.0, 5.0, 6.0, 9.4),
    'DeepSeek V4 Pro': (6.55, 4.3, 4.2, 10.0, 9.0, 8.0, 7.4),
    'Grok 4.6': (6.42, 5.1, 3.2, 10.0, 8.0, 9.5, 4.6),
    'GLM-5.3-Flash': (6.16, 4.0, 2.4, 10.0, 7.5, 9.5, 10.0),
    'GPT-5.6 Luna': (5.83, 3.7, 3.0, 10.0, 8.0, 7.0, 8.1),
    'Gemini 3.8 Flash': (5.74, 6.8, 5.8, 7.0, 4.0, 5.5, 2.5),
    'Kimi K3': (4.64, 3.9, 0.4, 10.0, 3.0, 9.0, 5.0),
}


def _matrix(out, title, cols, rows_fn, sort_key, note, foot=''):
    """十四行 × N 列的对照矩阵，跟 F51 同一套版式。"""
    fig, ax = _frame(title, note=note, source=SRC)
    T, B = 0.700, 0.155
    rows = sorted(R, key=sort_key)
    step = (T - B) / len(rows)
    for lab, cx, _ha in cols:
        ax.text(cx, T + 0.046, lab, ha='center', va='center',
                fontsize=14.5, fontname=SANS, color=INK, fontweight='bold')
    ax.plot([0.030, 0.970], [T + 0.022, T + 0.022], color=INK, lw=1.3, alpha=.55)
    for k, r in enumerate(rows):
        y = T - step * (k + 0.5)
        if k % 2 == 1:
            ax.add_patch(Rectangle((0.030, y - step * 0.46), 0.940, step * 0.92,
                                   fc='#EDEAE1', ec='none', zorder=0))
        _logo(ax, fig, r['vendor'], 0.040, y, 0.030)
        ax.text(0.060, y, r['short'], ha='left', va='center',
                fontsize=13, fontname=SANS, color=INK)
        for (lab, cx, ha), (txt, col, bold) in zip(cols[1:], rows_fn(r)):
            ax.text(cx, y, txt, ha=ha, va='center',
                    fontsize=13, fontname=_fam(txt), color=col,
                    fontweight='bold' if bold else 'normal')
    if foot:
        ax.text(0.030, 0.100, foot, ha='left', va='center',
                fontsize=13.5, fontname=SANS, color='#5B5B5B')
    _save(fig, out)


# ============================================================
# F52a · 收益归因明细（放在四象限散点之前）
# ============================================================
def attribution_table():
    def cells(r):
        pos = r['alpha'] > 0
        return [
            ('%+.1f%%' % r['alpha'], GREEN if pos else RED, True),
            ('%+.1f pt' % r['alpha_c'], GREEN if r['alpha_c'] > 0 else RED, False),
            ('%.3f' % r['beta'], INK, False),
            ('%.3f' % r['r2'], '#6B6B6B', False),
            ('%+.1f pt' % r['beta_d'], RED, False),
            ('%.1f%%' % r['net_exp'], INK, False),
            ('%+.2f%%' % r['test_ret'], GOLD if r['test_ret'] > 0 else INK,
             r['test_ret'] > 0),
            ('%.0f' % r['final_equity'], GOLD if r['final_equity'] > 10000 else '#6B6B6B',
             r['final_equity'] > 10000),
        ]
    COLS = [('', 0.055, 'left'),
            ('年化 alpha', 0.300, 'center'), ('alpha 贡献', 0.400, 'center'),
            ('beta', 0.487, 'center'), ('R²', 0.560, 'center'),
            ('beta 拖累', 0.648, 'center'), ('净敞口', 0.740, 'center'),
            ('样本外收益', 0.850, 'center'), ('最终权益', 0.955, 'right')]
    _matrix(os.path.join(OUT, 'F52a_归因明细.png'),
            '收益归因 · 14 个模型的明细', COLS, cells,
            lambda r: -r['alpha'],
            note='NOTE: OLS OF DAILY MTM EQUITY VS 20-COIN BENCHMARK · CAPITAL 10000',
            foot='alpha 贡献 + beta 拖累 ≈ 样本外收益。'
                 '同期大盘 −44.95%，14 个模型全部跑赢；但 alpha 为正的只有四条。')


# ============================================================
# F61 · 关键数字速查（全场14 个模型）
# ============================================================
def quickref():
    def cells(r):
        s = SCORE[r['short']]
        return [
            ('%.2f' % s[0], GOLD if s[0] >= 7.6 else INK, s[0] >= 7.6),
            ('%+.2f' % r['test_sharpe'], GOLD if r['test_sharpe'] > 0 else
             (RED if r['test_sharpe'] < -2 else INK), r['test_sharpe'] > 0),
            ('%+.2f%%' % r['test_ret'], GOLD if r['test_ret'] > 0 else INK,
             r['test_ret'] > 0),
            ('%+.2f%%' % r['ex_force'], RED if r['ex_force'] < 0 else GOLD, False),
            ('%.2f%%' % r['test_dd'], INK, False),
            ('%+.1f%%' % r['alpha'], GREEN if r['alpha'] > 0 else RED, r['alpha'] > 0),
            ('%.2f%%' % r['mc_prob'], RED if r['mc_prob'] < 1 else INK,
             r['mc_prob'] < 1),
            ('%.3f' % r['dsr'], '#6B6B6B', False),
            ('%.3f' % r['pvalue'], RED if r['pvalue'] < 0.05 else '#6B6B6B',
             r['pvalue'] < 0.05),
            ('¥%.2f' % r['cost'], INK, False),
            ('¥%.2f' % (r['cost'] / SCORE[r['short']][0]), INK, False),
        ]
    COLS = [('', 0.048, 'left'),
            ('六轴总分', 0.240, 'center'), ('样本外夏普', 0.318, 'center'),
            ('样本外收益', 0.400, 'center'), ('剔强平后', 0.482, 'center'),
            ('最大回撤', 0.558, 'center'), ('年化 alpha', 0.634, 'center'),
            ('蒙卡', 0.702, 'center'), ('DSR', 0.762, 'center'),
            ('p 值', 0.818, 'center'), ('成本', 0.888, 'center'),
            ('每分成本', 0.968, 'right')]
    _matrix(os.path.join(OUT, 'F61_关键数字速查.png'),
            '14 个模型 · 关键数字速查', COLS, cells,
            lambda r: -SCORE[r['short']][0],
            note='NOTE: FULL BOARD · SEE REPO FOR RAW ARTEFACTS',
            foot='按六轴总分排。权重发题前定死：稳健 0.25 ｜ 表现 0.25 ｜ '
                 '无作弊 0.15 ｜ 代码 0.15 ｜ 诚实 0.15 ｜ 性价比 0.05。'
                 '红色 p 值 = 亏损统计显著；红色蒙卡 = 低于 1%。')


# ============================================================
# F60 · 成本象限（价格 × 能力，帕累托前沿）
# ============================================================
def cost_quadrant():
    import math
    pts = [(r, r['cost'], SCORE[r['short']][0]) for r in R]
    # 帕累托前沿：没有任何模型同时更便宜且更高分
    front = [p for p in pts if not any(
        (q[1] <= p[1] and q[2] >= p[2] and (q[1] < p[1] or q[2] > p[2])) for q in pts)]
    front.sort(key=lambda p: p[1])

    fig, ax = _frame(
        '成本评价',
        note='NOTE: COST (LOG) VS 6-AXIS SCORE · PARETO FRONTIER', source=SRC)

    L, Rt, B, T = 0.090, 0.700, 0.190, 0.700
    xlo, xhi = math.log10(0.45), math.log10(560.0)
    ylo, yhi = 4.2, 8.3

    def X(v):
        return L + (Rt - L) * (math.log10(v) - xlo) / (xhi - xlo)

    def Y(v):
        return B + (T - B) * (v - ylo) / (yhi - ylo)

    # 中位数切四象限
    cs = sorted(c for _, c, _ in pts)
    ss = sorted(s for _, _, s in pts)
    mc = (cs[6] + cs[7]) / 2
    ms = (ss[6] + ss[7]) / 2
    ax.add_patch(Rectangle((L, Y(ms)), X(mc) - L, T - Y(ms),
                           fc=GREEN, alpha=.07, ec='none', zorder=0))
    ax.add_patch(Rectangle((X(mc), B), Rt - X(mc), Y(ms) - B,
                           fc=RED, alpha=.05, ec='none', zorder=0))
    ax.plot([X(mc), X(mc)], [B, T], color=GREY, lw=1.1, ls=(0, (5, 4)), zorder=2)
    ax.plot([L, Rt], [Y(ms), Y(ms)], color=GREY, lw=1.1, ls=(0, (5, 4)), zorder=2)
    ax.text(L + 0.010, T - 0.022, '便宜又好', ha='left', va='center',
            fontsize=15, fontname=SANS, color=GREEN, fontweight='bold')
    ax.text(Rt - 0.010, T - 0.022, '好，但贵', ha='right', va='center',
            fontsize=15, fontname=SANS, color='#6B6B6B')
    ax.text(L + 0.010, B + 0.022, '便宜，但弱', ha='left', va='center',
            fontsize=15, fontname=SANS, color='#6B6B6B')
    ax.text(Rt - 0.010, B + 0.022, '又贵又弱', ha='right', va='center',
            fontsize=15, fontname=SANS, color=RED, fontweight='bold')

    # 刻度
    for v in [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500]:
        ax.plot([X(v), X(v)], [B, T], color=GRID, lw=0.7, zorder=1)
        ax.text(X(v), B - 0.032, ('¥%g' % v), ha='center', va='center',
                fontsize=12.5, fontname=MONO, color=GREY)
    for v in [5, 6, 7, 8]:
        ax.plot([L, Rt], [Y(v), Y(v)], color=GRID, lw=0.7, zorder=1)
        ax.text(L - 0.012, Y(v), '%d' % v, ha='right', va='center',
                fontsize=13, fontname=MONO, color=GREY)

    ax.plot([X(p[1]) for p in front], [Y(p[2]) for p in front],
            color=GOLD, lw=3.0, alpha=.85, zorder=3, solid_capstyle='round')

    NUD = {'Qwen3.8-Max': (0.026, 0.020, 'l'), 'GPT-6 Astra': (0.024, 0.022, 'l'),
           'GPT-5.6 Sol': (-0.024, -0.024, 'r'), 'GPT-5.6 Terra': (-0.024, 0.020, 'r'),
           'Fable 5': (-0.024, 0.020, 'r'), 'GLM-5.3': (-0.024, 0.022, 'r'),
           'Opus 5': (-0.024, 0.022, 'r'), 'DeepSeek V4 Flash': (0.024, 0.022, 'l'),
           'DeepSeek V4 Pro': (0.024, -0.024, 'l'), 'Grok 4.6': (0.024, -0.022, 'l'),
           'GLM-5.3-Flash': (0.024, 0.022, 'l'), 'GPT-5.6 Luna': (-0.024, -0.024, 'r'),
           'Gemini 3.8 Flash': (-0.024, -0.024, 'r'), 'Kimi K3': (0.024, 0.022, 'l')}
    fr = {p[0]['short'] for p in front}
    for r, c, s in pts:
        x, y = X(c), Y(s)
        on = r['short'] in fr
        ax.plot([x], [y], 'o', ms=14 if on else 9,
                color=GOLD if on else BAR, mec=INK if on else 'none',
                mew=1.5 if on else 0, zorder=6)
        dx, dy, side = NUD.get(r['short'], (0.024, 0.020, 'l'))
        if side == 'l':
            _logo(ax, fig, r['vendor'], x + dx - 0.014, y + dy, 0.026)
            ax.text(x + dx, y + dy, r['short'], ha='left', va='center',
                    fontsize=13 if on else 12, fontname=SANS,
                    color=INK if on else '#5A5A5A',
                    fontweight='bold' if on else 'normal', zorder=7)
        else:
            _logo(ax, fig, r['vendor'], x + dx + 0.014, y + dy, 0.026)
            ax.text(x + dx, y + dy, r['short'], ha='right', va='center',
                    fontsize=13 if on else 12, fontname=SANS,
                    color=INK if on else '#5A5A5A',
                    fontweight='bold' if on else 'normal', zorder=7)

    ax.text(L, T + 0.030, '六轴总分 ↑', ha='left', va='center',
            fontsize=15, fontname=SANS, color=INK)
    ax.text(Rt, B - 0.070, '这一次跑完的花费（对数轴）→', ha='right', va='center',
            fontsize=15, fontname=SANS, color=INK)

    # 右栏
    cy = 0.690
    lines = [('金色 = 帕累托前沿', GOLD, True),
             ('没有任何一个模型同时比它', '#4A4A4A', False),
             ('更便宜、而且分更高', '#4A4A4A', False),
             ('', INK, False),
             ('前沿上的 %d 个：' % len(front), INK, True)]
    for p in sorted(front, key=lambda p: -p[2]):
        lines.append(('　%s　¥%.2f　%.2f 分' % (p[0]['short'], p[1], p[2]),
                      '#4A4A4A', False))

    for txt, col, bold in lines:
        if txt:
            ax.text(0.730, cy, txt, ha='left', va='center',
                    fontsize=15 if bold else 13.5, fontname=SANS,
                    color=col, fontweight='bold' if bold else 'normal')
        cy -= 0.034
    _save(fig, os.path.join(OUT, 'F60_成本象限.png'))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    net_curves(animate=False)
    net_curves(animate=True)
    net_curves(animate='frames')
    choices()
    attribution_table()
    alpha_beta()
    force_exit()
    forest()
    mc_recall()
    dsr_fail()
    twice()
    cost_quadrant()
    quickref()
    print('\n输出目录: ' + OUT)
