# 同花顺热度排名系统 📊

基于同花顺热榜API的股票热度排名Web系统，含全屏Dashboard、30天排名历史、多因子推荐算法、每日复盘自优化、智能过滤机制。

[![GitHub Pages](https://img.shields.io/badge/在线访问-GitHub%20Pages-brightgreen)](https://yjj79819.github.io/tdx/)
[![Python](https://img.shields.io/badge/Python-3.9+-green)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0-blue)](https://flask.palletsprojects.com/)
[![Auto Update](https://img.shields.io/badge/自动更新-交易日定时-orange)](https://github.com/yjj79819/tdx/actions)

---

## ✨ v3.0 特性

### 🖥️ 全屏Dashboard
- **5个栏目** — TOP50、板块&行业、概念分析、推荐股票、每日复盘
- **全屏Grid表格** — CSS Grid，列宽fr比例自适应窗口
- **暗色主题** — 深蓝/青色专业配色
- **股票名称链接** — 点击跳转同花顺详情页

### 📈 排名历史柱状图
- 每只股票下方直接显示**进入前100以来的全部排名历史**竖向柱状图
- **排名显示在柱子上方**（彩色数字），**日期显示在柱子内部**
- 柱子高度根据排名变化：#1最高，#100最低
- 柱状图颜色按排名区间区分：
  - 🟡 **金色发光** — 排名第1
  - 🔴 **亮红发光** — 排名2-3
  - 🌸 **浅红** — 排名4-5
  - 🟠 **亮橙** — 排名6-10
  - 🔵 **亮蓝** — 排名11-50
  - 🟢 **绿色** — 排名51-100

### 🎯 智能筛选条件
- 排除ST股票
- 排除亏损股
- 只显示曾进入前100名的股票
- 最新价红涨绿跌显示
- 表头支持点击排序

### ⭐ 13因子推荐算法 + 动态权重

本地版和GitHub版**算法完全一致**（v3）：

| 因子 | 权重 | 说明 |
|------|------|------|
| 排名分 | 25 | 前5/10/20阶梯加分 |
| 板块支撑 | 15 | 同板块上榜股票数 |
| 涨跌幅 | 5 | 涨停/大涨加分 |
| 概念丰富度 | 10 | 多概念标签加分 |
| 低价优势 | 5 | <10元满分 |
| 连续上榜 | 10 | ≥3天起加分(30天历史) |
| 月内频率 | 10 | ≥10次起加分(30天历史) |
| 排名趋势 | 10 | 上升加分/下降扣分 |
| 最佳排名 | 10 | 曾进前3/10加分 |
| 平均排名 | 10 | ≤20名满分 |
| 动量分 | 5 | 近3天排名飙升加分 |
| **低价优质股加权** | **+5** | **10元以下+排名50内+非ST+非亏损** |
| **上榜趋势分析** | **+10** | **刚冲上100/上升趋势/新上榜到50** |

### 🛡️ 智能过滤
- **走下坡路过滤** — 前十→五十→一百持续下降的股票不推荐
- **ST过滤** — 自动排除ST/*ST股票
- **亏损过滤** — 自动排除亏损股
- **低价优质股侧重** — 10元以下+排名50内+非ST+非亏损额外加权

### 📋 每日复盘栏目
- **30天胜率走势图** — 绿/黄/红柱状图直观展示
- **最近5次详细复盘** — 每只推荐股前后对比
- **算法权重面板** — 当前13维度权重值+版本号

### 🔄 智能自优化
- 近3次胜率≥60% → 趋势+1 动量+1
- 近3次胜率<40% → 涨跌-1 动量-1
- 权重持久化保存，累加进化

### 🔑 Cookie管理
- 网页上直接设置同花顺Cookie
- 6步详细教程（F12控制台获取）
- Cookie有效性测试

---

## 🚀 在线访问

👉 **[https://yjj79819.github.io/tdx/](https://yjj79819.github.io/tdx/)**

无需本地运行，交易日自动更新（9:00/盘中每小时/收盘后17:00）。
查看[数据更新流水线](https://github.com/yjj79819/tdx/actions/workflows/update_data.yml)。

---

## 快速开始

### 环境要求
- Python 3.9+
- 需要网络（访问同花顺API）

### 安装

```bash
pip install -r requirements.txt
```

### 运行

```bash
python web_server_v2.py
```

启动后访问: http://localhost:5000

### Cookie设置
1. 打开同花顺官网 https://ms.10jqka.com.cn/
2. 按F12打开开发者工具
3. 切换到Console(控制台)
4. 输入 `document.cookie` 并按回车
5. 复制输出的长字符串
6. 在网页上点击"🔑 Cookie"按钮粘贴保存

---

## GitHub Actions 自动更新

配置文件：`.github/workflows/update_data.yml`

**交易日定时更新**（仅周一到周五）：
- **9:00** — 开盘前更新
- **10:00-14:00** — 盘中每小时更新
- **17:00** — 收盘后2小时更新

**获取30天历史+复盘**：在 GitHub Settings → Secrets → Actions 中添加：
- `THS_COOKIE`: 你的同花顺Cookie

**手动触发**：在网页上点击"↻ 手动更新"按钮，或到Actions页面手动Run workflow。

---

## API 接口

| 接口 | 说明 |
|------|------|
| `GET /` | Web全屏Dashboard |
| `GET /api/filtered_hot/<date>` | 指定日期的TOP50排名（已过滤） |
| `GET /api/sector/<date>` | 板块热度分析 |
| `GET /api/concept/<date>` | 概念热度分析 |
| `GET /api/concept_hot` | 概念热榜（同花顺实时） |
| `GET /api/industry_hot` | 行业热榜（同花顺实时） |
| `GET /api/recommendations` | 推荐股票（13因子算法） |
| `GET /api/review` | 每日复盘历史数据 |
| `GET /api/weights` | 当前推荐算法权重 |
| `GET /api/sentiment` | 市场情绪指数 |
| `GET /api/stock_history_filtered/<code>` | 单股30天排名历史 |
| `GET /api/cookie/status` | Cookie状态 |
| `POST /api/cookie/set` | 设置Cookie |
| `GET /api/cookie/test` | 测试Cookie有效性 |
| `POST /api/stock/fetch_history/<code>` | 手动获取股票历史 |
| `POST /api/update_now` | 立即触发数据更新 |

---

## 项目结构

```
.
├── web_server_v2.py          # Flask主程序（13因子推荐+动态权重+复盘+Cookie管理）
├── export_data.py            # GitHub Actions数据导出脚本（算法与本地版完全一致）
├── report_generator.py       # 每日报告生成器
├── requirements.txt
├── cookie.txt                # 同花顺Cookie（本地运行用）
├── templates/
│   └── index.html            # Flask版前端（全屏布局）
├── docs/                     # GitHub Pages静态站
│   ├── index.html            # 静态版前端（与本地版界面一致）
│   └── data/
│       ├── top50.json        # TOP50排名数据
│       ├── sector.json       # 板块分析
│       ├── concept.json      # 概念分析
│       ├── concept_hot.json  # 概念热榜
│       ├── industry_hot.json # 行业热榜
│       ├── recommendations.json      # 推荐股票
│       ├── sentiment.json    # 市场情绪
│       ├── review_results.json      # 复盘结果（90天保留）
│       ├── recommendation_history.json  # 推荐历史快照（60天保留）
│       ├── recommendation_weights.json  # 算法动态权重
│       ├── meta.json         # 数据元信息
│       └── history/          # 每只股票30天排名JSON
└── .github/workflows/
    └── update_data.yml       # 自动更新Workflow（交易日定时）
```

---

## 数据来源

| 数据 | 来源 |
|------|------|
| 热榜排名 | 同花顺 `dq.10jqka.com.cn` |
| 30天历史排名 | 同花顺 `dataq.10jqka.com.cn`（需Cookie） |
| 板块/概念热榜 | 同花顺板块API |
| 行情数据 | 新浪财经 `hq.sinajs.cn` + akshare |
| 板块信息 | 东方财富 `levistock` |
| 概念标签 | 同花顺API tag字段 |

---

## 开发记录

- **v3.0** — 推荐算法升级：上榜趋势分析、走下坡路过滤、低价优质股加权、ST/亏损过滤；栏目合并（板块&行业、概念分析）；Cookie管理；GitHub Pages静态版与本地版完全一致；交易日定时更新
- **v2.1** — 排名历史柱状图直接显示、高对比度配色、#1金色/#2-5红色发光、表头排序、智能筛选、最新价红涨绿跌
- **v2.0** — 全屏Dashboard、30天历史柱状图、12因子推荐、每日复盘自优化
- **v1.5** — CSS Grid表格、概念热榜、行业热榜、推荐系统5因子
- **v1.0** — Flask Web服务、TOP50排名、板块分析

## 许可证

MIT License
