# 问财条件模板库

## 一、基础条件模板

### 1.1 热度范围选择

| 模板ID | 查询语句 | 说明 |
|--------|---------|------|
| `hot_50` | 热门股票前50名 | 热度前50 |
| `hot_100` | 热门股票前100名 | 热度前100 |
| `hot_200` | 热门股票前200名 | 热度前200 |
| `hot_300` | 热门股票前300名 | 热度前300 |

### 1.2 新进入热度榜（昨日未上榜）

| 模板ID | 查询语句 | 说明 |
|--------|---------|------|
| `new_enter_50` | 新进入热门股票前50名 | 昨日未在榜，今日新进入前50 |
| `new_enter_100` | 新进入热门股票前100名 | 昨日未在榜，今日新进入前100 |
| `new_enter_200` | 新进入热门股票前200名 | 昨日未在榜，今日新进入前200 |
| `new_enter_300` | 新进入热门股票前300名 | 昨日未在榜，今日新进入前300 |

### 1.3 股价范围选择

| 模板ID | 查询语句 | 说明 |
|--------|---------|------|
| `price_10` | 股价低于10元 | 10元以下 |
| `price_13` | 股价低于13元 | 13元以下 |
| `price_15` | 股价低于15元 | 15元以下 |
| `price_20` | 股价低于20元 | 20元以下 |
| `price_30` | 股价低于30元 | 30元以下 |
| `price_range` | 股价在{min}到{max}元之间 | 自定义区间 |

### 1.4 排除条件

| 模板ID | 查询语句 | 说明 |
|--------|---------|------|
| `no_st` | 非ST | 排除ST/*ST股 |
| `no_kcb` | 非科创板 | 排除科创板（688开头） |
| `no_bjb` | 非北交所 | 排除北交所（8开头） |
| `no_new` | 上市超过60天 | 排除新股（可自定义天数） |
| `no_loss` | 市盈率大于0 | 排除亏损股 |
| `no_delist` | 非退市整理 | 排除退市整理股 |

---

## 二、组合条件模板

### 2.1 标准筛选模板

```python
STANDARD_TEMPLATES = {
    "保守型": [
        "热门股票前100名",
        "股价低于10元",
        "非ST",
        "非科创板",
        "非北交所",
        "上市超过90天",
        "市盈率大于0",
        "市盈率小于30"
    ],
    
    "稳健型": [
        "热门股票前200名",
        "股价低于13元",
        "非ST",
        "非科创板",
        "非北交所",
        "上市超过60天",
        "市盈率大于0"
    ],
    
    "激进型": [
        "热门股票前300名",
        "股价低于20元",
        "非ST",
        "上市超过30天",
        "市盈率大于0"
    ],
    
    "新进热门": [
        "新进入热门股票前100名",
        "股价低于15元",
        "非ST",
        "非科创板",
        "上市超过60天",
        "市盈率大于0"
    ]
}
```

### 2.2 技术面增强模板

```python
TECH_TEMPLATES = {
    "MACD金叉热门": [
        "热门股票前200名",
        "MACD金叉",
        "股价低于15元",
        "非ST",
        "市盈率大于0"
    ],
    
    "超跌反弹": [
        "热门股票前300名",
        "RSI小于30",
        "股价低于10元",
        "非ST",
        "市盈率大于0"
    ],
    
    "放量突破": [
        "热门股票前200名",
        "成交量放大2倍以上",
        "股价突破20日均线",
        "股价低于15元",
        "非ST"
    ],
    
    "均线多头": [
        "热门股票前100名",
        "5日10日20日均线多头排列",
        "股价低于20元",
        "非ST",
        "市盈率大于0"
    ]
}
```

### 2.3 资金面增强模板

```python
CAPITAL_TEMPLATES = {
    "主力流入": [
        "热门股票前200名",
        "主力资金净流入",
        "股价低于15元",
        "非ST",
        "市盈率大于0"
    ],
    
    "北向加仓": [
        "热门股票前200名",
        "北向资金净流入",
        "股价低于20元",
        "非ST",
        "市盈率大于0"
    ],
    
    "机构买入": [
        "热门股票前300名",
        "龙虎榜机构净买入",
        "股价低于20元",
        "非ST"
    ]
}
```

---

## 三、前端条件选择器设计

### 3.1 条件选择面板

```
┌─────────────────────────────────────────────────────────┐
│  筛选条件                                                │
├─────────────────────────────────────────────────────────┤
│  热度范围:  [前50▼]  [前100]  [前200]  [前300]           │
│                                                         │
│  新进入:    [□] 新进入前50  [□] 新进入前100              │
│             [□] 新进入前200 [□] 新进入前300              │
│                                                         │
│  股价范围:  [低于▼] [13▼] 元                             │
│             (可选: 低于10/13/15/20/30 或 自定义区间)      │
│                                                         │
│  排除条件:                                              │
│    [✓] ST股        [✓] 科创板       [✓] 北交所          │
│    [✓] 新股(60天)  [✓] 亏损股      [ ] 退市整理         │
│                                                         │
│  技术条件:  (可选)                                       │
│    [ ] MACD金叉    [ ] RSI<30      [ ] 均线多头         │
│    [ ] 放量突破    [ ] 布林突破                         │
│                                                         │
│  资金条件:  (可选)                                       │
│    [ ] 主力流入    [ ] 北向流入    [ ] 机构买入          │
│                                                         │
│  [重置]  [查询]                                         │
└─────────────────────────────────────────────────────────┘
```

### 3.2 快捷模板按钮

```
┌─────────────────────────────────────────────────────────┐
│  快捷模板:                                              │
│  [保守型] [稳健型] [激进型] [新进热门]                   │
│  [MACD金叉] [超跌反弹] [主力流入] [北向加仓]             │
└─────────────────────────────────────────────────────────┘
```

---

## 四、API调用示例

### 4.1 构建查询语句

```python
def build_query(conditions: dict) -> str:
    """
    根据条件构建问财查询语句
    
    Args:
        conditions: {
            "hot_range": 300,           # 热度范围
            "new_enter": False,         # 是否新进入
            "price_max": 13,            # 最高股价
            "exclude_st": True,         # 排除ST
            "exclude_kcb": True,        # 排除科创板
            "exclude_bjb": True,        # 排除北交所
            "exclude_new": 60,          # 排除新股天数
            "exclude_loss": True,       # 排除亏损
            "tech_signals": ["macd_golden"],  # 技术信号
            "capital_signals": ["main_inflow"]  # 资金信号
        }
    
    Returns:
        问财查询语句
    """
    parts = []
    
    # 热度范围
    if conditions.get("new_enter"):
        parts.append(f"新进入热门股票前{conditions['hot_range']}名")
    else:
        parts.append(f"热门股票前{conditions['hot_range']}名")
    
    # 股价范围
    if conditions.get("price_max"):
        parts.append(f"股价低于{conditions['price_max']}元")
    
    # 排除条件
    if conditions.get("exclude_st"):
        parts.append("非ST")
    if conditions.get("exclude_kcb"):
        parts.append("非科创板")
    if conditions.get("exclude_bjb"):
        parts.append("非北交所")
    if conditions.get("exclude_new"):
        parts.append(f"上市超过{conditions['exclude_new']}天")
    if conditions.get("exclude_loss"):
        parts.append("市盈率大于0")
    
    # 技术信号
    tech_map = {
        "macd_golden": "MACD金叉",
        "rsi_oversold": "RSI小于30",
        "ma_bullish": "均线多头排列",
        "volume_surge": "成交量放大2倍以上"
    }
    for signal in conditions.get("tech_signals", []):
        if signal in tech_map:
            parts.append(tech_map[signal])
    
    # 资金信号
    capital_map = {
        "main_inflow": "主力资金净流入",
        "north_inflow": "北向资金净流入",
        "institution_buy": "龙虎榜机构净买入"
    }
    for signal in conditions.get("capital_signals", []):
        if signal in capital_map:
            parts.append(capital_map[signal])
    
    return "；".join(parts)
```

### 4.2 使用示例

```python
# 示例1: 稳健型筛选
query1 = build_query({
    "hot_range": 200,
    "price_max": 13,
    "exclude_st": True,
    "exclude_kcb": True,
    "exclude_bjb": True,
    "exclude_new": 60,
    "exclude_loss": True
})
# 输出: "热门股票前200名；股价低于13元；非ST；非科创板；非北交所；上市超过60天；市盈率大于0"

# 示例2: 新进热门 + MACD金叉
query2 = build_query({
    "hot_range": 100,
    "new_enter": True,
    "price_max": 15,
    "exclude_st": True,
    "exclude_kcb": True,
    "exclude_new": 60,
    "exclude_loss": True,
    "tech_signals": ["macd_golden"]
})
# 输出: "新进入热门股票前100名；股价低于15元；非ST；非科创板；上市超过60天；市盈率大于0；MACD金叉"

# 示例3: 主力流入热门股
query3 = build_query({
    "hot_range": 200,
    "price_max": 20,
    "exclude_st": True,
    "exclude_loss": True,
    "capital_signals": ["main_inflow"]
})
# 输出: "热门股票前200名；股价低于20元；非ST；市盈率大于0；主力资金净流入"
```

---

## 五、查询结果处理

### 5.1 结果数据结构

```python
@dataclass
class StockResult:
    code: str           # 股票代码
    name: str           # 股票名称
    price: float        # 现价
    change_pct: float   # 涨跌幅
    hot_rank: int       # 热度排名
    hot_value: float    # 热度值
    pe_ratio: float     # 市盈率
    volume: int         # 成交量
    turnover: float     # 成交额
```

### 5.2 结果导出

问财支持"导数据"功能，可以导出筛选结果为Excel/CSV格式。

---

## 六、注意事项

1. **条件分隔符**：使用中文分号"；"分隔多个条件
2. **新进入逻辑**：问财能理解"新进入"表示昨日未在榜、今日新进入
3. **上市天数**：可自定义，建议30-90天
4. **市盈率条件**：`市盈率大于0`排除亏损，`市盈率小于30`排除高估值
5. **查询缓存**：相同条件结果可缓存5-15分钟

---

*文档版本：v1.0*  
*更新时间：2026-05-28*
