"""TradingAgents Studio：TradingAgents-CN 的独立增强套件。

四个模块：
  digest  —— 长报告提炼成 200 字开盘简报
  notify  —— 飞书/webhook 推送 + cron 定时管道
  compare —— 多模型同题对比，硬指标表格
  replay  —— 智能体辩论过程渲染成单文件 HTML 回放

与原项目零耦合：只通过 HTTP API / 只读数据卷 / 只读 Mongo 集成。
"""
__version__ = "0.1.0"
