#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股价快速更新脚本 - 只更新股价和涨幅，不重新获取排名
用于 GitHub Actions 每 5 分钟运行一次
"""

import json
import os
from datetime import datetime
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'docs' / 'data'
HISTORY_DIR = DATA_DIR / 'history'

try:
    import requests as req
except ImportError:
    os.system('pip install requests -q')
    import requests as req


def fetch_sina_prices(codes):
    """通过新浪财经API批量获取股票价格"""
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
                
                change_pct = 0
                if prev_close > 0 and current_price > 0:
                    change_pct = round((current_price - prev_close) / prev_close * 100, 2)
                
                result[original_code] = {
                    'price': current_price,
                    'change_pct': change_pct,
                    'change_amt': round(current_price - prev_close, 2) if prev_close > 0 else 0
                }
        except Exception as e:
            print(f"  新浪批次请求失败: {e}")
            continue
    
    return result


def update_top50_prices():
    """更新 top50.json 中的股价"""
    top50_path = DATA_DIR / 'top50.json'
    if not top50_path.exists():
        print("ERROR: top50.json 不存在，请先运行完整数据导出")
        return False
    
    with open(top50_path, 'r', encoding='utf-8') as f:
        top50_data = json.load(f)
    
    codes = [item['code'] for item in top50_data]
    print(f"更新 {len(codes)} 只股票价格...")
    
    price_map = fetch_sina_prices(codes)
    
    updated_count = 0
    for item in top50_data:
        code = item['code']
        if code in price_map:
            item['price'] = price_map[code]['price']
            item['change_pct'] = price_map[code]['change_pct']
            item['change_amt'] = price_map[code]['change_amt']
            updated_count += 1
    
    # 保存更新后的数据
    with open(top50_path, 'w', encoding='utf-8') as f:
        json.dump(top50_data, f, ensure_ascii=False, indent=2)
    
    print(f"  ✓ 已更新 {updated_count}/{len(top50_data)} 只股票价格")
    return True


def update_recommendation_prices():
    """更新 recommendations.json 中的股价"""
    rec_path = DATA_DIR / 'recommendations.json'
    if not rec_path.exists():
        print("WARNING: recommendations.json 不存在，跳过")
        return False
    
    with open(rec_path, 'r', encoding='utf-8') as f:
        rec_data = json.load(f)
    
    codes = [item['code'] for item in rec_data]
    price_map = fetch_sina_prices(codes)
    
    updated_count = 0
    for item in rec_data:
        code = item['code']
        if code in price_map:
            old_price = item.get('price', 0)
            item['price'] = price_map[code]['price']
            item['change_pct'] = price_map[code]['change_pct']
            
            # 更新止损止盈价格
            price = item['price']
            if price and price > 0:
                item['stop_loss'] = round(price * 0.95, 2)
                item['take_profit1'] = round(price * 1.05, 2)
                item['take_profit2'] = round(price * 1.10, 2)
            updated_count += 1
    
    with open(rec_path, 'w', encoding='utf-8') as f:
        json.dump(rec_data, f, ensure_ascii=False, indent=2)
    
    print(f"  ✓ 已更新 {updated_count}/{len(rec_data)} 只推荐股票价格")
    return True


def update_history_prices():
    """更新历史数据文件中的当天价格"""
    if not HISTORY_DIR.exists():
        print("WARNING: history 目录不存在，跳过")
        return False
    
    today = datetime.now().strftime('%Y-%m-%d')
    updated_count = 0
    
    for hist_file in HISTORY_DIR.glob('*.json'):
        try:
            with open(hist_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            code = data.get('code')
            if not code:
                continue
            
            # 获取最新价格
            price_map = fetch_sina_prices([code])
            if code not in price_map:
                continue
            
            # 更新当天的价格
            history = data.get('history', [])
            for h in history:
                if h.get('date') == today:
                    h['price'] = price_map[code]['price']
                    h['change_pct'] = price_map[code]['change_pct']
                    updated_count += 1
                    break
            
            with open(hist_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"  更新 {hist_file.name} 失败: {e}")
            continue
    
    print(f"  ✓ 已更新 {updated_count} 个历史文件")
    return True


def update_meta():
    """更新 meta.json 中的最后更新时间"""
    meta_path = DATA_DIR / 'meta.json'
    if not meta_path.exists():
        return False
    
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    
    meta['last_price_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    print(f"  ✓ 更新时间戳: {meta['last_price_update']}")
    return True


def main():
    print("=" * 60)
    print("股价快速更新脚本")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 检查数据目录
    if not DATA_DIR.exists():
        print("ERROR: 数据目录不存在，请先运行完整数据导出")
        return False
    
    # 更新各类数据
    print("\n[1/4] 更新排行榜股价...")
    update_top50_prices()
    
    print("\n[2/4] 更新推荐股票股价...")
    update_recommendation_prices()
    
    print("\n[3/4] 更新历史数据股价...")
    update_history_prices()
    
    print("\n[4/4] 更新元数据...")
    update_meta()
    
    print("\n" + "=" * 60)
    print("股价更新完成！")
    print("=" * 60)
    return True


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
