# 02 · 接入 GLM-5.3

**视频 05:14** · 这一步在 Web UI 里点,不用写代码。

## 配置管理 → 厂家管理 → 添加自定义厂家

| 字段 | 填什么 |
|---|---|
| 厂家唯一标识 | `zhipu` |
| 显示名称 | 智谱 AI(随便填,只是界面显示) |
| Base URL | `https://open.bigmodel.cn/api/paas/v4` |
| API Key | 提前在 [BigModel 平台](https://open.bigmodel.cn/) 注册好、新建的 key |

## 🔴 厂家 ID 必须填 `zhipu`,不能填 `glm`

枚举里两个都有,但**只有 `zhipu` 在适配器表里注册了**:

```python
# tradingagents/llm_adapters/openai_compatible_base.py
"zhipu": {
    "adapter_class": ChatZhipuOpenAI,
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key_env": "ZHIPU_API_KEY",
}
```

这张表里没有 `glm` 这一项。填 `glm` 的话,`config_service.py` 里有映射能把 key 认出来,
但创建 LLM 实例时查不到适配器,会挂。

## 大模型配置 → 添加模型

适配器里预置的模型只到 `glm-4.6`,**没有 5.3**,所以得手动加:

- 模型名:`glm-5.3`
- 深度思考模型:勾上

加完点测试,能连上就行。

## ⚠️ `.env` 优先级高于数据库

```python
# app/core/config_bridge.py
# 🔧 [优先级] .env 文件 > 数据库厂家配置
```

如果 `.env` 里已经有 `ZHIPU_API_KEY` 而且不是 `your_xxx` 占位符,
**Web UI 里填的 key 会被它覆盖**。

症状是:界面显示配好了、测试也过,但跑分析时报错。看后端日志:

```
✓ 使用 .env 文件中的 ZHIPU_API_KEY (长度: xx)      ← 用的是 .env
✓ 使用数据库厂家配置的 ZHIPU_API_KEY (长度: xx)    ← 用的是界面填的
```

一眼就知道生效的是哪个。
