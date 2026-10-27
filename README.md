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
└─ tools/                    环境脚本与沙箱兼容 shim
```

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

## 核心概念

| 概念 | 含义 |
|---|---|
| 世界（World） | 模板：地区、势力、初始数据、规则参数。第一版只内置 |
| 分支（Branch） | 独立时间线，有自己的状态、事件、快照 |
| 精度（Precision） | `macro` / `standard` / `fine` / `deep`，整个世界统一设置 |
| 事件（Event） | 真实发生的变化，带 `scope`、`severity`、`causes`，不是固定大事/小事标签 |
| 快照（Snapshot） | 每个 tick 的世界状态，用于复现与对比 |

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