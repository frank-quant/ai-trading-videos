# 从零复现

全程约 2 小时,大部分时间在等 Docker 拉镜像和模型跑分析。

---

## 前置

| 要什么 | 哪儿拿 | 备注 |
|---|---|---|
| Docker Desktop | [docker.com](https://www.docker.com/products/docker-desktop/) | Windows 要 WSL2 后端 |
| 智谱 API Key | [open.bigmodel.cn](https://open.bigmodel.cn/) | 注册 → 控制台 → 新建 Key |
| Tushare Token | [tushare.pro](https://tushare.pro/) | 免费额度够跑 |
| ZCode | [智谱官网](https://open.bigmodel.cn/) | 也可以换成别的 Agent 编程工具 |

这个项目要跑 **MongoDB + Redis**,所以必须走 Docker,`pip install` 完是起不来的。

---

## 一、装底座(约 40 分钟,大部分在等镜像)

新建一个空目录,用 ZCode 打开,把 [`prompts/01-install.md`](prompts/01-install.md)
里那三行丢进去。

它会自己读 README、写 `.env`、拉镜像、起服务。中间要什么会问你。

**大概率会卡在登录这一步**——官方给了默认账号密码,但数据库里那条记录不存在。
把报错原样贴给 ZCode,它会去查、定位、调初始化脚本创建管理员。

服务起来之后浏览器打开它给的 Web UI 地址。

## 二、接模型(约 10 分钟)

按 [`prompts/02-add-model.md`](prompts/02-add-model.md) 在界面里配。

三个关键点:
- 厂家 ID 填 **`zhipu`**,不是 `glm`
- 模型名手动加 **`glm-5.3`**(适配器预置到 4.6 为止)
- 如果 `.env` 里已经有 `ZHIPU_API_KEY`,它会**覆盖**界面里填的

## 三、跑一只票(约 10 分钟)

股票分析界面:

- 股票代码:随便一只 A 股,视频里用的 `002594`
- 分析深度:**5 级拉满**
- 分析师团队:**只能选 3 个**(A 股数据源不覆盖社交媒体)
- 模型:选刚加的 `glm-5.3`

点开始,等五六分钟。出来是一份六千多字的报告。

## 四、装 studio(约 3 小时)

把 [`prompts/03-design-studio.md`](prompts/03-design-studio.md) 丢给 ZCode,
先要设计。结构确认之后,按 [`prompts/04-build-modules.md`](prompts/04-build-modules.md)
**一个模块一个 prompt** 地要实现。

顺序建议:`digest` → `notify` → `replay` → `compare`。
notify 依赖 digest 的输出,replay 需要先跑一次分析拿到辩论数据。

---

## 省时间的几个点

**第一次跑通就把完整日志存下来**

```bash
python your_script.py > samples/debug_002594.log 2>&1
```

一次分析是几分钟 + 几万 token。开发 replay 要反复试解析逻辑,
拿这个日志文件当测试数据,别每次重跑。

**开个分支**

```bash
git checkout -b studio
```

后面要看 diff、要提 PR,分支干净很重要。

**studio 放项目外面**

不要把代码散进 `tradingagents/` 里改人家的文件。放独立目录用插件方式挂进去,
原项目才能继续升级,你的东西也才能单独开源。

---

## 卡住的时候

大部分问题直接把报错原样贴给 ZCode 就行,不用自己加解释。视频里那个登录失败
就是这么解决的——只贴报错,它自己翻了几个相关文件,一次定位到。

如果它给的是"请检查您的配置"这类车轱辘话,说明上下文不够,
把相关文件路径一起给它。
