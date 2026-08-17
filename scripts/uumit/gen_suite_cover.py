#!/usr/bin/env python3
"""生成 UUMit 数据广场套件商品封面 /tmp/suite_cover_v1.png（1600x1000）。

目的：FX8 每日决策套件（AI 每日市场预测 + ETF 精选评分，数据广场产品/套件）的商品封面。
平台要求封面与标题/简介/标签/交付主题明显相关（数据包封面复用被 AI 质量评估判 failed：
主题不匹配）。本封面 = 套件专属：两个接口卡（AI 次日市场预测 / ETF 精选评分）+ 决策闭环概念。

方法/口径：
- 1600x1000，深蓝渐变背景(#0b1a2e->#132a45) + 顶部细网格（与既有封面系列一致）
- 顶部 6px 青色条 + 品牌小字 + 主标题「FX8 每日决策套件」+ 副标题「AI 市场预测 × ETF 精选评分」+ 分隔线
- 中部：左右两张接口卡（深色卡片 + 浅色文字，无亮色大色块——中央平台标题叠加区 y180-800 不遮挡）
  左卡=「AI 每日市场预测」方向/区间/置信度；右卡=「ETF 精选评分」buy/sell/hold 精选
- 右侧：3 个 KPI 小卡（2 接口 / 每日更新 / 决策闭环）
- 底部：类别标签一行 + 右下版本号

输入依赖：无（纯 PIL 生成，字体 /System/Library/Fonts/PingFang.ttc）
输出：/tmp/suite_cover_v1.png
复现：python3 scripts/uumit/gen_suite_cover.py
"""
from PIL import Image, ImageDraw, ImageFont
import math

W, H = 1600, 1000

# ---- 渐变深色背景 ----
base = Image.new('RGB', (W, H), '#0b1a2e')
px = base.load()
for y in range(H):
    t = y / H
    r = int(11 + (19 - 11) * t)
    g = int(26 + (42 - 26) * t)
    b = int(46 + (69 - 46) * t)
    for x in range(W):
        glow = max(0, 1 - math.hypot(x - 1400, y - 900) / 1300)
        px[x, y] = (min(255, int(r + 40 * glow)), min(255, int(g + 50 * glow)), min(255, int(b + 70 * glow)))
img = base
d = ImageDraw.Draw(img)

PF = '/System/Library/Fonts/PingFang.ttc'
def font(size):
    return ImageFont.truetype(PF, size)

ACCENT = '#2a9d8f'
ACCENT_RGB = (42, 157, 143)

# ---- 顶部细网格线（极淡）----
for i in range(0, W, 80):
    d.line([(i, 0), (i, H)], fill=(255, 255, 255, 5), width=1)
for j in range(0, H, 80):
    d.line([(0, j), (W, j)], fill=(255, 255, 255, 5), width=1)

# ---- 顶部品牌条 + 标题区 ----
d.rectangle([0, 0, W, 6], fill=ACCENT)
d.text((60, 42), 'FX8 STORE', fill='#7d9db8', font=font(26))
d.text((60, 84), 'DAILY DECISION SUITE', fill='#4d6b8a', font=font(22))
d.text((60, 150), 'FX8 每日决策套件', fill='#ffffff', font=font(84))
d.text((64, 258), 'AI 次日市场预测 × ETF 精选评分 · 每日收盘后更新 · 一次购买套内全接口', fill='#9fb8cd', font=font(30))
d.line([(60, 340), (1540, 340)], fill='#2a4a6a', width=2)
d.line([(60, 346), (600, 346)], fill=ACCENT, width=4)

# ---- 中部：两张接口卡（主题相关主体，深色卡无大亮块）----
CARD_W = 430
CARD_H = 260
y0 = 390
# 左卡：AI 每日市场预测
d.rounded_rectangle([60, y0, 60 + CARD_W, y0 + CARD_H], radius=18, fill='#0f2440', outline='#2a4a6a')
d.text((90, y0 + 24), 'AI 每日市场预测', fill='#ffffff', font=font(36))
d.line([(90, y0 + 74), (460, y0 + 74)], fill='#2a4a6a', width=1)
left_rows = [
    ('方向', '次日大盘涨跌方向'),
    ('区间', '预测涨跌幅区间'),
    ('置信度', '把握程度 0-100'),
    ('解读', '情绪/资金/技术 四维'),
]
for i, (k, v) in enumerate(left_rows):
    yy = y0 + 96 + i * 40
    d.text((90, yy), f'· {k}', fill=ACCENT, font=font(24))
    d.text((200, yy + 2), v, fill='#cfe0ef', font=font(20))

# 右卡：ETF 精选评分
x1 = 60 + CARD_W + 40
d.rounded_rectangle([x1, y0, x1 + CARD_W, y0 + CARD_H], radius=18, fill='#0f2440', outline='#2a4a6a')
d.text((x1 + 30, y0 + 24), 'ETF 精选评分', fill='#ffffff', font=font(36))
d.line([(x1 + 30, y0 + 74), (x1 + 400, y0 + 74)], fill='#2a4a6a', width=1)
right_rows = [
    ('买入精选', '高分买入候选'),
    ('卖出警示', '风险标的提醒'),
    ('持有观察', '中性跟踪池'),
    ('多因子', '评分卡全字段'),
]
for i, (k, v) in enumerate(right_rows):
    yy = y0 + 96 + i * 40
    d.text((x1 + 30, yy), f'· {k}', fill=ACCENT, font=font(24))
    d.text((x1 + 160, yy + 2), v, fill='#cfe0ef', font=font(20))

# ---- 右侧：3 个 KPI 小卡 ----
kpis = [
    ('2', '接口聚合'),
    ('每日', '更新频率'),
    ('闭环', '决策链路'),
]
kxi0, kxi1 = 1030, 1320
kwh = 118
for i, (v, k) in enumerate(kpis):
    yy = 390 + i * (kwh + 26)
    d.rounded_rectangle([kxi0, yy, kxi1, yy + kwh], radius=14, fill='#0f2440', outline='#2a4a6a')
    d.text((kxi0 + 24, yy + 18), v, fill=ACCENT, font=font(48))
    d.text((kxi0 + 24, yy + 74), k, fill='#eaf2f8', font=font(22))

# ---- 底部：类别标签 + 右下版本 ----
d.text((60, 700), '包含: AI 市场预测 · ETF 精选评分 · 每日更新 · 决策闭环', fill='#5b7c9a', font=font(24))
d.text((60, 850), '数据广场套件 · 一次购买访问套内全部接口', fill='#5b7c9a', font=font(24))
d.text((1380, 952), 'v1.0 · 2026-08', fill='#4d6b8a', font=font(20))

img.save('/tmp/suite_cover_v1.png', quality=95)
print('OK 套件封面已生成', img.size)

# ---- 自验：中央叠加区(y180-800)无大面积强调色块 ----
px2 = img.load()
area_accent = 0
for y in range(180, 801, 3):
    for x in range(100, 1501, 3):
        r, g, b = px2[x, y]
        if g > 120 and r < 90 and b > 90:
            area_accent += 1
print('中央叠加区强调色像素(采样):', area_accent, '→ 少量=只有KPI数值/细条,非大块')
bright = 0; total = 0
for y in range(0, H, 4):
    for x in range(0, W, 4):
        r, g, b = px2[x, y]
        total += 1
        if r + g + b > 600:
            bright += 1
print(f'全图高亮像素占比: {bright/total*100:.1f}%')
