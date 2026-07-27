import numpy as np, pandas as pd, glob
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

f=glob.glob('/freqtrade/user_data/data/binance/futures/ETH_USDT_USDT-30m*.feather')[0]
df=pd.read_feather(f); df['date']=pd.to_datetime(df['date'],utc=True)
df=df[(df['date']>='2024-07-01')&(df['date']<'2026-07-01')].copy()
px=df['close'].values
ema=pd.Series(px).ewm(span=100).mean().values
pos=np.where(px>ema,1,-1)
ret=np.diff(px)/px[:-1]
sig=pos[:-1]*ret - 0.0006*np.abs(np.diff(np.r_[pos]))
n=48
daily=np.array([sig[i:i+n].sum() for i in range(0,len(sig)-n,n)])
r=daily; N=len(r)
def curve(s): return 1000*np.cumprod(1+s)
np.random.seed(7); BLK=10; SIMS=400
fig,ax=plt.subplots(figsize=(11,6.2),dpi=130)
fig.patch.set_facecolor('#0d1117'); ax.set_facecolor('#0d1117')
finals=[]
for _ in range(SIMS):
    idx=[]
    while len(idx)<N:
        s=np.random.randint(0,max(1,N-BLK)); idx+=list(range(s,s+BLK))
    idx=idx[:N]; c=curve(r[np.array(idx)])
    ax.plot(c,color='#3fb6ff',alpha=0.05,lw=0.7); finals.append(c[-1])
orig=curve(r)
ax.plot(orig,color='#ffd24d',lw=2.6,label='actual backtest path',zorder=10)
ax.axhline(1000,color='#888',lw=0.8,ls='--',alpha=0.6)
ax.set_title('Block Bootstrap Monte Carlo - 400 resampled paths',color='#e6edf3',fontsize=13,pad=14)
ax.set_xlabel('trading days',color='#8b949e'); ax.set_ylabel('equity (start 1000)',color='#8b949e')
ax.tick_params(colors='#8b949e')
for sp in ax.spines.values(): sp.set_color('#30363d')
ax.legend(facecolor='#161b22',edgecolor='#30363d',labelcolor='#e6edf3',loc='upper left')
p5,p50,p95=np.percentile(finals,[5,50,95])
ax.text(0.985,0.06,f'final P5={p5:.0f}  P50={p50:.0f}  P95={p95:.0f}',transform=ax.transAxes,ha='right',color='#8b949e',fontsize=10)
plt.tight_layout()
plt.savefig('/freqtrade/user_data/mc_demo.png',facecolor='#0d1117')
print(f'OK P5={p5:.0f} P50={p50:.0f} P95={p95:.0f} orig={orig[-1]:.0f} days={N}')
