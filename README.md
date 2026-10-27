# WorldBranch · 平行世界推演实验室

多尺度空间、多层级事件、跨区域因果关联的世界模拟系统。

> 当前状态：**v0.1 骨架已跑通**。唐朝世界可推进时间、产生事件、保存快照、派生分支，
> 并通过 HTTP API 与一个可缩放的地图界面呈现。
> 完整设计见 [项目总设计文档](docs/WorldBranch_项目总设计文档.md)。

---

## 现在有什么

```
新项目开发/
├─ backend/                  Flask + SQLAlchemy 后端
│  ├─ app/
│  │  ├─ models.py           世界模板 / 分支 / 地区状态 / 事件 / 快照 / 转运通道
│  │  ├─ services.py         建分支、派生、干预、因果链
│  │  ├─ api/                worlds、branches 两个蓝图
│  │  ├─ engine/
│  │  │  ├─ rules.py         纯函数规则层（可单测，不碰数据库）
│  │  │  └─ simulation.py    时间推进、调运传导、事件生成、快照
│  │  ├─ seed/tang_750.py    唐朝天宝九年内置世界（7 道、2 势力、8 条粮道）
│  │  └─ cli.py              init-db / seed / new-branch / advance / show
│  ├─ tests/                 47 个测试（规则、引擎、传导、干预、API）
│  └─ run.py                 开发入口
├─ frontend/                 Vue 3 + Vite 前端（新界面）
│  ├─ src/components/        MapView / EventFeed / RegionDetail
│  ├─ build.mjs              构建脚本（绕过本机 spawn 限制）
│  └─ smoke.mjs              jsdom 渲染冒烟测试
├─ web/                      旧版静态界面（保留在 /legacy 作为回退）
├─ docs/                     设计文档、开发环境说明
└─ tools/                    地理数据生成、连接诊断、验收与演示脚本
```

## 界面入口

| 路径 | 说明 |
|---|---|
| `/` | 重定向到 `/app/` |
| `/app/` | **Vue 3 新版界面** |
| `/legacy` | 旧版原生 JS 界面（回退用） |

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

地图不是手画的方块，而是用**现代省级行政区边界近似唐代各道辖境**：

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

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
. .\tools\dev-env.ps1

cd backend
$env:FLASK_APP = "run.py"
python -m flask init-db
python -m flask seed
python -m flask new-branch tang_750 --precision standard --seed 1
python -m flask advance 1 --months 12
python run.py
```

然后打开 <http://127.0.0.1:5210/>

### 数据库

开发期连接的是**腾讯云服务器上的 MySQL**（5.7.44 / utf8mb4），连接串写在
`backend/.env`（已 gitignore，不会进仓库）。换库只改这一行：

```
WORLDBRANCH_DATABASE_URL=mysql+pymysql://用户:密码@主机:3306/库名?charset=utf8mb4
```

不配置时回退到本地 SQLite（`backend/instance/worldbranch.db`），测试用的就是它。

连接出问题先跑诊断脚本，它会把失败分成"网络 / 认证 / 库不存在 / 字符集"几类：

```powershell
python tools\test_db.py
```

### 性能

远程数据库单次往返约 36 ms，所以引擎做了两处批处理（见 `engine/simulation.py`）：

- 事件与快照在内存里攒成字典，最后统一写入；
- 用 Core `insert()` 而不是 ORM 对象，避免 SQLAlchemy 为取回自增主键而退化成逐条插入。

实测「推进 24 个月」从 4366 ms 降到 275 ms，且耗时不再随月数线性增长。

```powershell
python tools\bench_advance.py 60    # 计时
```

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

实测示例（`python tools/demo_chain.py`）：

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

实测示例（`python tools/demo_compare.py`）：

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
| POST | `/api/branches/<id>/fork` | 派生新分支 |
| GET | `/api/branches/compare?left=&right=` | 对比两条时间线 |
| GET | `/api/branches/<id>/state` | 当前状态 |
| GET | `/api/branches/<id>/events` | 事件（支持 `min_scope`、`min_severity`） |
| GET | `/api/branches/<id>/snapshots` | 快照历史 |
| POST | `/api/branches/<id>/fork` | 派生新分支 |

## 测试

```powershell
cd backend
python -m pytest
```

## 设计约束（来自项目总设计文档）

- 知识库 ≠ 模拟能力：状态变化由引擎与规则计算，AI 不代替计算。
- 事件不贴死「大事/小事」标签，靠范围、程度、时长、对象、因果推导展示层级。
- 模拟精度与地图缩放互相独立，且一个世界统一精度。
- 缺数据标注未知/估算与来源，不编造精确数字。
- 同一 seed 必得同一结果（可复现）。