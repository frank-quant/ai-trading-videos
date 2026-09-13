# 全场「交卷参数 vs valid argmax」对照表

生成 2026-09-06 · 脚本 `argmax_table.py` · 覆盖主榜 13 个模型
（DeepSeek V4 Pro 走 dsh，trials 导出格式不同，不在这张表里）

## 口径

**按参数字典精确匹配**，不靠 sharpe 数值比较 —— `metrics.json` 是在最终回测上重算的，跟 hyperopt trial 分数天然对不上（Qwen3.8 差 0.24），拿 sharpe 比会误判。

判定规则：某 trial 命中 = **它自己的全部搜索键都出现在交卷参数里且取值相同**。这样同时兼容两种情况 —— 参数文件里混入 `optimize=False` 的冻结键（Opus 5 有 3 个），以及一个 trials 列表里混了多个策略族的不同键集（Astra 三族合并）。若无 trial 被完全覆盖（交卷参数是从源码正则抓的 default，会漏掉非数字默认值），降级为「交集最大且交集内全等」，并标注 `(交集N键近似)`。

## 表

```
考场                    策略类                        N     argmax_train  argmax_valid  交卷轮                                   取argmax  参数来源                                                  
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
ft_gemini_3_8_flash   CryptoAlphaTrend           300   +1.1762       0.6896        e6 train+0.9555 valid0.6853 (第23名)    no       CryptoAlphaTrend.json                                 
ft_glm_5_3            XSRiskMom                  400   +0.2461       2.6264        e303 train+1.3349 valid2.5589 (第2名)   no       XSRiskMom.json                                        
ft_gpt_5_6_sol        CausalXSTrend              300   +0.8203       2.2330        e116 train+0.8203 valid2.2330 (第1名)   YES      策略 default（无参数文件）                                     
ft_gpt_6_astra        CausalRelativeMomentum     160   -0.0340       0.5766        e144 train-0.0340 valid0.5766 (第1名)   YES      config.json:strategy_parameters.CausalRelativeMomentum
ft_grok_4_6           XSDonchianMom              80    +1.0982       2.1876        e51 train+1.0982 valid2.1876 (第1名)    YES      XSDonchianMom.json                                    
ft_qwen_3_8_max       XSMomVolDaily              300   +0.2976       2.4891        e231 train+0.2976 valid2.4891 (第1名)   YES      XSMomVolDaily.json                                    
tier_glm_5_3_flash    HybridXSMomentum           597   +0.5157       2.9388        e237 train+0.5157 valid2.9388 (第1名)   YES      策略 default（无参数文件） (交集8键近似)                            
tier_gpt_5_6_luna     CausalMultiFactorXS        120   +0.5337       2.0420        e103 train+0.5337 valid2.0420 (第1名)   YES      CausalMultiFactorXS.json                              
tier_gpt_5_6_terra    BalancedXSTrend            60    +0.8257       1.8094        e1 train+0.8257 valid1.8094 (第1名)     YES      策略 default（无参数文件）                                     
ft_deepseek           DeepSeekMomentumXS         500   +0.6489       2.2457        e408 train+0.6489 valid2.2457 (第1名)   YES      DeepSeekMomentumXS.json                               
ft_fable_5            XSRiskMomentum             300   +0.2987       2.1113        e276 train+0.7896 valid2.0558 (第5名)   no       XSRiskMomentum.json                                   
ft_kimi_k3            KimiK3XSTrend              398   -0.3751       2.6805        e235 train+0.8215 valid1.8650 (第99名)  no       KimiK3XSTrend.json                                    
ft_opus_5             XSTrendEnsemble            300   +0.5989       1.9458        e233 train+0.7517 valid1.7095 (第7名)   no       XSTrendEnsemble.json                                  
```

## 读法

- `取argmax = YES` → 直接把 valid 分数最高的那一轮交上来，没做任何过拟合折价。**表内 8/13 这么干**；表外的 DeepSeek V4 Pro 交卷参数也是 argmax，全场 **9/14**。
- `取argmax = no` → 主动往下挑，通常是为了换更高的 train 分数（train/valid 一致性）。5 个：Gemini 3.8 Flash、GLM-5.3、Fable 5、Kimi K3、Opus 5。
