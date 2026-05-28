#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导出脚本 - 用于 GitHub Actions 定时运行
从同花顺API获取热榜数据，导出为JSON文件到 docs/data/ 目录
供 GitHub Pages 静态页面使用
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'docs' / 'data'
HISTORY_DIR = DATA_DIR / 'history'

# 创建目录
DATA_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# 导入 requests（可能在飞env中未安装）
try:
    import requests
except ImportError:
    os.system('pip install requests -q')
    import requests

# API地址
HOT_RANK_API = 'https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock?stock_type=a&type=hour&list_type=normal'
CONCEPT_HOT_API = 'https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/plate?type=concept'
INDUSTRY_HOT_API = 'https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/plate?type=industry'
HISTORY_API = 'https://dataq.10jqka.com.cn/fetch-data-server/fetch/v1/interval_data'
# 同花顺 Cookie（从GitHub Secrets读取，用于获取历史排名数据）
THS_COOKIE = os.environ.get('THS_COOKIE', '')


# ============ 工具函数 ============

def safe_json_dump(data, filepath, indent=2):
    """安全地写入JSON文件"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        print(f"  -> 已保存: {filepath}")
        return True
    except Exception as e:
        print(f"  ERROR 写入失败 {filepath}: {e}")
        return False


def make_headers():
    """生成请求头"""
    return {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
        'Accept': 'application/json',
        'Referer': 'https://eq.10jqka.com.cn/',
    }


# ============ 问财条件模板 ============

def build_iwencai_query(conditions: dict) -> str:
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
        }
    
    Returns:
        问财查询语句
    """
    parts = []
    
    # 热度范围
    hot_range = conditions.get("hot_range", 100)
    if conditions.get("new_enter"):
        parts.append(f"新进入热门股票前{hot_range}名")
    else:
        parts.append(f"热门股票前{hot_range}名")
    
    # 股价范围
    if conditions.get("price_max"):
        parts.append(f"股价低于{conditions['price_max']}元")
    
    # 排除条件
    if conditions.get("exclude_st", True):
        parts.append("非ST")
    if conditions.get("exclude_kcb", True):
        parts.append("非科创板")
    if conditions.get("exclude_bjb", True):
        parts.append("非北交所")
    if conditions.get("exclude_new"):
        parts.append(f"上市超过{conditions['exclude_new']}天")
    if conditions.get("exclude_loss", True):
        parts.append("市盈率大于0")
    
    return "；".join(parts)


def fetch_iwencai_hot(conditions: dict = None):
    """
    通过问财获取热门股票（支持多条件筛选）
    
    Args:
        conditions: 筛选条件字典，None则使用默认条件
    
    Returns:
        股票列表
    """
    # 默认条件
    if conditions is None:
        conditions = {
            "hot_range": 100,
            "price_max": 20,
            "exclude_st": True,
            "exclude_kcb": True,
            "exclude_bjb": True,
            "exclude_new": 60,
            "exclude_loss": True,
        }
    
    query = build_iwencai_query(conditions)
    print(f"  问财查询: {query}")
    
    try:
        from urllib.parse import quote
        url = f"https://www.iwencai.com/unifiedwap?question={quote(query)}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': 'https://www.iwencai.com/',
        }
        
        resp = requests.get(url, headers=headers, timeout=30)
        
        # 问财返回的是HTML，需要解析
        # 这里简化处理，返回空列表，实际使用需要解析HTML或使用问财API
        print(f"  问财返回状态: {resp.status_code}")
        print(f"  提示: 问财需要浏览器解析，建议使用前端直接调用")
        return []
        
    except Exception as e:
        print(f"  ERROR 问财查询失败: {e}")
        return []


# ============ 数据获取 ============

def fetch_hot_rank():
    """获取TOP50热榜数据（同花顺API）"""
    try:
        import requests
        resp = requests.get(HOT_RANK_API, headers=make_headers(), timeout=15)
        data = resp.json()
        if data.get('status_code') == 0 and data.get('data'):
            stocks = data['data'].get('stock_list', [])
            # 过滤ST股票
            stocks = [s for s in stocks if 'ST' not in s.get('name', '').upper() and '退' not in s.get('name', '')]
            print(f"  获取到 {len(stocks)} 只热榜股票")
            return stocks
        else:
            print(f"  API返回异常: {data}")
    except ImportError:
        print("  ERROR: 需要安装 requests 库")
    except Exception as e:
        print(f"  ERROR 获取热榜失败: {e}")
    return []


def fetch_sector_info(codes):
    """获取股票所属板块"""
    try:
        import levistock as lk
        belong = lk.sector_stock_belong_em(codes)
        result = {}
        for item in belong:
            result[item['stock_code']] = item['sector_name']
        print(f"  获取到 {len(result)} 只股票板块信息")
        return result
    except ImportError:
        print("  WARNING: levistock 未安装，跳过板块信息获取")
    except Exception as e:
        print(f"  ERROR 获取板块失败: {e}")
    return {}


def fetch_sina_prices(codes):
    """通过新浪财经API批量获取股票价格"""
    try:
        import requests as req
    except ImportError:
        print("  WARNING: requests 未安装，跳过价格获取")
        return {}

    result = {}
    
    # 将6位代码转换为新浪格式: sh600584, sz002156
    sina_codes = []
    for code in codes:
        if code.startswith('6'):
            sina_codes.append(f'sh{code}')
        elif code.startswith('0') or code.startswith('3'):
            sina_codes.append(f'sz{code}')
        else:
            sina_codes.append(f'sz{code}')
    
    # 分批请求（每次最多50只）
    batch_size = 50
    for i in range(0, len(sina_codes), batch_size):
        batch = sina_codes[i:i+batch_size]
        url = f'https://hq.sinajs.cn/list={",".join(batch)}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://finance.sina.com.cn'
        }
        try:
            r = req.get(url, headers=headers, timeout=10)
            r.encoding = 'gbk'
            for line in r.text.strip().split('\n'):
                if '="' not in line:
                    continue
                code_part = line.split('hq_str_')[1].split('=')[0] if 'hq_str_' in line else ''
                if not code_part:
                    continue
                original_code = code_part[2:]
                
                data_part = line.split('"')[1] if '"' in line else ''
                if not data_part:
                    continue
                fields = data_part.split(',')
                if len(fields) < 10:
                    continue
                
                name = fields[0]
                prev_close = float(fields[2]) if fields[2] else 0
                current_price = float(fields[3]) if fields[3] else 0
                volume = float(fields[8]) if fields[8] else 0
                turnover = float(fields[9]) if fields[9] else 0
                
                change_pct = 0
                if prev_close > 0 and current_price > 0:
                    change_pct = round((current_price - prev_close) / prev_close * 100, 2)
                
                result[original_code] = {
                    'price': current_price,
                    'change_pct': change_pct,
                    'change_amt': round(current_price - prev_close, 2) if prev_close > 0 else 0,
                    'volume': volume,
                    'turnover': turnover,
                    'market_cap': turnover
                }
        except Exception as e:
            print(f"  新浪批次请求失败: {e}")
            continue
    
    print(f"  获取到 {len(result)} 只股票实时价格")
    return result


def fetch_hot_plate(url, plate_type):
    """获取板块热榜（概念/行业）"""
    try:
        import requests
        resp = requests.get(url, headers=make_headers(), timeout=10)
        data = resp.json()
        if data.get('status_code') == 0 and data.get('data'):
            plate_list = data['data'].get('plate_list', [])
            result = []
            for item in plate_list:
                result.append({
                    'rank': item.get('order', 0),
                    'name': item.get('name', ''),
                    'code': item.get('code', ''),
                    'change_pct': round(item.get('rise_and_fall', 0), 2),
                    'heat': item.get('rate', '0'),
                    'limit_up_tag': item.get('tag', ''),
                    'hot_tag': item.get('hot_tag', ''),
                    'etf_name': item.get('etf_name', ''),
                    'etf_code': item.get('etf_product_id', ''),
                })
            print(f"  获取到 {len(result)} 条{plate_type}热榜数据")
            return result
    except Exception as e:
        print(f"  ERROR 获取{plate_type}热榜失败: {e}")
    return []


def fetch_history_from_api(code):
    """从同花顺API获取单只股票近30天排名历史
    返回: [{'date': '2026-05-26', 'rank': 15}, ...] 或空列表"""
    if not THS_COOKIE:
        return []
    
    # 判断市场码: 6开头=上海(17), 0/3开头=深圳(33)
    market = '17' if code.startswith('6') else '33'
    
    headers = {
        'Cookie': THS_COOKIE,
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Platform': 'mobileweb',
        'Source-Id': 'ths-hot-detail',
        'Origin': 'https://ms.10jqka.com.cn',
        'Referer': 'https://ms.10jqka.com.cn/thsHotDetail/',
    }
    
    now = datetime.now()
    end_ts = int(now.timestamp())
    start_ts = int((now - timedelta(days=30)).timestamp())
    
    body = {
        "indexes": [{
            "codes": [f"{market}:{code}"],
            "index_info": [{"index_id": "ths-hot-data-day-rank"}]
        }],
        "time_range": {
            "time_type": "NATURAL_DAILY",
            "start": start_ts,
            "end": end_ts
        }
    }
    
    try:
        resp = requests.post(HISTORY_API, headers=headers, json=body, timeout=15)
        data = resp.json()
        
        if data.get('status_code') != 0:
            return []
        
        if not data.get('data') or not data['data'].get('data'):
            return []
        
        time_range = data['data'].get('time_range', [])
        stock_data = data['data']['data']
        if not stock_data or not stock_data[0].get('values'):
            return []
        
        values = stock_data[0]['values'][0].get('values', [])
        
        records = []
        for i, ts in enumerate(time_range):
            if i < len(values) and values[i] and values[i] > 0 and values[i] < 2000:
                dt = datetime.fromtimestamp(int(ts))
                records.append({
                    "date": dt.strftime('%Y-%m-%d'),
                    "rank": values[i]
                })
        
        records.sort(key=lambda x: x['date'])
        return records
        
    except Exception as e:
        print(f"  [历史API] {code} 失败: {e}")
        return []


# ============ 数据处理 ============

def build_top50_data(stocks, sector_map, price_map):
    """构建排行榜数据（20元以下、非ST、非亏损，与本地Flask API一致）"""
    result = []
    for i, stock in enumerate(stocks[:100]):  # 取前100名再过滤
        code = stock['code']
        name = stock['name']
        rank = stock.get('order', i + 1)
        
        # 从API返回中提取概念标签和涨停原因
        tag = stock.get('tag') or {}
        concept_tags = tag.get('concept_tag') or []
        concept = ','.join(concept_tags) if concept_tags else sector_map.get(code, '')
        
        analyse_title = stock.get('analyse_title') or ''
        national_fund = '是' if any('大基金' in t for t in concept_tags) else ''
        
        api_change = stock.get('rise_and_fall')
        spot = price_map.get(code, {})
        change_pct = float(api_change) if api_change is not None else spot.get('change_pct', 0)
        price = spot.get('price', 0) or 0
        pe_ratio = spot.get('pe_ratio')
        
        # ========== 硬性过滤：20元以下、非ST、非亏损 ==========
        is_st = name.startswith('ST') or name.startswith('*ST')
        # 排除亏损股：
        # 1. 如果有pe_ratio数据，pe_ratio<=0视为亏损
        # 2. 如果没有pe_ratio数据，通过涨跌幅和名称判断
        if pe_ratio is not None:
            is_loss = pe_ratio <= 0  # pe_ratio为0或负数视为亏损
        else:
            is_loss = change_pct < -5 or '亏损' in name or '绩差' in name
        if is_st or is_loss or price <= 0 or price > 20:
            continue
        
        item = {
            'code': code,
            'name': name,
            'rank': rank,
            'current_rank': rank,
            'sector': sector_map.get(code, ''),
            'concept': concept,
            'price': price,
            'change_pct': change_pct,
            'change_amt': spot.get('change_amt', 0) or 0,
            'volume': spot.get('volume', 0) or 0,
            'turnover': spot.get('turnover', 0) or 0,
            'turnover_rate': 0,
            'limit_up_reason': analyse_title or '',
            'national_fund': national_fund,
            'consecutive_boards': 0,
            'continuous_days': 0
        }
        result.append(item)
    
    print(f"  构建排行榜数据: {len(result)} 条 (从100名中过滤20元以下非ST非亏损)")
    return result


def build_sector_data(stocks, sector_map, price_map):
    """构建板块分析数据（与Flask API格式一致）"""
    sector_count = {}
    sector_stocks = {}
    sector_change = {}
    
    for stock in stocks[:100]:
        code = stock['code']
        name = stock['name']
        rank = stock.get('order', 0)
        sector = sector_map.get(code, '')
        change_pct = price_map.get(code, {}).get('change_pct', 0)
        
        if not sector:
            continue
        
        if sector not in sector_count:
            sector_count[sector] = 0
            sector_stocks[sector] = []
            sector_change[sector] = []
        
        sector_count[sector] += 1
        sector_stocks[sector].append({
            'code': code,
            'name': name,
            'rank': rank,
            'change_pct': change_pct
        })
        if change_pct is not None:
            sector_change[sector].append(change_pct)
    
    result = []
    for sector, count in sorted(sector_count.items(), key=lambda x: -x[1]):
        avg_change = sum(sector_change[sector]) / len(sector_change[sector]) if sector_change[sector] else 0
        result.append({
            'sector': sector,
            'count': count,
            'avg_change': round(avg_change, 2),
            'stocks': sector_stocks[sector][:5]
        })
    
    print(f"  构建板块分析: {len(result)} 个板块")
    return result


def build_concept_data(stocks, sector_map):
    """构建概念分析数据（从热榜API的概念标签提取）"""
    concept_count = {}
    concept_stocks = {}
    
    for stock in stocks[:100]:
        code = stock['code']
        name = stock['name']
        rank = stock.get('order', 0)
        
        tag = stock.get('tag') or {}
        concept_tags = tag.get('concept_tag') or []
        if not concept_tags:
            continue
        
        for concept in concept_tags[:3]:
            if concept not in concept_count:
                concept_count[concept] = 0
                concept_stocks[concept] = []
            concept_count[concept] += 1
            concept_stocks[concept].append({
                'code': code,
                'name': name,
                'rank': rank
            })
    
    result = []
    for concept, count in sorted(concept_count.items(), key=lambda x: -x[1])[:20]:
        result.append({
            'concept': concept,
            'count': count,
            'stocks': concept_stocks[concept][:5]
        })
    
    print(f"  构建概念分析: {len(result)} 个概念")
    return result


# 加载历史辅助函数


def load_stock_history(code):
    """加载某只股票的30天历史排名JSON"""
    fpath = HISTORY_DIR / f'{code}.json'
    if fpath.exists():
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def load_weights():
    """加载推荐算法权重（无则创建默认值）"""
    wpath = DATA_DIR / 'recommendation_weights.json'
    defaults = {
        'rank_score': 25,        # 排名分权重
        'sector_score': 15,      # 板块支撑权重
        'change_score': 5,       # 涨跌幅权重
        'concept_score': 10,     # 概念丰富度权重
        'price_score': 5,        # 低价优势权重
        'continuous_score': 10,  # 连续上榜权重
        'monthly_score': 10,     # 月内频率权重
        'trend_score': 10,       # 排名趋势权重
        'best_rank_score': 10,   # 最佳排名权重
        'avg_rank_score': 10,    # 平均排名权重
        'momentum_score': 5,     # 动量分权重
        'version': 1,
        'updated': ''
    }
    if wpath.exists():
        try:
            with open(wpath, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                for k, v in defaults.items():
                    if k not in saved:
                        saved[k] = v
                return saved
        except Exception:
            pass
    return defaults


def save_weights(weights):
    """保存权重到JSON"""
    weights['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    safe_json_dump(weights, DATA_DIR / 'recommendation_weights.json')
    print(f"  权重已保存: {json.dumps({k: v for k, v in weights.items() if k != 'version' and k != 'updated'}, ensure_ascii=False)}")


def build_recommendations(top50_data, sector_data):
    """推荐算法 v3 - 与本地web_server_v2.py完全一致
    融入30天历史数据 + 动态权重 + 亏损过滤 + 走下坡路过滤 + 上榜趋势分析 + 低价优质股加权
    """
    if not top50_data:
        return []

    weights = load_weights()
    recommendations = []

    # ========== 上榜趋势分析（与本地版一致） ==========
    code_trend = {}
    for item in top50_data[:100]:
        code = item['code']
        hist = load_stock_history(code)
        h_records = hist.get('history', []) if hist else []

        if len(h_records) < 2:
            if len(h_records) == 1:
                r = h_records[0].get('rank')
                if r and r <= 50:
                    code_trend[code] = {'trend_type': 'new_to_50', 'trend_score': 8, 'trend_reason': '新上榜直冲50强'}
                else:
                    code_trend[code] = {'trend_type': 'new_to_100', 'trend_score': 5, 'trend_reason': '刚冲上100'}
            continue

        ranks = [h['rank'] for h in sorted(h_records, key=lambda x: x['date']) if h.get('rank')]

        # 检测走下坡路
        is_downhill = False
        if len(ranks) >= 3:
            recent_3 = ranks[-3:]
            if recent_3[0] <= 10 and recent_3[1] > 10 and recent_3[1] <= 50 and recent_3[2] > 50:
                is_downhill = True
            elif all(recent_3[i] < recent_3[i+1] for i in range(2)):
                if recent_3[0] <= 20 and recent_3[2] >= 50:
                    is_downhill = True
                elif recent_3[0] <= 50 and recent_3[2] > 80:
                    is_downhill = True

        if is_downhill:
            code_trend[code] = {'trend_type': 'downhill', 'trend_score': -10, 'trend_reason': '走下坡路'}
            continue

        # 检测上升趋势
        uptrend_score = 0
        uptrend_reason = ''
        if len(ranks) >= 2:
            if ranks[-2] > 100 and ranks[-1] <= 100:
                uptrend_score = 6; uptrend_reason = '刚冲上100'
            elif ranks[-2] > 100 and ranks[-1] <= 50:
                uptrend_score = 10; uptrend_reason = '新上榜直冲50强'
            elif ranks[-2] > 50 and ranks[-1] <= 50:
                uptrend_score = 7; uptrend_reason = '冲入50强'
            elif ranks[-2] > 20 and ranks[-1] <= 20:
                uptrend_score = 8; uptrend_reason = '冲入20强'
            elif ranks[-1] < ranks[-2]:
                rank_improve = ranks[-2] - ranks[-1]
                if rank_improve >= 20:
                    uptrend_score = 5; uptrend_reason = f'排名上升{rank_improve}位'

        if uptrend_score > 0:
            code_trend[code] = {'trend_type': 'uptrend', 'trend_score': uptrend_score, 'trend_reason': uptrend_reason}
        else:
            code_trend[code] = {'trend_type': 'stable', 'trend_score': 0, 'trend_reason': ''}

    # ========== 推荐评分（前50名） ==========
    for item in top50_data[:50]:
        code = item['code']
        name = item.get('name', '')
        score = 0.0
        reasons = []

        # --- 硬性过滤：20元以下、非ST、非亏损、前100名 ---
        is_st = name.startswith('ST') or name.startswith('*ST')
        change_pct = item.get('change_pct') or 0
        price = item.get('price') or 0
        # 排除亏损股：
        # 1. 如果有pe_ratio数据，pe_ratio<=0视为亏损
        # 2. 如果没有pe_ratio数据，通过涨跌幅和名称判断
        pe_ratio = item.get('pe_ratio')
        if pe_ratio is not None:
            is_loss = pe_ratio <= 0
        else:
            is_loss = change_pct < -5 or '亏损' in name or '绩差' in name

        # 硬性条件：必须满足才推荐
        if is_st or is_loss or price <= 0 or price > 20:
            continue

        # --- 走下坡路股票直接跳过 ---
        trend_info = code_trend.get(code, {'trend_type': 'stable', 'trend_score': 0, 'trend_reason': ''})
        if trend_info['trend_type'] == 'downhill':
            continue

        # 加载历史数据
        hist = load_stock_history(code)
        continuous_days = 0
        monthly_count = 0
        avg_rank = item['rank']
        best_rank = item['rank']
        rank_trend = 'stable'

        if hist:
            h_records = hist.get('history', [])
            continuous_days = hist.get('continuous_days', 0) or len(h_records)
            monthly_count = hist.get('monthly_count', 0) or len(h_records)
            avg_rank = hist.get('avg_rank', item['rank'])
            best_rank = hist.get('best_rank', item['rank'])
            rank_trend = hist.get('trend', 'stable')

            if rank_trend == 'stable' and len(h_records) >= 4:
                ranks = [r['rank'] for r in h_records if r.get('rank')]
                if len(ranks) >= 4:
                    recent_avg = sum(ranks[-3:]) / 3
                    earlier_avg = sum(ranks[:-3]) / len(ranks[:-3])
                    if recent_avg < earlier_avg - 5:
                        rank_trend = 'up'
                    elif recent_avg > earlier_avg + 5:
                        rank_trend = 'down'

        # ===== 基础排名分 =====
        rank = item['rank']
        if rank <= 5:
            score += weights['rank_score'] * 1.0
            reasons.append('排名前5')
        elif rank <= 10:
            score += weights['rank_score'] * 0.8
            reasons.append('排名前10')
        elif rank <= 20:
            score += weights['rank_score'] * 0.6
        elif rank <= 30:
            score += weights['rank_score'] * 0.4

        # ===== 板块支撑分 =====
        sector = item['sector']
        if sector:
            for s in sector_data:
                if s['sector'] == sector:
                    sector_count = s['count']
                    if sector_count >= 5:
                        score += weights['sector_score']
                        reasons.append('板块强势')
                    elif sector_count >= 3:
                        score += weights['sector_score'] * 0.7
                        reasons.append('板块支撑')
                    break

        # ===== 涨跌幅分 =====
        if change_pct and change_pct >= 9.5:
            score += weights['change_score']
            reasons.append('涨停')
        elif change_pct and change_pct >= 5:
            score += weights['change_score'] * 0.6
        elif change_pct and change_pct >= 3:
            score += weights['change_score'] * 0.4

        # ===== 概念丰富度分 =====
        if item['concept']:
            concept_count = len(item['concept'].split(','))
            score += min(concept_count * (weights['concept_score'] / 3), weights['concept_score'])
            if concept_count >= 3:
                reasons.append('概念丰富')

        # ===== 低价优势分 =====
        if price and price > 0 and price <= 10:
            score += weights['price_score']
            reasons.append('低价优势')
        elif price and price <= 15:
            score += weights['price_score'] * 0.6

        # ===== 连续上榜分 =====
        if continuous_days >= 10:
            score += weights['continuous_score']
            reasons.append(f'连续{continuous_days}天上榜')
        elif continuous_days >= 5:
            score += weights['continuous_score'] * 0.7
            reasons.append(f'连续{continuous_days}天上榜')
        elif continuous_days >= 3:
            score += weights['continuous_score'] * 0.4

        # ===== 月内频率分 =====
        if monthly_count >= 20:
            score += weights['monthly_score']
            reasons.append('高频上榜')
        elif monthly_count >= 10:
            score += weights['monthly_score'] * 0.6

        # ===== 排名趋势分 =====
        if rank_trend == 'up':
            score += weights['trend_score']
            reasons.append('排名上升趋势')
        elif rank_trend == 'down':
            score -= weights['trend_score'] * 0.3

        # ===== 最佳排名分 =====
        if best_rank <= 3:
            score += weights['best_rank_score']
            reasons.append('曾进前3')
        elif best_rank <= 10:
            score += weights['best_rank_score'] * 0.6
            reasons.append('曾进前10')

        # ===== 平均排名分 =====
        if avg_rank <= 20:
            score += weights['avg_rank_score']
        elif avg_rank <= 50:
            score += weights['avg_rank_score'] * 0.5

        # ===== 动量分 =====
        if hist and len(hist.get('history', [])) >= 3:
            h = hist['history']
            recent = [r['rank'] for r in h[-3:] if r.get('rank')]
            earlier = [r['rank'] for r in h[:-3] if r.get('rank')]
            if recent and earlier:
                recent_avg_rank = sum(recent) / len(recent)
                earlier_avg_rank = sum(earlier) / len(earlier)
                improvement = earlier_avg_rank - recent_avg_rank
                if improvement > 100:
                    score += weights['momentum_score']
                    reasons.append('排名飙升')

        # ===== 低价优质股加权（与本地版一致） =====
        low_price_quality_score = 0
        if not is_st and not is_loss:
            if 0 < price <= 10 and rank <= 50:
                low_price_quality_score = 5
            elif 0 < price <= 15 and rank <= 30:
                low_price_quality_score = 3
            elif 0 < price <= 20 and rank <= 20:
                low_price_quality_score = 2
        score += low_price_quality_score
        if low_price_quality_score >= 5:
            reasons.append('低价优质股')

        # ===== 上榜趋势分析加分（与本地版一致） =====
        trend_score = trend_info['trend_score']
        trend_reason = trend_info['trend_reason']
        score += trend_score
        if trend_reason:
            reasons.append(trend_reason)

        # ===== 风险评级 =====
        risk_level = '低风险'
        if change_pct and change_pct >= 9.5:
            risk_level = '追高风险'
        elif change_pct and change_pct >= 7:
            risk_level = '高风险'
        elif change_pct and change_pct >= 5:
            risk_level = '中风险'
        elif change_pct and change_pct <= -5:
            risk_level = '高风险'

        # ===== 止损止盈 =====
        stop_loss = round(price * 0.95, 2) if price and price > 0 else None
        take_profit1 = round(price * 1.05, 2) if price and price > 0 else None
        take_profit2 = round(price * 1.10, 2) if price and price > 0 else None

        if not reasons:
            reasons.append('热度上榜')

        recommendations.append({
            'code': code,
            'name': name,
            'rank': rank,
            'score': round(score, 1),
            'continuous_days': continuous_days,
            'monthly_count': monthly_count,
            'avg_rank': avg_rank,
            'best_rank': best_rank,
            'trend': rank_trend,
            'reasons': '、'.join(reasons),
            'sector': sector,
            'concept': item['concept'],
            'price': price,
            'change_pct': change_pct,
            'risk_level': risk_level,
            'stop_loss': stop_loss,
            'take_profit1': take_profit1,
            'take_profit2': take_profit2,
            'consecutive_boards': 0
        })

    recommendations.sort(key=lambda x: -x['score'])
    recs = recommendations[:8]
    print(f"  构建推荐数据: {len(recs)} 条 (算法v{weights.get('version', 1)})")
    return recs


# ============ 每日复盘系统 ============
def run_daily_review(top50_data, recommendations):
    """
    每日复盘：
    1. 保存本次推荐快照
    2. 对比上次推荐 → 验证结果
    3. 根据历史成功率调整权重
    """
    today = datetime.now().strftime('%Y-%m-%d')
    hist_path = DATA_DIR / 'recommendation_history.json'

    # 加载历史推荐记录
    history = []
    if hist_path.exists():
        try:
            with open(hist_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []

    # 1. 保存本次推荐快照
    today_snapshot = {
        'date': today,
        'stocks': [{'code': r['code'], 'name': r['name'], 'rank': r['rank'],
                     'score': r['score'], 'price': r['price'],
                     'change_pct': r['change_pct'], 'reasons': r['reasons']}
                   for r in recommendations]
    }
    history.append(today_snapshot)

    # 只保留最近60天
    if len(history) > 60:
        history = history[-60:]

    safe_json_dump(history, hist_path)

    # 2. 对比上次推荐验证结果（需要至少2条记录）
    if len(history) < 2:
        print("  复盘: 首次推荐，暂无对比数据")
        return

    prev = history[-2]
    prev_date = prev.get('date', '')
    print(f"\n  ==== 每日复盘 ({prev_date} → {today}) ====")

    # 构建今日排名映射
    today_rank_map = {s['code']: s for s in top50_data}
    today_price_map = {}
    for s in top50_data:
        if s.get('price') and s['price'] > 0:
            today_price_map[s['code']] = s['price']

    # 统计上次推荐表现
    results = []
    for prev_stock in prev.get('stocks', []):
        code = prev_stock['code']
        name = prev_stock.get('name', '')

        today_info = today_rank_map.get(code, {})
        prev_price = prev_stock.get('price', 0)
        today_price = today_price_map.get(code, prev_price)

        outcome = {
            'code': code, 'name': name,
            'prev_rank': prev_stock.get('rank'),
            'prev_price': prev_price,
            'today_rank': today_info.get('rank', '-'),
            'today_price': today_price,
            'price_change': round((today_price - prev_price) / prev_price * 100, 2) if prev_price and prev_price > 0 else 0,
            'still_in_top50': code in today_rank_map,
            'rank_change': prev_stock.get('rank', 0) - today_info.get('rank', 0) if code in today_rank_map else 0
        }
        results.append(outcome)

        status = '✅' if outcome['price_change'] > 0 else '❌'
        print(f"  {status} {name}({code}): "
              f"排名{outcome['prev_rank']}→{outcome['today_rank']} | "
              f"¥{prev_price}→¥{today_price}({outcome['price_change']:+.1f}%)")

    # 计算成功率
    win_count = sum(1 for r in results if r['price_change'] > 0)
    total = len(results)
    win_rate = win_count / total * 100 if total > 0 else 0
    rank_improved = sum(1 for r in results if r['rank_change'] > 0)

    print(f"\n  复盘结果: {win_count}/{total} 上涨 | 胜率={win_rate:.0f}% | "
          f"排名提升={rank_improved}只")

    # 保存复盘结果
    review_results = []
    review_path = DATA_DIR / 'review_results.json'
    if review_path.exists():
        try:
            with open(review_path, 'r', encoding='utf-8') as f:
                review_results = json.load(f)
        except Exception:
            review_results = []

    review_results.append({
        'review_date': today,
        'target_date': prev_date,
        'results': results,
        'win_rate': round(win_rate, 1),
        'win_count': win_count,
        'total': total,
        'rank_improved': rank_improved
    })
    if len(review_results) > 90:
        review_results = review_results[-90:]
    safe_json_dump(review_results, review_path)

    # 3. 动态调整权重（基于近期平均胜率）
    if len(review_results) >= 3:
        recent_3 = review_results[-3:]
        avg_win_rate = sum(r['win_rate'] for r in recent_3) / len(recent_3)
        weights = load_weights()

        # 根据整体胜率调整：胜率高 → 略微增加活跃维度权重
        if avg_win_rate >= 60:
            # 表现好，增加趋势、动量权重
            weights['trend_score'] = min(15, weights['trend_score'] + 1)
            weights['momentum_score'] = min(10, weights['momentum_score'] + 1)
            weights['version'] += 1
            save_weights(weights)
            print(f"  权重调整↑ 胜率{avg_win_rate:.0f}% → 趋势+1 动量+1 (v{weights['version']})")
        elif avg_win_rate < 40:
            # 表现差，降低风险维度，回归基础
            weights['change_score'] = max(3, weights['change_score'] - 1)
            weights['momentum_score'] = max(2, weights['momentum_score'] - 1)
            weights['version'] += 1
            save_weights(weights)
            print(f"  权重调整↓ 胜率{avg_win_rate:.0f}% → 涨跌-1 动量-1 (v{weights['version']})")
    else:
        print("  复盘: 数据不足，暂不调整权重")

    return results


def build_sentiment(top50_data):
    """构建市场情绪数据"""
    changes = [item['change_pct'] for item in top50_data[:100] if item.get('change_pct') is not None]
    
    if not changes:
        return {'up': 0, 'down': 0, 'flat': 0, 'limit_up': 0, 'limit_down': 0, 'sentiment': 50}
    
    up = sum(1 for x in changes if x > 0)
    down = sum(1 for x in changes if x < 0)
    flat = sum(1 for x in changes if x == 0)
    limit_up = sum(1 for x in changes if x >= 9.5)
    limit_down = sum(1 for x in changes if x <= -9.5)
    
    total = len(changes)
    sentiment = round((up / total * 50) + (limit_up / total * 30) + 20, 1)
    sentiment = min(100, max(0, sentiment))
    
    result = {
        'up': up, 'down': down, 'flat': flat,
        'limit_up': limit_up, 'limit_down': limit_down,
        'sentiment': sentiment,
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    print(f"  构建情绪指数: {sentiment}")
    return result


# ============ 主流程 ============

def main():
    print("=" * 60)
    print("热度排名数据导出脚本")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 1. 获取热榜数据
    print("\n[1/6] 获取热榜数据...")
    stocks = fetch_hot_rank()
    if not stocks:
        print("ERROR: 无法获取热榜数据，终止导出")
        return False
    codes = [s['code'] for s in stocks[:100]]
    
    # 2. 获取板块信息
    print("\n[2/6] 获取板块信息...")
    sector_map = fetch_sector_info(codes)
    
    # 3. 获取实时价格
    print("\n[3/6] 获取实时价格...")
    price_map = fetch_sina_prices(codes)
    
    # 4. 获取板块热榜
    print("\n[4/6] 获取热榜概念/行业数据...")
    concept_hot_data = fetch_hot_plate(CONCEPT_HOT_API, '概念')
    industry_hot_data = fetch_hot_plate(INDUSTRY_HOT_API, '行业')
    
    # 5. 构建并保存数据
    print("\n[5/6] 构建业务数据...")
    
    # 5a. TOP50
    top50_data = build_top50_data(stocks, sector_map, price_map)
    safe_json_dump(top50_data, DATA_DIR / 'top50.json')
    
    # 5b. 板块分析
    sector_data = build_sector_data(stocks, sector_map, price_map)
    safe_json_dump(sector_data, DATA_DIR / 'sector.json')
    
    # 5c. 概念分析
    concept_data = build_concept_data(stocks, sector_map)
    safe_json_dump(concept_data, DATA_DIR / 'concept.json')
    
    # 5d. 概念热榜
    safe_json_dump(concept_hot_data, DATA_DIR / 'concept_hot.json')
    
    # 5e. 行业热榜
    safe_json_dump(industry_hot_data, DATA_DIR / 'industry_hot.json')
    
    # 5f. 推荐股票
    recommendations_data = build_recommendations(top50_data, sector_data)
    safe_json_dump(recommendations_data, DATA_DIR / 'recommendations.json')
    
    # 运行每日复盘
    run_daily_review(top50_data, recommendations_data)
    
    # 5g. 情绪指数
    sentiment_data = build_sentiment(top50_data)
    safe_json_dump(sentiment_data, DATA_DIR / 'sentiment.json')
    
    # 5h. 每个股票的历史数据（从同花顺API获取近30天排名，取前100名）
    print("\n[6/6] 导出个股历史数据...")
    history_count = 0
    for i, stock in enumerate(stocks[:100]):  # 用原始前100名，不是过滤后的
        code = stock['code']
        name = stock['name']
        rank = stock.get('order', i + 1)
        spot = price_map.get(code, {})
        price = spot.get('price', 0) or 0
        change_pct = float(stock.get('rise_and_fall')) if stock.get('rise_and_fall') else spot.get('change_pct', 0)
        
        # 尝试从同花顺API获取历史数据
        api_records = []
        if THS_COOKIE:
            api_records = fetch_history_from_api(code)
        
        # 如果没有API数据，用当前快照作为fallback
        if not api_records:
            history = [{
                'date': datetime.now().strftime('%Y-%m-%d'),
                'rank': rank,
                'price': price,
                'change_pct': change_pct
            }]
        else:
            history = api_records
            # 确保当天数据包含price
            today_str = datetime.now().strftime('%Y-%m-%d')
            has_today = any(h.get('date') == today_str for h in history)
            if not has_today:
                history.append({
                    'date': today_str,
                    'rank': rank,
                    'price': price,
                    'change_pct': change_pct
                })
        
        # 计算统计
        ranks = [r['rank'] for r in history if r.get('rank')]
        history_item = {
            'code': code,
            'name': name,
            'history': history,
            'continuous_days': len(history),
            'monthly_count': len(history),
            'avg_rank': round(sum(ranks) / len(ranks), 1) if ranks else rank,
            'best_rank': min(ranks) if ranks else rank,
            'trend': 'stable'
        }
        safe_json_dump(history_item, HISTORY_DIR / f'{code}.json')
        history_count += 1
        
        # 添加延迟避免被封
        if i % 5 == 4:  # 每5只休息一下
            time.sleep(0.3)
        else:
            time.sleep(0.1)
    
    print(f"  ✓ 导出 {history_count} 只股票历史数据")
    
    # 6. 保存元数据（与前端docs/index.html格式一致）
    # 统计所有历史数据中的日期
    all_dates = set()
    history_dir = HISTORY_DIR
    if history_dir.exists():
        for f in history_dir.glob('*.json'):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    hdata = json.load(fh)
                    for h in hdata.get('history', []):
                        if h.get('date'):
                            all_dates.add(h['date'])
            except:
                pass
    
    available_dates = sorted(all_dates, reverse=True) if all_dates else [datetime.now().strftime('%Y-%m-%d')]
    latest_date = available_dates[0] if available_dates else datetime.now().strftime('%Y-%m-%d')
    
    meta = {
        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'stock_count': len(top50_data),
        'data_version': '3.0',
        'unique_stocks': len(top50_data),
        'total_records': len(top50_data) * len(available_dates) if available_dates else len(top50_data),
        'dates': len(available_dates),
        'latest_date': latest_date,
        'available_dates': available_dates
    }
    safe_json_dump(meta, DATA_DIR / 'meta.json')
    
    print("\n" + "=" * 60)
    print("数据导出完成！")
    print(f"输出目录: {DATA_DIR}")
    print("=" * 60)
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
