# WorldBranch · 安史之乱模拟器

给定真实的历史起点，你替唐廷做决定，看历史怎么分叉。

> 当前状态：**安史之乱切片（天宝十四载 – 广德元年，755–763）已可完整推演**。
> 21 件史实事件、7 处岔路口、17 位人物、8 支军队、真实地理边界，
> 每个结果都能追溯到引擎记录的事实与史料出处。
>
> 完整设计见 [项目总设计文档](docs/WorldBranch_项目总设计文档.md)，
> 数据来源逐项说明见 `python tools/data_provenance.py`。

---

## 这是什么

不是"AI 讲历史的聊天机器人"，也不是"通用世界模拟引擎"。

**是一台可以改写段历史的机器**：史实不是剧本，而是**有前提的条件句**。
前提还在，历史照旧；前提被你改了，历史就在那里分岔，并且记录下来为什么。

举个例子，同一个潼关，三种走法：

| 你的选择 | 结果 |
|---|---|
| 遣使催战（史载） | 潼关失守 → 玄宗奔蜀 → 长安陷落 |
| 令其坚守 | 潼关不失 → 长安不陷，两件史实改道 |
| 哥舒翰提前病故 | 结果同上，但原因不同：**无人可催** |

后两种结局一样、原因不同——这正是"因果经得起推敲"要看的东西。

## 怎么玩

打开页面即进入**天宝十四载十一月**，你扮演唐廷。

侧栏四个分组：

| 分组 | 内容 |
|---|---|
| **决断** | 世界摆到你面前的问题，每个选项写明代价；朝臣会各自进言 |
| **军事** | 各军兵力、主帅、士气与补给、双方总战力 |
| **人物** | 忠诚、野心、统兵数、状态（功高 / 拥兵自重 / 将叛 / 已叛） |
| **史实** | 哪些史实应验了、哪些因你而改道，各带史实年月与原因 |

推进到 **764 年**给出结局评级（中兴 / 克复 / 苟安 / 大乱初定 / 崩坏），
分项为两京、乱平、府库、威望、民心、河北。

**河北权重最高**——因为安史之乱真正的后果不是"平定"，而是河朔三镇自此百年割据。
一把按史载走完的战绩是 **克复 75.4 分**：赢了战争，输了河北。

## 数据诚实

这个项目对自己的假设是公开的：

- 人物才略、忠诚、野心是**建模估值**，不是史料数字；
- 兵力取史载量级作示意；粮价、民变、士气、补给是**模拟假设**；
- 朝议立场由规则推出（角色 + 才略 + 忠诚 + 野心 + 选项后果），**不是奏议原文**；
- 事件日期按史载年月；只记年或只记月者按最可能月份归位。

逐项说明见 `python tools/data_provenance.py`。

---

## 目录结构

```
WorldBranch/
├─ backend/                     Flask + SQLAlchemy 后端
│  ├─ app/
│  │  ├─ models.py              世界模板 / 分支 / 地区状态 / 事件 / 快照 / 决策
│  │  ├─ services.py            建分支、派生、干预、因果链
│  │  ├─ api/                   worlds / branches / ai 三个蓝图
│  │  ├─ engine/                推演、史实、决策、军事、忠诚、朝议、官职、结局
│  │  ├─ seed/                  内置世界（tang_755 主世界，tang_750 回归基线）
│  │  └─ cli.py                 init-db / seed / new-branch / advance / show
│  ├─ tests/                    178 个用例
│  ├─ serve.py                  生产入口（waitress，一键启动用的就是它）
│  └─ run.py                    开发入口（热重载）
├─ frontend/                    Vue 3 + Vite
│  ├─ src/                      App.vue、组件、api.js、sound.js
│  ├─ dist/                     构建产物（随仓库走，使用者无需装 Node）
│  ├─ build.mjs                 构建脚本
│  └─ smoke.mjs / smoke-mobile.mjs   jsdom 渲染冒烟
├─ docs/                        设计文档、AI 分析层、部署（可选）、手机访问
├─ deploy/                      systemd / nginx / 部署脚本（可选，默认用不到）
├─ tools/                       启动、CI、打包、数据校验、示例
├─ start.bat / start.sh         一键启动
└─ LICENSE · README.md
```

后端引擎分四层，每层只做一件事：

| 模块 | 职责 |
|---|---|
| `engine/rules.py` | 纯函数规则（粮食、财政、价格），不碰数据库 |
| `engine/simulation.py` | 按月推进、调运传导、事件生成、快照 |
| `engine/history.py` | 史实事件的**条件判定**与改道记录 |
| `engine/decisions.py` | 世界主动抛出的抉择与后果结算 |
| `engine/military.py` | 战力：兵员 × 士气/补给 × 主帅系数 |
| `engine/loyalty.py` | 功高震主、拥兵自重、叛离 |
| `engine/counsel.py` | 人物按自身利益与能力给出立场 |
| `engine/ending.py` | 通用五年评估（tang_750） |
| `engine/end_tang.py` | 八年结局评估（tang_755，按两京/乱平/河北计分） |

## 界面入口

| 路径 | 说明 |
|---|---|
| `/` | 重定向到 `/app/` |
| `/app/` | **Vue 3 界面** |
| `/api/...` | REST 接口 |

## 前端构建

本机 Node 环境禁止以管道方式 spawn 子进程，Vite 内部的 esbuild 会因此失败。
`frontend/build.mjs` 在加载 Vite 前禁用 `child_process` 并同步内置 ESM 导出，
再把 `vue` 指向预构建的 browser ESM、目标设为 `esnext`，从而跳过所有 spawn 环节。

```powershell
cd frontend
node build.mjs     # 产物输出到 dist/，由 Flask 在 /app/ 托管
node smoke.mjs     # 用 jsdom 真实挂载并断言渲染结果
```

### 地图数据

安史之乱切片使用**真实边界切分**：拿唐朝七道的真实地理，按历史情形切成八块
（关内道→京兆/灵武，河北道→范阳/河北诸州，河南道→河南府/睢阳，河东道→太原，
另加潼关关隘），由 `tools/build_geo_755.py` 用 Sutherland–Hodgman 半平面裁剪生成。

早先的 tang_750 世界则以**现代省级行政区边界近似唐代各道辖境**：

| 道 | 由哪些现代省组成 |
|---|---|
| 关内道 | 陕西、宁夏 |
| 陇右道 | 甘肃、青海、新疆 |
| 河东道 | 山西 |
| 河北道 | 河北、北京、天津、辽宁 |
| 河南道 | 河南、山东 |
| 淮南道 | 江苏、安徽 |
| 江南道 | 浙江、江西、湖南、福建、上海 |

生成脚本 `tools/build_geo.py`（会自动下载省级边界、简化顶点、输出到
`backend/app/seed/data/tang_750_geo.json`）。这是**近似展示**，不是历史行政区划复原，
界面上有明确标注。

渲染技巧：一个"道"由多个省多边形拼成，前端用「先描边、再填充」两遍绘制，
让内部省界被填充色盖掉，视觉上就是一个整体。

## 快速开始

### 只需要一步

- **Windows**：双击 `start.bat`
- **Linux / macOS**：`./start.sh`

脚本会自己完成：找合适的 Python（3.10+）→ 建虚拟环境 → 装依赖 →
建库并播种 → 挑一个空闲端口 → 起服务 → 打开浏览器。

**不需要装数据库**：数据默认存在 `backend/instance/worldbranch.db`
（Python 自带的 SQLite）。首次运行约十几秒，之后几秒即开。

> 需要 Python 3.10 或更高。装 Python 时记得勾选 “Add Python to PATH”。

### 分发给别人

```powershell
python tools\package.py --oneclick    # 打包并验证解压后能一键启动
```

产物在 `dist-package/worldbranch-<日期>.tar.gz`（约 0.5 MB），
使用者解压后双击 `start.bat` 即可，不含 Node、不含数据库、不需要联网装服务。

### 开发者方式

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
. .\tools\dev-env.ps1

cd backend
$env:FLASK_APP = "run.py"
python -m flask init-db
python -m flask seed
python run.py            # 开发模式：热重载
```

然后打开 <http://127.0.0.1:5210/>，页面直接进入安史之乱切片。

想先看它跑得对不对，不必开界面：

```powershell
python tools\demo\demo_anshi.py      # 八年史实线：21 件史实是否按年月应验
python tools\demo\demo_diverge.py    # 三场景对比：催战 / 坚守 / 主将病故
python tools\demo\demo_end_tang.py   # 两种打法的八年结局与分项得分
python tools\demo\demo_counsel.py    # 朝议：谁在进言、主哪一项、为什么
python tools\demo\demo_loyalty.py    # 忠诚逐年变化：功高者如何离心
python tools\data_provenance.py # 每个数字从哪来
```

### 数据库

**默认用 Python 自带的 SQLite**，数据就是一个文件：
`backend/instance/worldbranch.db`。不需要安装数据库、不需要配置。

SQLite 下开了 WAL、`busy_timeout=5s`、`foreign_keys`，
多线程起服务（`serve.py` 默认 8 线程）不会出现 `database is locked`。

想把数据放到别处或换成 MySQL 时才需要配置：

```
# 换路径（sqlite:/// 后面是相对 backend/ 的路径）
WORLDBRANCH_DATABASE_URL=sqlite:///instance/worldbranch.db

# 换 MySQL（先 pip install -r requirements-mysql.txt）
WORLDBRANCH_DATABASE_URL=mysql+pymysql://用户:密码@主机:3306/库名?charset=utf8mb4
```

写进 `backend/.env`（已 gitignore）或直接设环境变量都行，代码无需改动。

### 性能

远程数据库单次往返约 36 ms，所以引擎做了两处批处理（见 `engine/simulation.py`）：

- 事件与快照在内存里攒成字典，最后统一写入；
- 用 Core `insert()` 而不是 ORM 对象，避免 SQLAlchemy 为取回自增主键而退化成逐条插入。

实测「推进 24 个月」从 4366 ms 降到 275 ms，且耗时不再随月数线性增长。

```powershell
python tools\bench_advance.py 60    # 计时
```

## 多尺度观察

同一份世界数据，按观察尺度换一种聚合方式——不新增、不隐藏数据：

| 尺度 | 地图呈现 | 侧栏 | 事件范围 |
|---|---|---|---|
| 世界级 | 按势力着色，只标势力名 | 势力概览（人口/存粮/粮价/府库） | world + nation |
| 国家级 | 同上，带治所 | 势力概览 | nation + region |
| 地区级 | 按道着色，标道名与粮价 | 地区详情 + 干预 | region |
| 局部级 | 同上 | 地区详情 | region + local |

缩放地图会自动切换尺度；手动选择后转为手动模式，可一键恢复自动。

## AI 分析层（已实现，BYOK）

AI 能力建立在**用户自己的 API Key** 上，不绑定任何厂商，详见
[AI 分析层设计](docs/AI分析层设计.md)。

**Key 从不落库**：浏览器保存在 localStorage，随请求头 `X-LLM-Key` 传入，
服务端用完即弃。数据库里只有接口地址与模型名。

| 组件 | 说明 |
|---|---|
| 适配层 `app/ai/providers.py` | 唯一的厂商相关代码；内置 `openai_compatible` 与离线 `mock` |
| 知识库 `app/ai/knowledge.py` | 资料切片 + 字符二元组检索，带来源与可信度 |
| 材料组装 `app/ai/context.py` | 只把引擎已记录的事实整理成提示词，不产生新数据 |
| 服务 `app/ai/service.py` | 材料 → 提示词 → 模型 → 带引用的回答 |

接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/ai/kinds` | 可用适配器 |
| GET/POST | `/api/ai/providers` | 模型服务配置（不含 Key） |
| POST | `/api/ai/branches/<id>/analyze` | 执行分析（Key 走请求头） |
| GET | `/api/ai/branches/<id>/material` | 只看会送给模型的材料 |
| GET/POST | `/api/ai/worlds/<key>/knowledge` | 知识库条目 |

内置知识库有 5 篇资料（赋税与转运、军事结构、灾荒赈济、行政区划、建模假设），
每篇都标注来源与可信度（`primary` / `secondary` / `assumption`）。

实测材料示例（`python tools/demo/demo_ai.py`）：

```
【世界】唐朝（天宝九年（750 年））
【数据可信度说明】人口与耕地为量级估算…；存粮、粮价指数、民变指数为模拟初始假设…
【各道现状】- 河北道：人口 4,800,000，存粮 331,200 石，粮价指数 5.55，民变指数 0.76…
【近期事件】- [750-03-01]（region/grain_flow，程度4）河南道调粮至河北道…
【重点事件】…【该事件的因果链（由远及近）】
  · [750-01-01] （干预）河北道歉收
  · [750-03-01] 河北道出现粮荒
【参考资料】[2] 唐代的灾荒与赈济（《通典》…，可信度 secondary）…
```

## 附：旧世界 tang_750

安史之乱切片之前，项目做过一个"治天下"式的五年沙盘（天宝九年，7 个道）。
它保留了通用的粮食—财政—民变链条与六类决策，用于验证引擎本身：

| 决策 | 触发条件 |
|---|---|
| 河北藩镇上表请饷 | 藩镇府库透支 |
| 某道请求赈济 | 该道受灾、缺粮或民变升高 |
| 朝议：是否削藩 | 臣属度 < 0.25 |
| 吐蕃寇边 | 陇右随机边患 |
| 漕运受阻 | 江淮粮价走高 |
| 河北举兵 | 臣属度 < −0.15 |

`python tools/demo/demo_ending.py <策略>` 可跑三种打法的五年结局。
它现在的作用是**回归基线**：证明引擎不依赖唐朝切片的特殊数据也能跑。

## 核心概念

| 概念 | 含义 |
|---|---|
| 世界（World） | 模板：地区、势力、初始数据、规则参数。第一版只内置 |
| 分支（Branch） | 独立时间线，有自己的状态、事件、快照 |
| 精度（Precision） | `macro` / `standard` / `fine` / `deep`，整个世界统一设置 |
| 事件（Event） | 真实发生的变化，带 `scope`、`severity`、`causes`，不是固定大事/小事标签 |
| 快照（Snapshot） | 每个 tick 的世界状态，用于复现与对比 |
| 转运通道（TradeLink） | 两道之间的粮道，带月度运力与途耗 |

## 跨区域因果传导

这是项目的核心机制，不是事后叙述：

```
用户干预（河北歉收）
   └─> 河北断粮            （famine）
         └─> 河南、河东调粮  （grain_flow，带运力上限与途耗）
               └─> 调出方存粮下降、粮价被推高（price_pressure）
```

每个事件都在 `causes` 里记录上游事件 id，`GET /events/<id>/chain` 可以一路回溯到
最初的那次干预。界面上点击事件即可展开这条链。

实测示例（`python tools/demo/demo_chain.py`）：

```
[干预] （干预）河北道歉收  (event id=1)
  [750-02-01] famine      河北道出现粮荒      ← step_region, 事件1
  [750-02-01] grain_flow  河南道调粮至河北道  ← trade_transfer, 事件3
  [750-02-01] grain_flow  河东道调粮至河北道  ← trade_transfer, 事件3

从「河南道调粮至河北道」回溯因果链（3 个节点）：
  750-01-01  （干预）河北道歉收
  750-02-01  河北道出现粮荒
  750-02-01  河南道调粮至河北道
```

## 用户干预

界面上点击地区后可以：制造歉收、开仓赈济（花钱买粮）、增减税率。干预会写入事件流，
并成为后续所有连锁反应的因果起点。

## 时间线分支对比

从任意时刻派生出一条新分支，两边各自推演，然后在「分支对比」页看差异：

- 两条线各自的日期、进度、精度
- 七个道的存粮 / 粮价 / 民变 / 税率 / 人口 逐项对比，带差值
- 只在 A 发生、只在 B 发生的事件
- 自动识别派生关系与共同祖先

实测示例（`python tools/demo/demo_compare.py`）：

```
A: 750-08-01  B: 750-08-01
关系：B 从 A 派生 = True；共同祖先 = 甲：置之不理

地区               存粮(A)         存粮(B)          差异
河北道            578,796     1,478,800    +900,004
河南道         10,079,400    11,198,500  +1,119,100

只在 A 发生：河北道粮价高企 / 河北道民变风险升高
只在 B 发生：（干预）河北道开仓赈济
```

注意河南的存粮在 B 里反而更多——因为 A 里河北缺粮要从河南调运，B 里开了仓就不用了。
这就是跨区域传导在分支对比下的体现。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/worlds` | 世界列表 |
| GET | `/api/worlds/<key>` | 世界详情（含地区几何） |
| GET | `/api/worlds/<key>/map` | 地图数据 |
| POST | `/api/worlds/<key>/branches` | 新建分支 |
| GET | `/api/branches/<id>` | 分支信息 |
| POST | `/api/branches/<id>/advance` | 推进 N 个月 |
| POST | `/api/branches/<id>/actions` | 用户干预：制造歉收 / 开仓赈济 / 调整税率 |
| GET | `/api/branches/<id>/events/<eid>/chain` | 回溯事件的上游因果链 |
| GET | `/api/branches/compare?left=&right=` | 对比两条时间线 |
| GET | `/api/branches/<id>/state` | 当前状态 |
| GET | `/api/branches/<id>/events` | 事件（支持 `min_scope`、`min_severity`） |
| GET | `/api/branches/<id>/snapshots` | 快照历史 |
| POST | `/api/branches/<id>/fork` | 派生新分支 |
| GET | `/api/branches/<id>/decisions` | 待决事项（含朝议）；`?history=1` 取历史 |
| POST | `/api/branches/<id>/decisions/<did>/resolve` | 决断 |
| GET | `/api/branches/<id>/armies` | 各军兵力、士气、战力、主帅 |
| GET | `/api/branches/<id>/loyalty` | 人物忠诚一览 |
| GET | `/api/branches/<id>/history` | 史实应验与改道 |
| GET | `/api/branches/<id>/ending` | 结局评估（未到时限返回 204） |

## 测试与 CI

一条命令跑完全部检查（后端测试、史料数据校验、建库播种、前端构建、渲染冒烟）：

```powershell
python tools\ci.py
python tools\ci.py --skip-frontend   # 只跑后端
python tools\ci.py --port 5300       # 换端口（默认 5300，不占用开发用的 5210）
```

CI 用**独立的 SQLite 文件**（`.tmp/ci.db`），不会碰你本地的数据库；
起一个临时服务跑完冒烟后会自己关掉。

同样这套检查会在推送时由 GitHub Actions 执行（`.github/workflows/ci.yml`）。

单独跑某一项：

```powershell
cd backend && python -m pytest           # 后端测试
cd frontend && node smoke.mjs <url>      # 渲染冒烟（需要服务在跑）
python tools\check_tang_data.py          # 史料数据完整性
python tools\diagnose_history.py         # 逐条打印史实判定结果
```

## 设计约束（来自项目总设计文档）

- 知识库 ≠ 模拟能力：状态变化由引擎与规则计算，AI 不代替计算。
- 事件不贴死「大事/小事」标签，靠范围、程度、时长、对象、因果推导展示层级。
- 模拟精度与地图缩放互相独立，且一个世界统一精度。
- 缺数据标注未知/估算与来源，不编造精确数字。
- 同一 seed 必得同一结果（可复现）。
---

## 参与

欢迎提 Issue 与 PR。改动前建议先跑一遍：

```powershell
python tools\ci.py
```

它会依次检查启动脚本、后端测试、史料数据完整性、建库播种、前端构建、
构建产物与源码是否同步、桌面与窄屏渲染冒烟、生产入口、接口自检、发布包。

几条约定：

- **史料引用要给出处**。新增史实事件请填 `source`，并确保 `conditions`
  与 `effects` 里引用的地区 / 人物 / 事件 key 都真实存在（CI 会校验）。
- **不要把建模值写成史料**。忠诚、才略、建议立场都是推算结果，
  界面上必须能与「史载原文」区分开。
- **改了前端源码要一起提交 `frontend/dist`**。产物随仓库走，是为了让
  使用者不装 Node 也能运行；CI 会检查两者是否一致。

## 许可

[MIT](LICENSE)

史实部分引用的史料（《资治通鉴》《旧唐书》《新唐书》等）属于公有领域；
项目中的建模参数、界面与代码以 MIT 授权。