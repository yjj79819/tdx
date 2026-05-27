#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web服务 V2 - 暗色系 + 完整数据字段 + 排序功能 + 历史统计 + 推荐系统 + 每日报告"""
import sqlite3
import requests
import threading
import time
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file, make_response
import levistock as lk
import akshare as ak

# 导入报告生成器
from report_generator import generate_markdown_report

app = Flask(__name__)

# 使用相对路径（基于脚本所在目录），兼容GitHub部署
import os
# 清除外部DB_PATH环境变量，使用本地文件
os.environ.pop('DB_PATH', None)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'hot_rank.db'
PORT = int(os.environ.get('PORT', 5000))
REPORT_DIR = BASE_DIR / 'reports'

HOT_RANK_API = 'https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock?stock_type=a&type=hour&list_type=normal'
HISTORY_API = 'https://dataq.10jqka.com.cn/fetch-data-server/fetch/v1/interval_data'
# 同花顺 Cookie (登录后从浏览器复制，用于获取历史排名数据)
# 优先读环境变量，其次读本地 cookie.txt 文件
THS_COOKIE = os.environ.get('THS_COOKIE', '')
if not THS_COOKIE:
    cookie_file = BASE_DIR / 'cookie.txt'
    if cookie_file.exists():
        THS_COOKIE = cookie_file.read_text(encoding='utf-8').strip()
        if THS_COOKIE:
            print(f"[Cookie] 从 {cookie_file} 加载 ({len(THS_COOKIE)} 字符)")
    if not THS_COOKIE:
        print("[Cookie] ⚠ 未设置 THS_COOKIE，将无法获取新数据")

# 推荐算法权重持久化路径
WEIGHT_PATH = BASE_DIR / 'docs' / 'data' / 'recommendation_weights.json'

def load_weights():
    """加载推荐算法权重"""
    defaults = {
        'concept_heat': 20, 'persistence': 20, 'frequency': 15,
        'sector_support': 15, 'concept_group': 10,
        'speed': 10, 'price': 5, 'board': 3, 'tech': 2,
        'liquidity': 0, 'ta': 6, 'version': 1, 'updated': ''
    }
    if WEIGHT_PATH.exists():
        try:
            with open(WEIGHT_PATH, 'r', encoding='utf-8') as f:
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
    try:
        with open(WEIGHT_PATH, 'w', encoding='utf-8') as f:
            json.dump(weights, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[权重] 保存失败: {e}")

update_status = {'running': False, 'last_time': None, 'message': ''}

# ============ 数据库 ============
def init_db():
    """初始化数据库 - 扩展字段"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 检查表是否存在
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stocks'")
    table_exists = c.fetchone() is not None

    if table_exists:
        # 检查并添加新字段
        c.execute('PRAGMA table_info(stocks)')
        existing_cols = [col[1] for col in c.fetchall()]

        new_cols = {
            'concept': 'TEXT',
            'price': 'REAL',
            'change_pct': 'REAL',
            'change_amt': 'REAL',
            'volume': 'REAL',
            'turnover': 'REAL',
            'turnover_rate': 'REAL',
            'pe_ratio': 'REAL',
            'market_cap': 'REAL',
            'limit_up_reason': 'TEXT',
            'national_fund': 'TEXT',
            'consecutive_boards': 'INTEGER',
            'first_limit_time': 'TEXT',
            'seal_amount': 'REAL'
        }

        for col_name, col_type in new_cols.items():
            if col_name not in existing_cols:
                try:
                    c.execute(f'ALTER TABLE stocks ADD COLUMN {col_name} {col_type}')
                    print(f"添加字段: {col_name}")
                except Exception as e:
                    print(f"添加字段失败 {col_name}: {e}")
    else:
        # 创建新表
        c.execute('''CREATE TABLE stocks (
            code TEXT PRIMARY KEY,
            name TEXT,
            market TEXT,
            current_rank INTEGER,
            sector TEXT,
            concept TEXT,
            price REAL,
            change_pct REAL,
            change_amt REAL,
            volume REAL,
            turnover REAL,
            turnover_rate REAL,
            pe_ratio REAL,
            market_cap REAL,
            limit_up_reason TEXT,
            national_fund TEXT,
            consecutive_boards INTEGER,
            first_limit_time TEXT,
            seal_amount REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

    # 热度排名历史表 - 带迁移
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hot_rank_history'")
    hist_exists = c.fetchone() is not None
    
    if hist_exists:
        c.execute('PRAGMA table_info(hot_rank_history)')
        hist_cols = [col[1] for col in c.fetchall()]
        for col_name, col_type in {'price': 'REAL', 'change_pct': 'REAL'}.items():
            if col_name not in hist_cols:
                try:
                    c.execute(f'ALTER TABLE hot_rank_history ADD COLUMN {col_name} {col_type}')
                    print(f"hot_rank_history 添加字段: {col_name}")
                except Exception as e:
                    print(f"hot_rank_history 添加字段失败 {col_name}: {e}")
    else:
        c.execute('''CREATE TABLE hot_rank_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            date TEXT,
            rank INTEGER,
            price REAL,
            change_pct REAL,
            UNIQUE(code, date)
        )''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_code ON hot_rank_history(code)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_date ON hot_rank_history(date)')
    conn.commit()
    conn.close()
    print("数据库初始化完成")

def get_stats():
    """获取数据库统计信息"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM stocks')
    stock_count = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM hot_rank_history')
    record_count = c.fetchone()[0]
    c.execute('SELECT COUNT(DISTINCT date) FROM hot_rank_history')
    day_count = c.fetchone()[0]
    c.execute('SELECT MIN(date), MAX(date) FROM hot_rank_history')
    dr = c.fetchone()
    conn.close()
    return {'stock_count': stock_count, 'record_count': record_count, 'day_count': day_count, 'date_min': dr[0], 'date_max': dr[1]}

def get_dates():
    """获取所有有数据的日期列表"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT DISTINCT date FROM hot_rank_history ORDER BY date DESC')
    dates = [r[0] for r in c.fetchall()]
    conn.close()
    return dates

def get_top50_with_full_data(date):
    """获取TOP50完整数据"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT h.code, COALESCE(s.name, h.name, h.code) as name, h.rank, h.current_rank, 
                        COALESCE(s.sector, h.sector, '') as sector, COALESCE(s.concept, h.concept, '') as concept,
                        h.price, h.change_pct, h.change_amt, h.volume, h.turnover,
                        h.turnover_rate, h.limit_up_reason, h.national_fund, h.consecutive_boards
                 FROM hot_rank_history h
                 LEFT JOIN stocks s ON h.code = s.code
                 WHERE h.date = ? AND h.rank IS NOT NULL
                 ORDER BY h.rank ASC LIMIT 50''', (date,))
    data = c.fetchall()
    conn.close()
    return data

def get_top100(date):
    """获取TOP100用于板块分析"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT h.code, h.name, h.rank, h.sector, h.concept, h.change_pct
                 FROM hot_rank_history h
                 WHERE h.date = ? AND h.rank IS NOT NULL
                 ORDER BY h.rank ASC LIMIT 100''', (date,))
    data = c.fetchall()
    conn.close()
    return data

# ============ 数据获取 ============
def fetch_hot_rank():
    """获取热榜数据"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
        'Accept': 'application/json',
    }
    try:
        resp = requests.get(HOT_RANK_API, headers=headers, timeout=15)
        data = resp.json()
        if data.get('status_code') == 0 and data.get('data'):
            stocks = data['data'].get('stock_list', [])
            # 过滤ST股票
            stocks = [s for s in stocks if 'ST' not in s.get('name', '').upper() and '退' not in s.get('name', '')]
            return stocks
    except Exception as e:
        print(f"获取热榜失败: {e}")
    return []

def fetch_sector_info(codes):
    """获取股票所属板块"""
    try:
        belong = lk.sector_stock_belong_em(codes)
        return {item['stock_code']: item['sector_name'] for item in belong}
    except Exception as e:
        print(f"获取板块失败: {e}")
        return {}

def fetch_spot_data():
    """获取实时行情数据（主方案：新浪财经API）"""
    try:
        df = lk.stock_zh_a_spot_em()
        return df
    except Exception as e:
        print(f"levistock行情失败: {e}")

    # 备选方案：新浪财经API（非交易时间也能返回最后收盘价）
    try:
        return fetch_sina_spot_all()
    except Exception as e:
        print(f"新浪行情也失败: {e}")
        return None

def fetch_sina_spot_all():
    """通过新浪财经API获取全A股行情（非交易时间也能用）"""
    import requests as req
    # 先获取沪深A股列表（用东方财富的股票列表API获取代码）
    # 简化方案：直接传入codes列表
    return None  # 占位，实际在do_update中按需调用

def fetch_sina_prices(codes):
    """通过新浪财经API批量获取股票价格（每次最多50只）
    返回: {code: {price, change_pct, market_cap}}"""
    import requests as req
    result = {}
    
    # 将6位代码转换为新浪格式: sh600584, sz002156
    sina_codes = []
    for code in codes:
        if code.startswith('6'):
            sina_codes.append(f'sh{code}')
        elif code.startswith('0') or code.startswith('3'):
            sina_codes.append(f'sz{code}')
        else:
            sina_codes.append(f'sz{code}')  # 北交所等
    
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
                # 提取代码
                code_part = line.split('hq_str_')[1].split('=')[0] if 'hq_str_' in line else ''
                if not code_part:
                    continue
                original_code = code_part[2:]  # 去掉sh/sz前缀
                
                # 提取数据
                data_part = line.split('"')[1] if '"' in line else ''
                if not data_part:
                    continue
                fields = data_part.split(',')
                if len(fields) < 10:
                    continue
                
                name = fields[0]
                open_price = float(fields[1]) if fields[1] else 0
                prev_close = float(fields[2]) if fields[2] else 0
                current_price = float(fields[3]) if fields[3] else 0
                high = float(fields[4]) if fields[4] else 0
                low = float(fields[5]) if fields[5] else 0
                volume = float(fields[8]) if fields[8] else 0
                turnover = float(fields[9]) if fields[9] else 0
                
                # 计算涨跌幅
                change_pct = 0
                if prev_close > 0 and current_price > 0:
                    change_pct = round((current_price - prev_close) / prev_close * 100, 2)
                
                # 估算总市值（新浪不直接提供，用成交量*价格估算流通市值）
                market_cap = turnover  # 成交额作为流通市值近似
                
                result[original_code] = {
                    'price': current_price,
                    'change_pct': change_pct,
                    'change_amt': round(current_price - prev_close, 2) if prev_close > 0 else 0,
                    'volume': volume,
                    'turnover': turnover,
                    'market_cap': market_cap
                }
        except Exception as e:
            print(f"  新浪批次请求失败: {e}")
            continue
    
    return result

def fetch_price_backup(code):
    """非交易时间用akshare历史行情获取最近交易日收盘数据（单只股票）"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20250101", adjust="qfq")
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            return {
                'price': float(latest.get('收盘', 0)),
                'change_pct': float(latest.get('涨跌幅', 0))
            }
    except Exception as e:
        print(f"akshare获取 {code} 历史行情失败: {e}")
    return {}

def fetch_concept_data(codes):
    """获取股票概念数据"""
    try:
        concepts = {}
        for code in codes[:50]:
            try:
                info = lk.stock_individual_info_em(code)
                if info is not None and len(info) > 0:
                    concept_str = info.get('概念', '') if isinstance(info, dict) else ''
                    if not concept_str and isinstance(info, dict):
                        concept_str = info.get('所属概念', '')
                    concepts[code] = concept_str
            except:
                pass
        return concepts
    except Exception as e:
        print(f"获取概念失败: {e}")
        return {}

# ============ 板块分析 ============
def analyze_sectors(date):
    """分析各板块上榜股票数量"""
    stocks = get_top100(date)
    if not stocks:
        return []

    sector_count = {}
    sector_stocks = {}
    sector_change = {}

    for code, name, rank, sector, concept, change_pct in stocks:
        if sector:
            if sector not in sector_count:
                sector_count[sector] = 0
                sector_stocks[sector] = []
                sector_change[sector] = []
            sector_count[sector] += 1
            sector_stocks[sector].append({'code': code, 'name': name, 'rank': rank, 'change_pct': change_pct})
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
    return result

def analyze_concepts(date):
    """分析各概念上榜股票数量"""
    stocks = get_top100(date)
    if not stocks:
        return []

    concept_count = {}
    concept_stocks = {}

    for code, name, rank, sector, concept, change_pct in stocks:
        if concept:
            concepts = [c.strip() for c in str(concept).split(',') if c.strip()]
            for c in concepts[:3]:
                if c not in concept_count:
                    concept_count[c] = 0
                    concept_stocks[c] = []
                concept_count[c] += 1
                concept_stocks[c].append({'code': code, 'name': name, 'rank': rank})

    result = []
    for concept, count in sorted(concept_count.items(), key=lambda x: -x[1])[:20]:
        result.append({
            'concept': concept,
            'count': count,
            'stocks': concept_stocks[concept][:5]
        })
    return result

# ============ 30天历史统计 ============
def fetch_history_from_api(code):
    """从同花顺API获取单只股票近30天排名历史
    返回: [{'date': '2026-05-26', 'rank': 15}, ...] 或空列表"""
    if not THS_COOKIE:
        print(f"[历史API] 无Cookie，跳过 {code}")
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
    
    # 30天时间范围
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
            print(f"[历史API] {code} 请求失败: {data.get('status_msg')}")
            return []
        
        if not data.get('data') or not data['data'].get('data'):
            print(f"[历史API] {code} 无返回数据")
            return []
        
        time_range = data['data'].get('time_range', [])
        stock_data = data['data']['data']
        if not stock_data or not stock_data[0].get('values'):
            return []
        
        values = stock_data[0]['values'][0].get('values', [])
        
        # 筛选有效排名(>0的值)并按日期排序
        records = []
        for i, ts in enumerate(time_range):
            if i < len(values) and values[i] and values[i] > 0 and values[i] < 2000:
                dt = datetime.fromtimestamp(int(ts))
                records.append({
                    "date": dt.strftime('%Y-%m-%d'),
                    "rank": values[i]
                })
        
        # 按日期排序（最新在前便于显示）
        records.sort(key=lambda x: x['date'])
        print(f"[历史API] {code} 获取 {len(records)} 天数据")
        return records
        
    except Exception as e:
        print(f"[历史API] {code} 获取失败: {e}")
        return []

def save_history_to_db(code, records):
    """将API获取的历史排名数据保存到数据库"""
    if not records:
        return 0
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    saved = 0
    for r in records:
        try:
            # 使用 INSERT OR IGNORE 避免重复
            c.execute('''INSERT OR IGNORE INTO hot_rank_history (code, date, rank)
                         VALUES (?, ?, ?)''', (code, r['date'], r['rank']))
            if c.rowcount > 0:
                saved += 1
        except Exception as e:
            print(f"[DB] 保存历史数据失败 {code}/{r.get('date')}: {e}")
    
    conn.commit()
    conn.close()
    print(f"[DB] {code} 保存 {saved} 条历史数据")
    return saved

def get_stock_history(code):
    """获取某只股票最近30天的排名历史及统计指标"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 计算30天前的日期
    today = datetime.now().strftime('%Y-%m-%d')
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    # 查询30天内的排名记录
    c.execute('''SELECT date, rank, price, change_pct
                 FROM hot_rank_history
                 WHERE code = ? AND date >= ? AND rank IS NOT NULL
                 ORDER BY date ASC''', (code, thirty_days_ago))
    records = c.fetchall()
    conn.close()

    if not records:
        # DB无数据，尝试从同花顺API获取
        api_records = fetch_history_from_api(code)
        if api_records:
            save_history_to_db(code, api_records)
            # 重新查询DB
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('''SELECT date, rank, price, change_pct
                         FROM hot_rank_history
                         WHERE code = ? AND date >= ? AND rank IS NOT NULL
                         ORDER BY date ASC''', (code, thirty_days_ago))
            records = c.fetchall()
            conn.close()
        
        if not records:
            return {'code': code, 'history': [], 'continuous_days': 0, 'monthly_count': 0,
                    'avg_rank': 0, 'best_rank': 0, 'trend': 'stable', 'from_api': bool(api_records)}

    # 构建历史数据
    history = [{'date': r[0], 'rank': r[1], 'price': r[2], 'change_pct': r[3]} for r in records]

    # 计算统计指标
    ranks = [r['rank'] for r in history]
    dates_list = [r['date'] for r in history]

    # 连续上榜天数：从最新数据日期往前连续有记录的天数
    continuous_days = 0
    latest_date_str = records[-1][0] if records else datetime.now().strftime('%Y-%m-%d')
    check_date = datetime.strptime(latest_date_str, '%Y-%m-%d')
    for _ in range(30):
        date_str = check_date.strftime('%Y-%m-%d')
        if date_str in dates_list:
            continuous_days += 1
        else:
            break
        check_date -= timedelta(days=1)

    # 30天内上榜总次数
    monthly_count = len(records)

    # 平均排名
    avg_rank = round(sum(ranks) / len(ranks), 1)

    # 最佳排名（数值最小）
    best_rank = min(ranks)

    # 排名趋势：最近3天平均 vs 之前平均
    if len(ranks) >= 4:
        recent_avg = sum(ranks[-3:]) / 3
        earlier_avg = sum(ranks[:-3]) / len(ranks[:-3])
        if recent_avg < earlier_avg - 2:
            trend = 'up'  # 排名数值变小 = 排名上升
        elif recent_avg > earlier_avg + 2:
            trend = 'down'  # 排名数值变大 = 排名下降
        else:
            trend = 'stable'
    else:
        trend = 'stable'

    return {
        'code': code,
        'history': history,
        'continuous_days': continuous_days,
        'monthly_count': monthly_count,
        'avg_rank': avg_rank,
        'best_rank': best_rank,
        'trend': trend
    }

def get_continuous_days_bulk(codes):
    """批量获取连续上榜天数（用于表格显示）"""
    if not codes:
        return {}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 获取数据库中最新日期（而非当前日期，避免非交易日导致连续天数为0）
    c.execute('SELECT MAX(date) FROM hot_rank_history')
    row = c.fetchone()
    latest_date = row[0] if row and row[0] else datetime.now().strftime('%Y-%m-%d')

    # 获取最近30天所有日期的记录
    thirty_days_ago = (datetime.strptime(latest_date, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d')
    placeholders = ','.join(['?'] * len(codes))
    c.execute(f'''SELECT code, date FROM hot_rank_history
                  WHERE code IN ({placeholders}) AND date >= ? AND rank IS NOT NULL
                  ORDER BY date ASC''', codes + [thirty_days_ago])
    rows = c.fetchall()
    
    # 获取所有有数据的交易日（按日期倒序）
    c.execute('SELECT DISTINCT date FROM hot_rank_history WHERE date >= ? ORDER BY date DESC', (thirty_days_ago,))
    all_trading_days = [r[0] for r in c.fetchall()]
    conn.close()

    # 按code分组
    code_dates = {}
    for code, date in rows:
        if code not in code_dates:
            code_dates[code] = set()
        code_dates[code].add(date)

    # 计算每只股票的连续上榜天数（从最新交易日开始往前算，只看交易日）
    result = {}
    for code in codes:
        dates_set = code_dates.get(code, set())
        continuous = 0
        for trading_day in all_trading_days:
            if trading_day in dates_set:
                continuous += 1
            else:
                break
        result[code] = continuous
    return result

# ============ 技术分析评分 ============
def get_technical_scores(codes):
    """
    使用akshare获取技术指标，为每只股票计算技术评分(0-6分)。
    因子:
      - MA5 vs MA10: MA5 > MA10 → 看多 (+2分)
      - MACD柱状图 > 0 且递增 → 看多 (+2分)
      - 近5日均量 > 前5日均量 → 放量 (+1分)
      - 当前价 > MA20 → 站上中期均线 (+1分)
    总超时限制30秒，超时后未完成的股票返回0分
    """
    import time as _time
    result = {}
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    start_time = _time.time()
    timeout = 10  # 总超时10秒

    for code in codes:
        # 超时检查
        if _time.time() - start_time > timeout:
            print(f"技术分析超时，已完成 {len(result)}/{len(codes)} 只")
            break
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start_date, adjust="qfq"
            )
            if df is None or df.empty or len(df) < 20:
                result[code] = 0
                continue

            close = df['收盘'].astype(float)
            volume = df['成交量'].astype(float)

            score = 0

            # --- MA5 vs MA10 ---
            if len(close) >= 10:
                ma5 = close.iloc[-5:].mean()
                ma10 = close.iloc[-10:].mean()
                if ma5 > ma10:
                    score += 2

            # --- MACD ---
            # 简易MACD: EMA12, EMA26, DIF=EMA12-EMA26, DEA=EMA(DIF,9), Histogram=2*(DIF-DEA)
            if len(close) >= 26 + 9:
                ema12 = close.ewm(span=12, adjust=False).mean()
                ema26 = close.ewm(span=26, adjust=False).mean()
                dif = ema12 - ema26
                dea = dif.ewm(span=9, adjust=False).mean()
                histogram = 2 * (dif - dea)
                if len(histogram) >= 2:
                    hist_last = histogram.iloc[-1]
                    hist_prev = histogram.iloc[-2]
                    if hist_last > 0 and hist_last > hist_prev:
                        score += 2
                    elif hist_last > 0:
                        score += 1  # 柱状图>0但未递增，给一半分

            # --- Volume trend ---
            if len(volume) >= 10:
                vol_recent5 = volume.iloc[-5:].mean()
                vol_prev5 = volume.iloc[-10:-5].mean()
                if vol_recent5 > vol_prev5:
                    score += 1

            # --- Price vs MA20 ---
            if len(close) >= 20:
                ma20 = close.iloc[-20:].mean()
                if close.iloc[-1] > ma20:
                    score += 1

            result[code] = min(score, 6)

        except Exception as e:
            print(f"技术分析 {code} 失败: {e}")
            result[code] = 0

    return result


# ============ 推荐系统 V3.0 ============
def get_market_sentiment():
    """获取大盘情绪指数（基于TOP100涨跌分布）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('SELECT MAX(date) FROM hot_rank_history')
    row = c.fetchone()
    if not row or not row[0]:
        conn.close()
        return {'up': 0, 'down': 0, 'flat': 0, 'limit_up': 0, 'limit_down': 0, 'sentiment': 50}
    latest_date = row[0]
    
    # 获取TOP100的涨跌幅
    c.execute('''SELECT h.change_pct FROM hot_rank_history h 
                 WHERE h.date = ? AND h.rank IS NOT NULL AND h.rank <= 100
                 ORDER BY h.rank ASC''', (latest_date,))
    changes = [r[0] for r in c.fetchall() if r[0] is not None]
    conn.close()
    
    if not changes:
        return {'up': 0, 'down': 0, 'flat': 0, 'limit_up': 0, 'limit_down': 0, 'sentiment': 50}
    
    up = sum(1 for x in changes if x > 0)
    down = sum(1 for x in changes if x < 0)
    flat = sum(1 for x in changes if x == 0)
    limit_up = sum(1 for x in changes if x >= 9.5)  # 接近涨停
    limit_down = sum(1 for x in changes if x <= -9.5)  # 接近跌停
    
    # 情绪指数：0-100，越高越乐观
    total = len(changes)
    sentiment = round((up / total * 50) + (limit_up / total * 30) + 20, 1)
    sentiment = min(100, max(0, sentiment))
    
    return {
        'up': up, 'down': down, 'flat': flat,
        'limit_up': limit_up, 'limit_down': limit_down,
        'sentiment': sentiment
    }

def get_recommendations():
    """基于多维度计算推荐评分 - V3.0 十因子模型"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 获取最新日期
    c.execute('SELECT MAX(date) FROM hot_rank_history')
    row = c.fetchone()
    if not row or not row[0]:
        conn.close()
        return []
    latest_date = row[0]

    # 获取前一天日期（用于计算上升速度）
    c.execute('SELECT MAX(date) FROM hot_rank_history WHERE date < ?', (latest_date,))
    prev_date_row = c.fetchone()
    prev_date = prev_date_row[0] if prev_date_row else None

    # 获取当前TOP100（增加更多字段）
    c.execute('''SELECT h.code, h.name, h.rank, h.sector, h.concept, h.change_pct,
                        h.price, h.consecutive_boards, 0, h.limit_up_reason
                 FROM hot_rank_history h
                 WHERE h.date = ? AND h.rank IS NOT NULL
                 ORDER BY h.rank ASC LIMIT 100''', (latest_date,))
    top100 = c.fetchall()
    
    # 获取前一天排名（用于计算上升速度）
    prev_ranks = {}
    if prev_date:
        c.execute('''SELECT code, rank FROM hot_rank_history 
                     WHERE date = ? AND rank IS NOT NULL''', (prev_date,))
        prev_ranks = {r[0]: r[1] for r in c.fetchall()}
    
    conn.close()

    if not top100:
        return []

    # 构建TOP100集合
    top100_codes = set()
    top100_sectors = {}  # sector -> count
    top100_concepts = {}  # concept -> count
    top100_concept_stocks = {}  # concept -> set of codes

    for item in top100:
        code, name, rank, sector, concept, change_pct, price, consecutive_boards, market_cap, limit_up_reason = item
        top100_codes.add(code)
        if sector:
            top100_sectors[sector] = top100_sectors.get(sector, 0) + 1
        if concept:
            concepts = [c.strip() for c in str(concept).split(',') if c.strip()]
            for con in concepts:
                top100_concepts[con] = top100_concepts.get(con, 0) + 1
                if con not in top100_concept_stocks:
                    top100_concept_stocks[con] = set()
                top100_concept_stocks[con].add(code)

    # 获取概念热度：哪些概念进入了TOP100概念榜（出现>=2次的）
    hot_concepts = {con for con, cnt in top100_concepts.items() if cnt >= 2}

    # 批量获取30天统计
    all_codes = [item[0] for item in top100]
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    placeholders = ','.join(['?'] * len(all_codes))
    c.execute(f'''SELECT code, date, rank FROM hot_rank_history
                  WHERE code IN ({placeholders}) AND date >= ? AND rank IS NOT NULL
                  ORDER BY date ASC''', all_codes + [thirty_days_ago])
    history_rows = c.fetchall()
    conn.close()

    # 按code分组历史数据
    code_history = {}
    for code, date, rank in history_rows:
        if code not in code_history:
            code_history[code] = []
        code_history[code].append({'date': date, 'rank': rank})
    
    # ========== 上榜趋势分析 ==========
    # 分析每只股票的排名趋势：刚冲上100、上升趋势、走下坡路等
    code_trend = {}  # code -> {trend_type, trend_score, trend_reason}
    for code, hist in code_history.items():
        if len(hist) < 2:
            # 新上榜：只有1天数据
            if len(hist) == 1:
                r = hist[0]['rank']
                if r <= 50:
                    code_trend[code] = {'trend_type': 'new_to_50', 'trend_score': 8, 'trend_reason': '新上榜直冲50强'}
                else:
                    code_trend[code] = {'trend_type': 'new_to_100', 'trend_score': 5, 'trend_reason': '刚冲上100'}
            continue
        
        # 按日期排序
        hist_sorted = sorted(hist, key=lambda x: x['date'])
        ranks = [h['rank'] for h in hist_sorted]
        
        # 检测走下坡路：前十→五十→一百（持续下降）
        is_downhill = False
        downhill_score = 0
        if len(ranks) >= 3:
            # 检查最近3天的趋势
            recent_3 = ranks[-3:]
            if recent_3[0] <= 10 and recent_3[1] > 10 and recent_3[1] <= 50 and recent_3[2] > 50:
                is_downhill = True
                downhill_score = -10  # 前十→五十→一百，严重扣分
            # 检查是否持续下降
            elif all(recent_3[i] < recent_3[i+1] for i in range(2)):
                if recent_3[0] <= 20 and recent_3[2] >= 50:
                    is_downhill = True
                    downhill_score = -8  # 持续下降
                elif recent_3[0] <= 50 and recent_3[2] > 80:
                    is_downhill = True
                    downhill_score = -6
        
        if is_downhill:
            code_trend[code] = {'trend_type': 'downhill', 'trend_score': downhill_score, 'trend_reason': '走下坡路'}
            continue
        
        # 检测上升趋势
        is_uptrend = False
        uptrend_score = 0
        uptrend_reason = ''
        if len(ranks) >= 2:
            # 从100外进入100
            if ranks[-2] > 100 and ranks[-1] <= 100:
                is_uptrend = True
                uptrend_score = 6
                uptrend_reason = '刚冲上100'
            # 从100外进入50
            elif ranks[-2] > 100 and ranks[-1] <= 50:
                is_uptrend = True
                uptrend_score = 10
                uptrend_reason = '新上榜直冲50强'
            # 从50外进入50
            elif ranks[-2] > 50 and ranks[-1] <= 50:
                is_uptrend = True
                uptrend_score = 7
                uptrend_reason = '冲入50强'
            # 从20外进入20
            elif ranks[-2] > 20 and ranks[-1] <= 20:
                is_uptrend = True
                uptrend_score = 8
                uptrend_reason = '冲入20强'
            # 排名持续上升（数字变小）
            elif ranks[-1] < ranks[-2]:
                rank_improve = ranks[-2] - ranks[-1]
                if rank_improve >= 20:
                    is_uptrend = True
                    uptrend_score = 5
                    uptrend_reason = f'排名上升{rank_improve}位'
        
        if is_uptrend:
            code_trend[code] = {'trend_type': 'uptrend', 'trend_score': uptrend_score, 'trend_reason': uptrend_reason}
        else:
            code_trend[code] = {'trend_type': 'stable', 'trend_score': 0, 'trend_reason': ''}

    # 获取技术分析评分（因子#11）- 只对过滤后的候选股票计算（加速）
    # 先排除科创板和北交所
    candidate_codes = [item[0] for item in top100 if not item[0].startswith('688')
                       and not ((item[0].startswith('8') or item[0].startswith('4')) and len(item[0]) >= 6)]
    technical_scores = get_technical_scores(candidate_codes)

    # 获取最新复盘教训
    review_lessons = []
    try:
        review_data = get_daily_review()
        review_lessons = review_data.get('lessons', [])
    except Exception as e:
        print(f"获取复盘教训失败: {e}")

    # 加载动态权重
    w = load_weights()

    # 计算每只股票的推荐评分
    recommendations = []

    for item in top100:
        code, name, rank, sector, concept, change_pct, price, consecutive_boards, market_cap, limit_up_reason = item
        
        # 处理None值
        name = name or ''
        change_pct = change_pct or 0
        price = price or 0
        consecutive_boards = consecutive_boards or 0
        market_cap = market_cap or 0

        # ========== 硬性过滤：13元以下、非ST、非亏损 ==========
        is_st = name.startswith('ST') or name.startswith('*ST')
        is_loss = change_pct < -5 or '亏损' in name or '绩差' in name
        if is_st or is_loss or price <= 0 or price > 13:
            continue

        # ========== 原有五因子 ==========
        
        # --- 1. 概念热度分(20分基准): 所属概念中有多少个进入TOP100概念榜 ---
        concept_heat = 0
        if concept:
            concepts = [c.strip() for c in str(concept).split(',') if c.strip()]
            hot_count = sum(1 for con in concepts if con in hot_concepts)
            concept_heat = min(hot_count / 3 * w.get('concept_heat', 20), w.get('concept_heat', 20))

        # --- 2. 上榜持续性(20分基准): continuous_days / 5 * 20 ---
        hist = code_history.get(code, [])
        hist_dates = set(r['date'] for r in hist)
        continuous_days = 0
        if hist:
            latest_hist_date = max(hist_dates)
            check_date = datetime.strptime(latest_hist_date, '%Y-%m-%d')
        else:
            check_date = datetime.now()
        for _ in range(30):
            date_str = check_date.strftime('%Y-%m-%d')
            if date_str in hist_dates:
                continuous_days += 1
            else:
                break
            check_date -= timedelta(days=1)
        persistence_score = min(continuous_days / 5 * w.get('persistence', 20), w.get('persistence', 20))

        # --- 3. 上榜频率(15分基准): monthly_count / 10 * 15 ---
        monthly_count = len(hist)
        frequency_score = min(monthly_count / 10 * w.get('frequency', 15), w.get('frequency', 15))

        # --- 4. 板块支撑(15分基准): 同板块有多少只进入TOP100 ---
        sector_support = 0
        if sector:
            sector_cnt = top100_sectors.get(sector, 0)
            sector_support = min(sector_cnt / 5 * w.get('sector_support', 15), w.get('sector_support', 15))

        # --- 5. 概念梯队(10分基准): 同概念有多少只进入TOP100 ---
        concept_group = 0
        if concept:
            concepts = [c.strip() for c in str(concept).split(',') if c.strip()]
            max_group = 0
            for con in concepts:
                group_cnt = len(top100_concept_stocks.get(con, set()))
                if group_cnt > max_group:
                    max_group = group_cnt
            concept_group = min(max_group / 5 * w.get('concept_group', 10), w.get('concept_group', 10))

        # ========== 新增六因子 ==========
        
        # --- 6. 上升速度(10分基准): 排名上升幅度 ---
        speed_score = 0
        if code in prev_ranks:
            prev_rank = prev_ranks[code]
            rank_change = prev_rank - rank
            if rank_change > 0:
                speed_score = min(rank_change / 10 * w.get('speed', 10), w.get('speed', 10))
            elif rank_change < 0:
                speed_score = max(rank_change / 20 * 5, -5)

        # --- 7. 价格优势(5分基准): 低价股偏好(2-15元区间) ---
        price_score = 0
        pw = w.get('price', 5)
        if price > 0:
            if price <= 5:
                price_score = pw * 1.0
            elif price <= 10:
                price_score = pw * 0.8
            elif price <= 15:
                price_score = pw * 0.6
            elif price <= 30:
                price_score = pw * 0.4
            else:
                price_score = pw * 0.2

        # --- 8. 连板溢价(3分基准): 连板天数 ---
        board_score = min(consecutive_boards / 3 * w.get('board', 3), w.get('board', 3)) if consecutive_boards > 0 else 0

        # --- 9. 技术信号(2分基准): 涨停/强势形态 ---
        tech_score = 0
        tw = w.get('tech', 2)
        if change_pct >= 9.5:
            tech_score = tw
        elif change_pct >= 7:
            tech_score = tw * 0.75
        elif change_pct >= 5:
            tech_score = tw * 0.5
        elif change_pct >= 3:
            tech_score = tw * 0.25

        # --- 10. 流动性(0分基准): 流通市值50-500亿最优 ---
        liquidity_score = 0
        if market_cap > 0:
            cap_yi = market_cap / 100000000
            if 50 <= cap_yi <= 500:
                liquidity_score = 0
            elif cap_yi < 20:
                liquidity_score = -2
            elif cap_yi < 50:
                liquidity_score = -1
            elif cap_yi > 1000:
                liquidity_score = -1

        # --- 11. 技术分析(6分基准): MA/MACD/量能/均线 ---
        ta_score = technical_scores.get(code, 0) * (w.get('ta', 6) / 6)
        
        # --- 12. 低价优质股加权(额外+5分): 10元以下、排名50内 ---
        low_price_quality_score = 0
        if 0 < price <= 10 and rank <= 50:
            low_price_quality_score = 5
            reasons_low_price = True
        elif 0 < price <= 15 and rank <= 30:
            low_price_quality_score = 3
        elif 0 < price <= 20 and rank <= 20:
            low_price_quality_score = 2

        # --- 13. 上榜趋势分析(额外+10分或-10分) ---
        trend_info = code_trend.get(code, {'trend_type': 'stable', 'trend_score': 0, 'trend_reason': ''})
        trend_score = trend_info['trend_score']
        trend_reason = trend_info['trend_reason']
        
        # 走下坡路的股票直接跳过，不推荐
        if trend_info['trend_type'] == 'downhill':
            continue  # 跳过走下坡路的股票

        # 总分
        total_score = round(
            concept_heat + persistence_score + frequency_score + sector_support + concept_group +
            speed_score + price_score + board_score + tech_score + liquidity_score + ta_score + low_price_quality_score + trend_score, 1
        )

        # ========== 风险评级 ==========
        risk_level = '低风险'
        risk_deduct = 0
        if change_pct >= 9.5:
            risk_level = '追高风险'
            risk_deduct = 0  # 涨停不扣分，但标记风险
        elif change_pct >= 7:
            risk_level = '高风险'
            risk_deduct = 2
        elif change_pct >= 5:
            risk_level = '中风险'
            risk_deduct = 1
        elif change_pct <= -5:
            risk_level = '高风险'
            risk_deduct = 3
        elif change_pct <= -3:
            risk_level = '中风险'
            risk_deduct = 2
        
        # ST股额外扣分
        is_st = name.startswith('ST') or name.startswith('*ST')
        if is_st:
            risk_level = '高风险'
            risk_deduct += 5
        
        total_score = max(0, total_score - risk_deduct)

        # ========== 复盘教训调整 ==========
        lesson_adjust = 0
        for lesson in review_lessons:
            if "涨停股次日追高风险大" in lesson and change_pct >= 9.5:
                lesson_adjust -= 2
            if "低价股表现优于高价股" in lesson and 0 < price < 10:
                lesson_adjust += 1
        total_score = max(0, total_score + lesson_adjust)

        # ========== 止损止盈建议 ==========
        stop_loss = None
        take_profit1 = None
        take_profit2 = None
        if price > 0:
            stop_loss = round(price * 0.95, 2)  # -5%止损
            take_profit1 = round(price * 1.05, 2)  # +5%止盈
            take_profit2 = round(price * 1.10, 2)  # +10%止盈

        # 生成推荐理由
        reasons = []
        # 趋势理由优先显示
        if trend_reason:
            reasons.append(trend_reason)
        if low_price_quality_score >= 5:
            reasons.append('低价优质股')
        if concept_heat >= 15:
            reasons.append('概念热度高')
        if continuous_days >= 5:
            reasons.append(f'连续上榜{continuous_days}天')
        elif continuous_days >= 3:
            reasons.append(f'连续上榜{continuous_days}天')
        if monthly_count >= 10:
            reasons.append('上榜频率极高')
        elif monthly_count >= 5:
            reasons.append('上榜频率高')
        if sector and top100_sectors.get(sector, 0) >= 5:
            reasons.append('板块强势')
        elif sector and top100_sectors.get(sector, 0) >= 3:
            reasons.append('板块支撑')
        if concept_group >= 8:
            reasons.append('概念梯队强')
        if speed_score >= 5:
            reasons.append('排名快速上升')
        elif speed_score >= 3:
            reasons.append('排名上升')
        if consecutive_boards >= 3:
            reasons.append(f'{consecutive_boards}连板')
        if change_pct >= 9.5:
            reasons.append('涨停')
        if price > 0 and price <= 10:
            reasons.append('低价优势')
        # 确保至少有一条理由
        if not reasons:
            if continuous_days > 0:
                reasons.append(f'连续上榜{continuous_days}天')
            elif monthly_count > 0:
                reasons.append(f'30天上榜{monthly_count}次')
            else:
                reasons.append('热度上榜')

        recommendations.append({
            'code': code,
            'name': name,
            'rank': rank,
            'score': total_score,
            'continuous_days': continuous_days,
            'monthly_count': monthly_count,
            'sector_support': round(sector_support, 1),
            'concept_group': round(concept_group, 1),
            'speed_score': round(speed_score, 1),
            'price_score': round(price_score, 1),
            'reasons': '、'.join(reasons),
            'sector': sector or '',
            'concept': concept or '',
            'price': price,
            'change_pct': round(change_pct, 2),
            'risk_level': risk_level,
            'stop_loss': stop_loss,
            'take_profit1': take_profit1,
            'take_profit2': take_profit2,
            'consecutive_boards': consecutive_boards
        })

    # 按评分排序
    recommendations.sort(key=lambda x: -x['score'])

    # ========== 过滤逻辑 ==========

    # 价格过滤: 必须有有效价格且价格<20元
    recommendations = [r for r in recommendations if r.get('price') and r['price'] > 0 and r['price'] < 20]

    # 交易所过滤: 排除北交所和科创板
    filtered = []
    for r in recommendations:
        code = r['code']
        # 排除科创板 (688开头)
        if code.startswith('688'):
            continue
        # 排除北交所 (8开头且长度>=6, 或4开头且长度>=6)
        if (code.startswith('8') or code.startswith('4')) and len(code) >= 6:
            continue
        filtered.append(r)
    recommendations = filtered

    # 限制最多8只
    recommendations = recommendations[:8]

    return recommendations

# ============ 每日复盘 ============
def get_daily_review():
    """
    获取昨日TOP5推荐股票，对比今日表现，生成复盘报告。
    返回dict: {review_date, review_stocks, summary, lessons}
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 获取数据库中最新日期和前一天日期
    c.execute('SELECT MAX(date) FROM hot_rank_history')
    row = c.fetchone()
    if not row or not row[0]:
        conn.close()
        return {'review_date': datetime.now().strftime('%Y-%m-%d'), 'review_stocks': [], 'summary': '无数据', 'lessons': []}
    latest_date = row[0]

    # 获取前一天日期
    c.execute('SELECT MAX(date) FROM hot_rank_history WHERE date < ?', (latest_date,))
    prev_row = c.fetchone()
    if not prev_row or not prev_row[0]:
        conn.close()
        return {'review_date': datetime.now().strftime('%Y-%m-%d'), 'review_stocks': [], 'summary': '无昨日数据', 'lessons': []}
    prev_date = prev_row[0]

    # 获取昨日TOP5（按排名取前5）
    c.execute('''SELECT h.code, h.name, h.rank, h.price, h.change_pct
                 FROM hot_rank_history h
                 WHERE h.date = ? AND h.rank IS NOT NULL
                 ORDER BY h.rank ASC LIMIT 5''', (prev_date,))
    prev_top5 = c.fetchall()

    if not prev_top5:
        conn.close()
        return {'review_date': datetime.now().strftime('%Y-%m-%d'), 'review_stocks': [], 'summary': '昨日无推荐数据', 'lessons': []}

    # 获取今日排名和行情
    c.execute('''SELECT h.code, h.rank, h.price, h.change_pct
                 FROM hot_rank_history h
                 WHERE h.date = ? AND h.rank IS NOT NULL''', (latest_date,))
    today_data = {r[0]: {'rank': r[1], 'price': r[2], 'change_pct': r[3]} for r in c.fetchall()}
    conn.close()

    review_stocks = []
    up_count = 0
    down_count = 0
    total_change = 0
    valid_count = 0
    hit_target_count = 0
    limit_up_yesterday = 0
    limit_up_today_down = 0
    low_price_up = 0
    low_price_total = 0

    for code, name, prev_rank, prev_price, prev_change_pct in prev_top5:
        today_info = today_data.get(code, {})
        curr_rank = today_info.get('rank', None)
        today_price = today_info.get('price', 0) or 0
        today_change_pct = today_info.get('change_pct', 0) or 0

        # 计算涨跌幅变化
        change_pct = today_change_pct
        hit_target = change_pct > 0  # 今日上涨视为命中目标

        if change_pct > 0:
            up_count += 1
        elif change_pct < 0:
            down_count += 1
        total_change += change_pct
        valid_count += 1

        if hit_target:
            hit_target_count += 1

        # 统计：昨日涨停今日表现
        if prev_change_pct and prev_change_pct >= 9.5:
            limit_up_yesterday += 1
            if change_pct < 0:
                limit_up_today_down += 1

        # 统计：低价股表现
        if prev_price and prev_price > 0 and prev_price < 10:
            low_price_total += 1
            if change_pct > 0:
                low_price_up += 1

        review_stocks.append({
            'code': code,
            'name': name,
            'prev_rank': prev_rank,
            'curr_rank': curr_rank,
            'prev_score': round(prev_change_pct or 0, 2),
            'change_pct': round(change_pct, 2),
            'hit_target': hit_target
        })

    # 生成总结
    avg_change = round(total_change / valid_count, 2) if valid_count > 0 else 0
    summary = f"昨日推荐{len(prev_top5)}只，{up_count}只上涨，{down_count}只下跌，平均涨幅{'+' if avg_change >= 0 else ''}{avg_change}%"

    # 生成经验教训
    lessons = []

    # 规则1: 涨停股次日追高风险
    if limit_up_yesterday >= 1 and limit_up_today_down > 0:
        lessons.append("涨停股次日追高风险大")

    # 规则2: 低价股表现
    if low_price_total >= 2:
        if low_price_up / low_price_total >= 0.5:
            lessons.append("低价股表现优于高价股")
        else:
            lessons.append("低价股表现不稳定")

    # 规则3: 连板股风险
    if hit_target_count < valid_count // 2 and valid_count >= 3:
        lessons.append("热门股次日回调概率较高")

    # 规则4: 整体市场偏弱
    if avg_change < -2:
        lessons.append("市场整体偏弱，需降低仓位")

    # 规则5: 排名下降股
    rank_down_count = sum(1 for s in review_stocks if s['curr_rank'] and s['prev_rank'] and s['curr_rank'] > s['prev_rank'])
    if rank_down_count >= 3:
        lessons.append("热度排名下降股需警惕")

    # ===== 动态调整权重 =====
    weights = load_weights()
    hit_rate = hit_target_count / valid_count * 100 if valid_count > 0 else 50
    adjusted = False

    if valid_count >= 4:
        if hit_rate >= 75:
            weights['speed'] = min(15, weights['speed'] + 1)
            weights['persistence'] = min(25, weights['persistence'] + 1)
            weights['version'] += 1
            adjusted = True
        elif hit_rate < 30:
            weights['speed'] = max(5, weights['speed'] - 1)
            weights['tech'] = max(0, weights['tech'] - 1)
            weights['version'] += 1
            adjusted = True

    if limit_up_today_down >= 2:
        weights['tech'] = max(0, weights['tech'] - 1)
        weights['version'] += 1
        adjusted = True

    if adjusted:
        save_weights(weights)
        lessons.append(f"算法v{weights['version']}已自动优化: 命中率{hit_rate:.0f}%")

    return {
        'review_date': datetime.now().strftime('%Y-%m-%d'),
        'prev_date': prev_date,
        'review_stocks': review_stocks,
        'summary': summary,
        'lessons': lessons
    }


# ============ 更新数据 ============
def do_update():
    """更新数据 - 包含完整字段，行情失败时用akshare备选"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    update_status['running'] = True
    update_status['message'] = f'[{now}] 正在更新...'
    print(f"[{now}] 开始更新数据...")

    # 1. 获取热榜数据
    stocks = fetch_hot_rank()
    if not stocks:
        update_status['message'] = f'[{now}] 更新失败：无法获取热榜数据'
        update_status['running'] = False
        return

    print(f"获取到 {len(stocks)} 只热榜股票")

    # 2. 获取板块信息
    codes = [s['code'] for s in stocks[:100]]
    sector_map = fetch_sector_info(codes)
    print(f"获取到 {len(sector_map)} 只股票板块信息")

    # 3. 获取实时行情
    spot_df = fetch_spot_data()
    spot_map = {}
    spot_success = False
    if spot_df is not None:
        for _, row in spot_df.iterrows():
            code = str(row.get('代码', '')).zfill(6)
            spot_map[code] = {
                'price': row.get('最新价', 0),
                'change_pct': row.get('涨跌幅', 0),
                'change_amt': row.get('涨跌额', 0),
                'volume': row.get('成交量', 0),
                'turnover': row.get('成交额', 0),
                'turnover_rate': row.get('换手率', 0),
                'pe_ratio': row.get('市盈率-动态', 0),
                'market_cap': row.get('总市值', 0)
            }
        spot_success = True
        print(f"获取到 {len(spot_map)} 条行情数据")

    # 3.5 如果行情接口失败，用新浪财经API获取TOP100价格（非交易时间也能用）
    if not spot_success:
        print("levistock行情失败，尝试用新浪财经API获取价格...")
        try:
            top100_codes = [s['code'] for s in stocks[:100]]
            sina_data = fetch_sina_prices(top100_codes)
            if sina_data:
                for code, info in sina_data.items():
                    if info.get('price', 0) > 0:
                        spot_map[code] = {
                            'price': info['price'],
                            'change_pct': info['change_pct'],
                            'change_amt': info.get('change_amt', 0),
                            'volume': info.get('volume', 0),
                            'turnover': info.get('turnover', 0),
                            'turnover_rate': 0,
                            'pe_ratio': 0,
                            'market_cap': info.get('market_cap', 0)
                        }
                print(f"  新浪API获取到 {len(sina_data)} 只股票价格")
                spot_success = len(sina_data) > 0
        except Exception as e:
            print(f"  新浪API也失败: {e}")

    # 3.6 如果新浪也失败，用akshare逐只获取TOP10
    if not spot_success:
        print("所有行情接口失败，尝试用akshare获取TOP10历史收盘数据...")
        top10_codes = [s['code'] for s in stocks[:10]]
        for code in top10_codes:
            backup = fetch_price_backup(code)
            if backup:
                spot_map[code] = {
                    'price': backup['price'],
                    'change_pct': backup['change_pct'],
                    'change_amt': 0,
                    'volume': 0,
                    'turnover': 0,
                    'turnover_rate': 0,
                    'pe_ratio': 0,
                    'market_cap': 0
                }
                print(f"  akshare备选: {code} 价格={backup['price']} 涨跌幅={backup['change_pct']}%")

    # 4. 从热榜API直接提取概念标签和涨停原因
    concept_map = {}
    reason_map = {}
    reason_title_map = {}
    national_fund_map = {}
    api_change_map = {}

    for stock in stocks:
        code = stock['code']
        tag = stock.get('tag') or {}
        concept_tags = tag.get('concept_tag') or []
        if concept_tags:
            concept_map[code] = ','.join(concept_tags)
            if any('大基金' in t for t in concept_tags):
                national_fund_map[code] = '是'

        analyse = stock.get('analyse') or ''
        if analyse:
            reason_map[code] = analyse[:500]

        analyse_title = stock.get('analyse_title') or ''
        if analyse_title:
            reason_title_map[code] = analyse_title

        api_change = stock.get('rise_and_fall')
        if api_change is not None:
            api_change_map[code] = float(api_change)

    print(f"提取到 {len(concept_map)} 只股票概念标签")
    print(f"提取到 {len(reason_map)} 只股票涨停原因")
    print(f"提取到 {len(national_fund_map)} 只国家大基金持股")

    # 5. 更新数据库
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    updated = 0

    for stock in stocks:
        code = stock['code']
        name = stock['name']
        rank = stock.get('order', 0)
        market = '17' if code.startswith('6') else '33'

        sector = sector_map.get(code, '')
        concept = concept_map.get(code, '')
        limit_up_reason = reason_title_map.get(code, '')
        national_fund = national_fund_map.get(code, '')

        # 行情数据（优先用API返回的涨跌幅，行情失败时用akshare备选或热榜API的rise_and_fall）
        spot = spot_map.get(code, {})
        price = spot.get('price', 0) or 0
        change_pct = api_change_map.get(code, 0) or spot.get('change_pct', 0) or 0
        change_amt = spot.get('change_amt', 0) or 0
        volume = spot.get('volume', 0) or 0
        turnover = spot.get('turnover', 0) or 0
        turnover_rate = spot.get('turnover_rate', 0) or 0
        pe_ratio = spot.get('pe_ratio', 0) or 0
        market_cap = spot.get('market_cap', 0) or 0

        # 保存股票信息
        c.execute('''INSERT OR REPLACE INTO stocks
                     (code, name, market, current_rank, sector, concept,
                      price, change_pct, change_amt, volume, turnover,
                      turnover_rate, pe_ratio, market_cap, limit_up_reason, national_fund)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (code, name, market, rank, sector, concept,
                   price, change_pct, change_amt, volume, turnover,
                   turnover_rate, pe_ratio, market_cap, limit_up_reason, national_fund))

        # 保存历史排名
        try:
            c.execute('''INSERT OR REPLACE INTO hot_rank_history
                         (code, date, rank, price, change_pct)
                         VALUES (?, ?, ?, ?, ?)''',
                      (code, today, rank, price, change_pct))
            updated += 1
        except Exception as e:
            print(f"保存历史记录失败 {code}: {e}")

    conn.commit()
    conn.close()

    # 5.5 获取新上榜股票的历史数据（后台异步执行）
    if THS_COOKIE and updated > 0:
        def fetch_new_stocks_history():
            """后台获取新上榜股票的历史数据"""
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            today = datetime.now().strftime('%Y-%m-%d')
            
            # 找出今天新上榜的股票（历史记录只有今天的）
            new_codes = []
            for stock in stocks[:50]:  # 只处理前50名
                code = stock['code']
                c.execute('''SELECT COUNT(DISTINCT date) FROM hot_rank_history 
                             WHERE code = ? AND date < ?''', (code, today))
                count = c.fetchone()[0]
                if count < 2:  # 历史数据少于2天，认为是新上榜
                    new_codes.append(code)
            
            conn.close()
            
            if new_codes:
                print(f"[后台] 发现 {len(new_codes)} 只新上榜股票，开始获取历史数据...")
                for code in new_codes:
                    try:
                        records = fetch_history_from_api(code)
                        if records:
                            save_history_to_db(code, records)
                            print(f"[后台] {code} 历史数据获取成功: {len(records)} 天")
                        else:
                            print(f"[后台] {code} 历史数据获取失败")
                    except Exception as e:
                        print(f"[后台] {code} 获取异常: {e}")
                print(f"[后台] 新上榜股票历史数据获取完成")
        
        # 启动后台线程获取历史数据
        import threading
        history_thread = threading.Thread(target=fetch_new_stocks_history, daemon=True)
        history_thread.start()

    # 6. 补充获取市盈率（用腾讯财经接口）
    if updated > 0:
        try:
            import requests as req
            all_codes = [s['code'] for s in stocks]
            qq_codes = []
            for code in all_codes:
                if code.startswith('6'):
                    qq_codes.append(f'sh{code}')
                elif code.startswith('0') or code.startswith('3'):
                    qq_codes.append(f'sz{code}')
                else:
                    qq_codes.append(f'sz{code}')
            qq_url = f'https://qt.gtimg.cn/q={",".join(qq_codes)}'
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = req.get(qq_url, headers=headers, timeout=15)
            r.encoding = 'gbk'
            pe_map = {}
            for line in r.text.strip().split(';'):
                if 'v_' not in line or '~' not in line:
                    continue
                fields = line.split('~')
                if len(fields) < 40:
                    continue
                code = fields[2]
                pe = fields[39]
                try:
                    pe_val = float(pe) if pe and pe != '-' else 0
                except:
                    pe_val = 0
                if pe_val > 0:
                    pe_map[code] = pe_val
            if pe_map:
                conn2 = sqlite3.connect(DB_PATH)
                c2 = conn2.cursor()
                for code, pe in pe_map.items():
                    c2.execute('UPDATE stocks SET pe_ratio = ? WHERE code = ? AND (pe_ratio IS NULL OR pe_ratio = 0)', (pe, code))
                conn2.commit()
                conn2.close()
                print(f"补充市盈率: {len(pe_map)} 只股票")
        except Exception as e:
            print(f"补充市盈率失败: {e}")

    update_status['running'] = False
    update_status['last_time'] = now
    update_status['message'] = f'[{now}] 更新成功，共 {updated} 只'
    print(f"更新完成: {updated} 只股票")

    # 自动清理30天前的旧数据
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT date FROM hot_rank_history ORDER BY date DESC LIMIT 1 OFFSET 29")
        row = c.fetchone()
        if row:
            cutoff = row[0]
            c.execute('DELETE FROM hot_rank_history WHERE date < ?', (cutoff,))
            deleted = c.rowcount
            if deleted > 0:
                # 清理孤立的stocks记录
                c.execute('DELETE FROM stocks WHERE code NOT IN (SELECT DISTINCT code FROM hot_rank_history)')
                conn.commit()
                print(f"清理旧数据: 删除 {deleted} 条历史记录")
        conn.close()
    except Exception as e:
        print(f"清理旧数据失败: {e}")

def auto_update_loop():
    """自动更新循环"""
    while True:
        time.sleep(3600)
        if not update_status['running']:
            do_update()

# ============ Web路由 ============
@app.route('/')
def index():
    stats = get_stats()
    dates = get_dates()
    selected_date = dates[0] if dates else ''
    resp = make_response(render_template('index.html', stats=stats, dates=dates, selected_date=selected_date))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/api/top50/<date>')
def api_top50(date):
    """获取TOP50数据，附带连续上榜天数"""
    data = get_top50_with_full_data(date)
    codes = [d[0] for d in data]
    # 批量获取连续上榜天数
    continuous_map = get_continuous_days_bulk(codes)

    result = []
    for d in data:
        result.append({
            'code': d[0],
            'name': d[1],
            'rank': d[2],
            'current_rank': d[3],
            'sector': d[4] or '',
            'concept': d[5] or '',
            'price': d[6] or 0,
            'change_pct': d[7] or 0,
            'change_amt': d[8] or 0,
            'volume': d[9] or 0,
            'turnover': d[10] or 0,
            'turnover_rate': d[11] or 0,
            'limit_up_reason': d[12] or '',
            'national_fund': d[13] or '',
            'consecutive_boards': d[14] or 0,
            'continuous_days': continuous_map.get(d[0], 0)
        })
    return jsonify(result)

@app.route('/api/filtered_hot/<date>')
def api_filtered_hot(date):
    """获取过滤后的热门股票（价格<13、排除ST、排除亏损、只显示曾进前100的）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. 获取曾进入前100的股票代码（历史最高排名<=100）
    c.execute('''SELECT code, MIN(rank) as best_rank 
                 FROM hot_rank_history 
                 GROUP BY code 
                 HAVING best_rank <= 100''')
    ever_top100_codes = {row[0]: row[1] for row in c.fetchall()}
    
    if not ever_top100_codes:
        conn.close()
        return jsonify([])
    
    # 2. 获取这些股票在指定日期的数据，并应用过滤条件
    codes_tuple = tuple(ever_top100_codes.keys())
    
    # COALESCE取price/change_pct优先用stocks表，GROUP BY去重
    query = '''SELECT h.code, COALESCE(s.name, h.name, h.code) as name, MIN(h.rank) as rank, 
                      COALESCE(s.price, h.price) as price, COALESCE(s.change_pct, h.change_pct) as change_pct, 
                      COALESCE(s.sector, h.sector, '') as sector,
                      COALESCE(s.concept, h.concept, '') as concept, h.limit_up_reason,
                      s.pe_ratio, s.market_cap
               FROM hot_rank_history h
               LEFT JOIN stocks s ON h.code = s.code
               WHERE h.date = ? AND h.code IN ({})
               GROUP BY h.code'''.format(','.join(['?' for _ in ever_top100_codes]))
    
    c.execute(query, (date,) + codes_tuple)
    rows = c.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        code, name, rank, price, change_pct, sector, concept, limit_up_reason, pe_ratio, market_cap = row
        
        # 过滤条件：
        # 1. 价格 < 13（price为0或None说明无数据，也排除）
        # 2. 排除ST（名称包含ST）
        # 3. 排除亏损（市盈率为负或为0，pe_ratio<=0说明亏损或数据缺失）
        if not price or price >= 13:
            continue
        if name and ('ST' in name.upper() or '*ST' in name or '退' in name):
            continue
        if pe_ratio is None or pe_ratio <= 0:
            continue
            
        result.append({
            'code': code,
            'name': name or code,
            'rank': rank,
            'best_rank': ever_top100_codes.get(code, rank),
            'price': price or 0,
            'change_pct': change_pct or 0,
            'sector': sector or '',
            'concept': concept or '',
            'limit_up_reason': limit_up_reason or '',
            'pe_ratio': pe_ratio,
            'market_cap': market_cap or 0
        })
    
    # 按当前排名排序
    result.sort(key=lambda x: x['rank'] if x['rank'] else 999)
    return jsonify(result)

@app.route('/api/stock_history_filtered/<code>')
def api_stock_history_filtered(code):
    """获取股票最近30天历史排名，上榜显示排名，未上榜留空"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 获取数据库中该股票所有上榜记录（rank<=100）
    c.execute('''SELECT date, rank FROM hot_rank_history 
                 WHERE code = ? AND rank <= 100
                 ORDER BY date ASC''', (code,))
    rank_map = {}
    for row in c.fetchall():
        if row[0] not in rank_map or row[1] < rank_map[row[0]]:
            rank_map[row[0]] = row[1]
    
    conn.close()
    
    # 如果数据库中历史数据不足2天，尝试从同花顺API补全
    if len(rank_map) < 2:
        api_records = fetch_history_from_api(code)
        if api_records:
            save_history_to_db(code, api_records)
            # 重新查询
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('''SELECT date, rank FROM hot_rank_history 
                         WHERE code = ? AND rank <= 100
                         ORDER BY date ASC''', (code,))
            rank_map = {}
            for row in c.fetchall():
                if row[0] not in rank_map or row[1] < rank_map[row[0]]:
                    rank_map[row[0]] = row[1]
            conn.close()
    
    # 生成最近30天的日期列表
    from datetime import datetime, timedelta
    today = datetime.now().strftime('%Y-%m-%d')
    dates = []
    for d in range(29, -1, -1):
        dt = (datetime.now() - timedelta(days=d)).strftime('%Y-%m-%d')
        dates.append(dt)
    
    # 构建历史数据：上榜有rank，未上榜为null
    history = []
    for dt in dates:
        if dt in rank_map:
            history.append({'date': dt, 'rank': rank_map[dt]})
        else:
            history.append({'date': dt, 'rank': None})
    
    return jsonify({
        'code': code,
        'history': history,
        'count': len([h for h in history if h['rank'] is not None])
    })

@app.route('/api/cookie/status')
def api_cookie_status():
    """获取Cookie状态"""
    global THS_COOKIE
    has_cookie = bool(THS_COOKIE and len(THS_COOKIE) > 10)
    return jsonify({
        'has_cookie': has_cookie,
        'length': len(THS_COOKIE) if THS_COOKIE else 0,
        'message': 'Cookie有效' if has_cookie else 'Cookie缺失或过期，请设置Cookie'
    })

@app.route('/api/cookie/set', methods=['POST'])
def api_cookie_set():
    """设置Cookie"""
    global THS_COOKIE
    data = request.get_json()
    cookie = data.get('cookie', '').strip()
    if not cookie:
        return jsonify({'success': False, 'message': 'Cookie不能为空'})
    
    # 保存到文件
    try:
        cookie_file = BASE_DIR / 'cookie.txt'
        cookie_file.write_text(cookie, encoding='utf-8')
        THS_COOKIE = cookie
        return jsonify({'success': True, 'message': 'Cookie设置成功', 'length': len(cookie)})
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存失败: {str(e)}'})

@app.route('/api/cookie/test')
def api_cookie_test():
    """测试Cookie是否有效"""
    global THS_COOKIE
    if not THS_COOKIE:
        return jsonify({'valid': False, 'message': 'Cookie未设置'})
    
    # 测试获取一个股票的历史数据
    test_result = fetch_history_from_api('000001')  # 用平安银行测试
    if test_result:
        return jsonify({'valid': True, 'message': 'Cookie有效', 'test_data_count': len(test_result)})
    else:
        return jsonify({'valid': False, 'message': 'Cookie可能已过期，请重新获取'})

@app.route('/api/stock/fetch_history/<code>', methods=['POST'])
def api_stock_fetch_history(code):
    """手动触发获取股票历史数据"""
    global THS_COOKIE
    if not THS_COOKIE:
        return jsonify({'success': False, 'message': 'Cookie未设置，请先设置Cookie'})
    
    records = fetch_history_from_api(code)
    if records:
        save_history_to_db(code, records)
        return jsonify({'success': True, 'message': f'获取到 {len(records)} 天历史数据', 'count': len(records)})
    else:
        return jsonify({'success': False, 'message': '获取失败，Cookie可能已过期'})

@app.route('/api/sector/<date>')
def api_sector(date):
    """板块分析API"""
    return jsonify(analyze_sectors(date))

@app.route('/api/concept/<date>')
def api_concept(date):
    """概念分析API"""
    return jsonify(analyze_concepts(date))

@app.route('/api/stock_history/<code>')
def api_stock_history(code):
    """股票30天历史统计API"""
    data = get_stock_history(code)
    return jsonify(data)

@app.route('/api/recommendations')
def api_recommendations():
    """推荐系统API"""
    data = get_recommendations()
    return jsonify(data)

@app.route('/api/review')
def api_review():
    """每日复盘API - 返回历史数组"""
    review_path = BASE_DIR / 'docs' / 'data' / 'review_results.json'
    if review_path.exists():
        try:
            with open(review_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify([])
    # fallback: 实时复盘
    data = get_daily_review()
    return jsonify([data])

@app.route('/api/weights')
def api_weights():
    """推荐算法权重"""
    return jsonify(load_weights())

@app.route('/api/sentiment')
def api_sentiment():
    """大盘情绪指数API"""
    data = get_market_sentiment()
    return jsonify(data)

@app.route('/api/report/<date>')
def api_report(date):
    """获取指定日期的推荐报告"""
    report_path = Path(REPORT_DIR) / f'推荐报告_{date}.md'
    if report_path.exists():
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({'success': True, 'date': date, 'content': content})
    return jsonify({'success': False, 'message': '报告不存在'})

@app.route('/api/reports')
def api_reports_list():
    """获取报告列表"""
    report_dir = Path(REPORT_DIR)
    if not report_dir.exists():
        return jsonify([])
    reports = sorted([f.name for f in report_dir.glob('推荐报告_*.md')], reverse=True)
    return jsonify(reports[:30])  # 最近30天

@app.route('/api/generate_report')
def api_generate_report():
    """手动生成今日报告"""
    try:
        filepath = generate_markdown_report()
        if filepath:
            return jsonify({'success': True, 'message': f'报告已生成: {filepath.name}'})
        return jsonify({'success': False, 'message': '生成失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/stats')
def api_stats():
    """获取数据库统计（供前端显示）"""
    s = get_stats()
    return jsonify({
        'unique_stocks': s['stock_count'],
        'total_records': s['record_count'],
        'dates': s['day_count']
    })

@app.route('/api/update_now', methods=['POST'])
def api_update_now():
    """手动触发更新（供前端按钮调用，非阻塞）"""
    if update_status['running']:
        return jsonify({'status': 'error', 'message': '正在更新中'})
    thread = threading.Thread(target=do_update)
    thread.start()
    for _ in range(60):
        time.sleep(0.5)
        if not update_status['running']:
            break
    if '失败' not in update_status.get('message', ''):
        return jsonify({'status': 'ok', 'updated': update_status.get('last_time', '')})
    return jsonify({'status': 'error', 'message': update_status.get('message', '更新失败')})

@app.route('/api/update')
def api_update():
    """手动触发更新API"""
    if update_status['running']:
        return jsonify({'success': False, 'message': '正在更新中'})
    thread = threading.Thread(target=do_update)
    thread.start()
    for _ in range(60):
        time.sleep(0.5)
        if not update_status['running']:
            break
    return jsonify({'success': '失败' not in update_status.get('message', ''), 'message': update_status['message']})

@app.route('/api/update_status')
def api_update_status():
    """获取更新状态（供前端轮询判断是否有新数据）"""
    return jsonify({
        'running': update_status['running'],
        'last_time': update_status['last_time'],
        'message': update_status['message']
    })


@app.route('/api/concept_hot')
def concept_hot():
    """同花顺概念板块热榜（含涨停家数、热度）"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': 'application/json',
            'Referer': 'https://eq.10jqka.com.cn/',
        }
        url = 'https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/plate?type=concept'
        resp = requests.get(url, headers=headers, timeout=10)
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
                    'limit_up_tag': item.get('tag', ''),  # "13家涨停"
                    'hot_tag': item.get('hot_tag', ''),    # "连续166天上榜"
                    'etf_name': item.get('etf_name', ''),
                    'etf_code': item.get('etf_product_id', ''),
                })
            return jsonify(result)
        return jsonify([])
    except Exception as e:
        print(f"概念板块热榜获取失败: {e}")
        return jsonify([])


@app.route('/api/industry_hot')
def industry_hot():
    """同花顺行业板块热榜"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': 'application/json',
            'Referer': 'https://eq.10jqka.com.cn/',
        }
        url = 'https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/plate?type=industry'
        resp = requests.get(url, headers=headers, timeout=10)
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
            return jsonify(result)
        return jsonify([])
    except Exception as e:
        print(f"行业板块热榜获取失败: {e}")
        return jsonify([])


if __name__ == '__main__':
    init_db()
    t = threading.Thread(target=auto_update_loop, daemon=True)
    t.start()
    print("Web服务 V2: http://localhost:5000")
    print("暗色系主题 + 完整数据字段 + 排序功能 + 历史统计 + 推荐系统")
    app.run(host='0.0.0.0', port=PORT, debug=False)
