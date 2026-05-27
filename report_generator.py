#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日推荐报告生成器
生成Markdown格式的推荐报告，包含统计数据和进化总结
"""
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
import requests
import levistock as lk

DB_PATH = Path(__file__).resolve().parent / 'hot_rank.db'
REPORT_DIR = Path(__file__).resolve().parent / 'reports'


def ensure_report_dir():
    """确保报告目录存在"""
    Path(REPORT_DIR).mkdir(parents=True, exist_ok=True)


def fetch_hot_rank():
    """获取同花顺热榜TOP100"""
    try:
        url = 'https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock?stock_type=a&type=hour&list_type=normal'
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': 'application/json',
        }
        resp = requests.get(url, headers=headers, timeout=15)
        data = resp.json()
        if data.get('status_code') == 0:
            return data['data'].get('stock_list', [])
    except Exception as e:
        print(f"获取热榜失败: {e}")
    return []


def get_sector_info(codes):
    """获取板块信息"""
    try:
        belong = lk.sector_stock_belong_em(codes)
        return {item['stock_code']: item['sector_name'] for item in belong}
    except:
        return {}


def get_spot_data(codes):
    """获取实时行情"""
    try:
        df = lk.stock_zh_a_spot_em()
        spot_map = {}
        for code in codes:
            stock_data = df[df['代码'] == code]
            if not stock_data.empty:
                row = stock_data.iloc[0]
                spot_map[code] = {
                    'price': float(row.get('最新价', 0) or 0),
                    'change_pct': float(row.get('涨跌幅', 0) or 0),
                }
        return spot_map
    except:
        return {}


def calculate_recommendations(stocks, sector_map, spot_map):
    """计算推荐评分"""
    # 统计板块分布
    sector_counts = {}
    concept_counts = {}
    
    for stock in stocks:
        code = stock['code']
        sector = sector_map.get(code, '')
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        
        # 统计概念
        tag = stock.get('tag') or {}
        concept_tags = tag.get('concept_tag') or []
        for concept in concept_tags:
            concept_counts[concept] = concept_counts.get(concept, 0) + 1
    
    recommendations = []
    for stock in stocks:
        code = stock['code']
        name = stock['name']
        rank = stock.get('order', 0)
        sector = sector_map.get(code, '')
        
        # 获取概念
        tag = stock.get('tag') or {}
        concept_tags = tag.get('concept_tag') or []
        
        # 获取行情
        spot = spot_map.get(code, {})
        change_pct = spot.get('change_pct', 0)
        
        # 计算评分
        concept_heat = min(len(concept_tags) / 3 * 25, 25) if concept_tags else 0
        sector_support = min(sector_counts.get(sector, 0) / 5 * 15, 15) if sector else 0
        
        # 概念梯队分
        max_group = 0
        for concept in concept_tags:
            max_group = max(max_group, concept_counts.get(concept, 0))
        concept_group = min(max_group / 5 * 15, 15)
        
        # 总分
        total_score = round(concept_heat + sector_support + concept_group + 35, 1)  # 基础分35
        
        # 生成推荐理由
        reasons = []
        if concept_heat >= 15:
            reasons.append('概念热度高')
        if sector_support >= 5:
            reasons.append('板块强势')
        elif sector_support >= 3:
            reasons.append('板块支撑')
        if concept_group >= 8:
            reasons.append('概念梯队强')
        if change_pct > 5:
            reasons.append(f'涨幅{change_pct:.1f}%')
        if not reasons:
            reasons.append('热度上升')
        
        recommendations.append({
            'rank': rank,
            'code': code,
            'name': name,
            'score': total_score,
            'change_pct': change_pct,
            'sector': sector,
            'concepts': concept_tags,
            'reasons': '、'.join(reasons),
            'sector_support': sector_counts.get(sector, 0),
            'concept_group': max_group
        })
    
    # 按评分排序
    recommendations.sort(key=lambda x: -x['score'])
    return recommendations


def generate_markdown_report(date_str=None):
    """生成Markdown格式的每日推荐报告"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    ensure_report_dir()
    
    # 获取数据
    stocks = fetch_hot_rank()
    if not stocks:
        print("无法获取热榜数据")
        return None
    
    codes = [s['code'] for s in stocks]
    sector_map = get_sector_info(codes)
    spot_map = get_spot_data(codes)
    
    # 计算推荐
    recommendations = calculate_recommendations(stocks, sector_map, spot_map)
    
    # 生成报告
    report = generate_report_content(date_str, stocks, recommendations, sector_map, spot_map)
    
    # 保存文件
    filename = f"推荐报告_{date_str}.md"
    filepath = Path(REPORT_DIR) / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"报告已生成: {filepath}")
    return filepath


def generate_report_content(date_str, stocks, recommendations, sector_map, spot_map):
    """生成报告内容"""
    
    # 统计板块分布
    sector_dist = {}
    for stock in stocks:
        sector = sector_map.get(stock['code'], '未知')
        sector_dist[sector] = sector_dist.get(sector, 0) + 1
    top_sectors = sorted(sector_dist.items(), key=lambda x: -x[1])[:5]
    
    # 统计概念分布
    concept_dist = {}
    for stock in stocks:
        tag = stock.get('tag') or {}
        for concept in tag.get('concept_tag', []):
            concept_dist[concept] = concept_dist.get(concept, 0) + 1
    top_concepts = sorted(concept_dist.items(), key=lambda x: -x[1])[:5]
    
    # 涨跌幅统计
    changes = [r['change_pct'] for r in recommendations if r['change_pct']]
    avg_change = sum(changes) / len(changes) if changes else 0
    up_count = len([c for c in changes if c > 0])
    down_count = len([c for c in changes if c < 0])
    
    report = f"""# 📊 同花顺热榜每日推荐报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**数据日期**: {date_str}

---

## 📈 市场概览

### 热度排名统计
| 指标 | 数值 |
|------|------|
| 统计股票数 | {len(stocks)} |
| 平均涨跌幅 | {avg_change:+.2f}% |
| 上涨家数 | {up_count} |
| 下跌家数 | {down_count} |
| 平盘家数 | {len(changes) - up_count - down_count} |

### 热门板块 TOP5
| 排名 | 板块 | 上榜数量 | 占比 |
|------|------|----------|------|
"""
    
    for i, (sector, count) in enumerate(top_sectors, 1):
        pct = count / len(stocks) * 100
        report += f"| {i} | {sector} | {count} | {pct:.1f}% |\n"
    
    report += f"""
### 热门概念 TOP5
| 排名 | 概念 | 上榜数量 | 占比 |
|------|------|----------|------|
"""
    
    for i, (concept, count) in enumerate(top_concepts, 1):
        pct = count / len(stocks) * 100
        report += f"| {i} | {concept} | {count} | {pct:.1f}% |\n"
    
    report += f"""
---

## ⭐ 重点推荐股票

> 评分标准：满分100分，基于概念热度、板块支撑、概念梯队、涨跌幅等多维度计算

### 🏆 强烈推荐（评分≥90分）

| 排名 | 股票代码 | 股票名称 | 评分 | 涨跌幅 | 板块 | 推荐理由 |
|------|----------|----------|------|--------|------|----------|
"""
    
    # 强烈推荐
    high_score = [r for r in recommendations if r['score'] >= 90][:10]
    for r in high_score:
        stars = '★' * int(r['score'] / 20)
        report += f"| {r['rank']} | {r['code']} | **{r['name']}** | {r['score']}{stars} | {r['change_pct']:+.2f}% | {r['sector']} | {r['reasons']} |\n"
    
    report += f"""
### 📌 值得关注（评分80-89分）

| 排名 | 股票代码 | 股票名称 | 评分 | 涨跌幅 | 板块 | 推荐理由 |
|------|----------|----------|------|--------|------|----------|
"""
    
    # 值得关注
    mid_score = [r for r in recommendations if 80 <= r['score'] < 90][:10]
    for r in mid_score:
        stars = '★' * int(r['score'] / 20)
        report += f"| {r['rank']} | {r['code']} | {r['name']} | {r['score']}{stars} | {r['change_pct']:+.2f}% | {r['sector']} | {r['reasons']} |\n"
    
    report += f"""
---

## 📊 详细推荐列表

| 排名 | 股票代码 | 股票名称 | 评分 | 涨跌幅 | 板块 | 板块支撑 | 概念梯队 | 推荐理由 |
|------|----------|----------|------|--------|------|----------|----------|----------|
"""
    
    # 全部推荐
    for r in recommendations[:50]:
        stars = '★' * int(r['score'] / 20)
        report += f"| {r['rank']} | {r['code']} | {r['name']} | {r['score']}{stars} | {r['change_pct']:+.2f}% | {r['sector']} | {r['sector_support']}只 | {r['concept_group']}只 | {r['reasons']} |\n"
    
    report += f"""
---

## 🎯 投资策略建议

### 短期策略（1-3天）
基于今日热度排名和涨跌幅数据：

1. **关注板块效应**: 
   - 今日{top_sectors[0][0]}板块有{top_sectors[0][1]}只上榜，板块效应明显
   - 建议关注该板块内尚未大涨的补涨标的

2. **概念轮动机会**:
   - {top_concepts[0][0]}概念持续活跃，可关注相关产业链延伸机会
   - 注意高位股风险，优先选择低位启动标的

3. **涨停原因分析**:
   - 关注有明确涨停原因（如业绩预增、重大合同、政策支持）的标的
   - 避免纯情绪炒作、无基本面支撑的高位股

### 中期策略（1-2周）
基于上榜持续性数据：

1. **持续跟踪**: 
   - 连续上榜≥5天的股票说明资金持续关注
   - 可建立重点观察池，等待回调后的二次启动机会

2. **板块配置**:
   - 分散配置于3-5个热门板块，降低单一板块风险
   - 优先选择有业绩支撑、估值合理的板块龙头

---

## 🔄 下次进化总结

### 本次数据采集情况
- 热榜数据: {'✅ 正常' if stocks else '❌ 异常'}
- 板块数据: {'✅ 正常' if sector_map else '❌ 异常'}
- 行情数据: {'✅ 正常' if spot_map else '❌ 异常'}
- 推荐计算: {'✅ 正常' if recommendations else '❌ 异常'}

### 系统优化建议

#### 1. 数据质量提升
- [ ] 增加盘前/盘后数据获取，解决非交易时间行情缺失问题
- [ ] 引入更多数据源（东方财富、雪球等）进行交叉验证
- [ ] 增加异常数据检测和自动修正机制

#### 2. 推荐算法优化
- [ ] 引入机器学习模型，基于历史数据训练评分权重
- [ ] 增加市场情绪指标（恐慌/贪婪指数）作为参考
- [ ] 增加个股基本面数据（PE/PB/ROE）过滤低质量标的

#### 3. 功能扩展计划
- [ ] 增加个股新闻舆情分析
- [ ] 增加龙虎榜资金流向追踪
- [ ] 增加板块轮动周期识别
- [ ] 增加回测功能，验证推荐策略历史表现

#### 4. 报告内容增强
- [ ] 增加个股技术形态分析（K线形态、支撑压力位）
- [ ] 增加资金流向分析（主力/散户资金比例）
- [ ] 增加行业对比分析（与同行业其他公司对比）
- [ ] 增加风险提示（高估值、业绩暴雷风险等）

### 待修复问题
| 优先级 | 问题描述 | 预计解决时间 |
|--------|----------|--------------|
| P0 | 非交易时间行情数据缺失 | 下次更新 |
| P1 | 推荐理由生成逻辑优化 | 持续改进 |
| P2 | 增加更多技术指标 | 后续版本 |
| P3 | 回测系统开发 | 长期规划 |

---

## 📌 免责声明

> **风险提示**: 本报告仅供参考，不构成投资建议。股市有风险，投资需谨慎。
> 
> - 报告中的评分和推荐基于历史数据和算法模型，不保证未来收益
> - 投资者应根据自身风险承受能力独立决策
> - 过往业绩不代表未来表现，据此操作风险自担

---

*报告由同花顺热度排名系统自动生成*  
*数据来源: 同花顺、东方财富*  
*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    return report


if __name__ == '__main__':
    # 生成今日报告
    filepath = generate_markdown_report()
    if filepath:
        print(f"\n报告预览（前2000字符）:\n")
        with open(filepath, 'r', encoding='utf-8') as f:
            print(f.read(2000))
            print("\n...")
