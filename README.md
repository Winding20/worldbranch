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
│  │  ├─ models.py           世界模板 / 分支 / 地区状态 / 事件 / 快照
│  │  ├─ services.py         建分支、派生分支、几何与势力元数据
│  │  ├─ api/                worlds、branches 两个蓝图
│  │  ├─ engine/
│  │  │  ├─ rules.py         纯函数规则层（可单测，不碰数据库）
│  │  │  └─ simulation.py    时间推进、事件生成、快照
│  │  ├─ seed/tang_750.py    唐朝天宝九年内置世界（7 道、2 势力）
│  │  └─ cli.py              init-db / seed / new-branch / advance / show
│  ├─ tests/                 28 个测试（规则、引擎、API）
│  └─ run.py                 开发入口
├─ web/                      地图界面（原生 JS + SVG，无构建步骤）
├─ docs/                     设计文档、开发环境说明
└─ tools/                    环境脚本、地理数据生成、连接诊断、验收脚本
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