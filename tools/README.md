# tools

开发与维护用的脚本。日常使用不需要碰这里——双击 `start.bat` 就够了。

## 入口

| 脚本 | 作用 |
|---|---|
| `bootstrap.py` | **一键启动**：找 Python、建虚拟环境、装依赖、建库播种、起服务、开浏览器 |
| `ci.py` | 跑完全部检查（本地与 GitHub Actions 共用一份） |
| `package.py` | 打可分发压缩包；`--oneclick` 会解包并用包内脚本实跑一遍 |
| `check_launcher.py` | 校验 `start.bat` 是 ASCII + CRLF（cmd 的硬要求） |
| `check_api.py` | 对着运行中的服务做接口自检 |

## 数据

| 脚本 | 作用 |
|---|---|
| `check_tang_data.py` | 校验史实事件的 key、条件、效果引用是否都存在 |
| `diagnose_history.py` | 逐条打印 21 件史实的判定结果（应验 / 改道 / 未到） |
| `data_provenance.py` | 打印每个数字的来源，以及哪些东西没有建模 |
| `build_geo_755.py` | 把 7 道切成 8 个区域，生成 `tang_755_geo.json` |
| `preview_geo_755.py` | 把 8 个区域画成图，检查切割是否合理 |

## 界面

| 脚本 | 作用 |
|---|---|
| `preview_ui.py` | 按当前实现渲染桌面与手机两张效果图（**示意图，不是截图**） |

## 性能

| 脚本 | 作用 |
|---|---|
| `bench_advance.py` | 推进多个月份的耗时基准 |

## 示例（`demo/`）

都是可直接运行的演示，用来在命令行里看清引擎行为，不必开界面。

| 脚本 | 演示什么 |
|---|---|
| `demo_anshi.py` | 八年史实线：21 件史实是否按年月应验 |
| `demo_diverge.py` | 潼关三场景：催战 / 坚守 / 主将病故 |
| `demo_end_tang.py` | 两种打法的八年结局与分项得分 |
| `demo_counsel.py` | 朝议：谁在进言、主哪一项、依据是什么 |
| `demo_decisions.py` | 各类决策的触发条件与后果结算 |
| `demo_loyalty.py` | 忠诚逐年变化，功高者如何离心 |
| `demo_armies.py` | 各军战力拆解：兵力 × 士气补给 × 主帅 |
| `demo_office.py` | 官职品级与迁转 |
| `demo_chain.py` | 单个事件的因果链（由远及近） |
| `demo_compare.py` | 两个分支的差异对比 |
| `demo_propagation.py` | 跨区域粮价传导 |
| `demo_ai.py` | AI 分析层的材料构成（不需要 Key） |
| `demo_ending.py` | tang_750 旧世界的五年评估（引擎回归基线） |

跑法：

```powershell
python tools\demo\demo_anshi.py
```