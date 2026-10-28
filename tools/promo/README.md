# 宣传片

用纯代码逐帧渲染 + numpy 合成配乐 + FFmpeg 编码，产出 `dist-promo/worldbranch-promo.mp4`
（1920×1080 / 30fps / 31s / H.264 + AAC）。

创作规范参考 [code-video-showcase](https://github.com/Moessif/code-video-showcase)（MIT）：
绯墨剧场主题、120 BPM 卡点、大字卡 + 风格段交替的结构、确定性渲染。

本项目**不包含**该技能的代码，也不依赖它运行——`build_promo.py` 是独立实现。

## 生成

```powershell
python -m pip install numpy pillow imageio-ffmpeg
python tools\promo\build_promo.py             # 出成片
python tools\promo\build_promo.py --stills    # 只出 9 张静帧，先看构图
python tools\promo\build_promo.py --frames-only
```

产物：`dist-promo/worldbranch-promo.mp4`（约 42 MB，gitignore）。

## 结构

| 时间 | 内容 |
|---|---|
| 0–6s | 开场：品牌字逐字出现 + 代码列上滚 |
| 6–10s | 大字卡「天宝十四载 / 21 件史实」+ 条件句场景 |
| 10–14s | 大字卡「潼关 / 三种走法」+ 地图聚光（镜头推近潼关） |
| 14–18s | 大字卡「河北 / 权重最高」+ 奏疏决策浮层 |
| 18–22s | 大字卡「八年之后 / 克复 75.4」+ 六项评分条 |
| 22–26s | 大字卡「开源 / 双击即跑」+ 命令行跑 CI |
| 26–31s | 结尾：品牌 + 一键启动 + MIT |

## 与技能的差异

本机浏览器在沙箱内无法启动（crashpad 被拒），所以渲染器从
HTML/Canvas/Playwright 换成了 Pillow；字体用系统字体（宋体/微软雅黑/Consolas），
技能规范要求的 OFL 字体没能下载。结构与节奏仍按技能执行。