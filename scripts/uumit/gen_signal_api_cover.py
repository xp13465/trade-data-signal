#!/usr/bin/env python3
"""生成 UUMit 数据广场「当日买入信号 / 卖出警示」两个 API 商品封面(1600x1000)。

目的:第三批上架两个数据广场 API(接口1 当日买入信号 + 接口4 卖出警示)的专属封面。
平台要求封面与商品主题明显相关,且中央平台标题叠加区(y180-800)无大面积亮色块。
本脚本 = 单接口专属封面(买入/卖出各一张):深蓝渐变 + 单接口卡 + KPI 小卡。

方法/口径:
- 1600x1000,深蓝渐变背景(#0b1a2e->#132a45) + 顶部细网格(与既有封面系列一致)
- 顶部 6px 青色条 + 品牌小字 + 主标题 + 副标题 + 分隔线
- 中部:中央一张接口卡(深色卡片 + 浅色文字,无亮色大色块——中央平台标题叠加区不遮挡)
- 右侧:3 个 KPI 小卡(每日更新 / 回测背书 / 高胜率)
- 底部:类别标签一行 + 右下版本号

输入依赖:无(纯 PIL 生成,字体 /System/Library/Fonts/PingFang.ttc)
输出:/tmp/buy_signal_cover.png /tmp/sell_alert_cover.png
复现:python3 scripts/uumit/gen_signal_api_cover.py
"""
from PIL import Image, ImageDraw, ImageFont
import math

W, H = 1600, 1000
PF = '/System/Library/Fonts/PingFang.ttc'

def font(size):
    return ImageFont.truetype(PF, size)

ACCENT = '#2a9d8f'
ACCENT2 = '#e76f51'  # 卖出用强调色

def base_image():
    img = Image.new('RGB', (W, H), '#0b1a2e')
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(11 + (19 - 11) * t)
        g = int(26 + (42 - 26) * t)
        b = int(46 + (69 - 46) * t)
        for x in range(W):
            glow = max(0, 1 - math.hypot(x - 1400, y - 900) / 1300)
            px[x, y] = (min(255, int(r + 40 * glow)), min(255, int(g + 50 * glow)), min(255, int(b + 70 * glow)))
    return img

def build(title, subtitle, accent, accent_rgb, rows, kpis, bottom_label, out):
    img = base_image()
    d = ImageDraw.Draw(img)
    # 顶部细网格
    for i in range(0, W, 80):
        d.line([(i, 0), (i, H)], fill=(255, 255, 255, 5), width=1)
    for j in range(0, H, 80):
        d.line([(0, j), (W, j)], fill=(255, 255, 255, 5), width=1)
    # 顶部品牌条 + 标题
    d.rectangle([0, 0, W, 6], fill=accent)
    d.text((60, 42), 'FX8 STORE', fill='#7d9db8', font=font(26))
    d.text((60, 84), 'DAILY TRADING SIGNALS', fill='#4d6b8a', font=font(22))
    d.text((60, 150), title, fill='#ffffff', font=font(84))
    d.text((64, 258), subtitle, fill='#9fb8cd', font=font(30))
    d.line([(60, 340), (1540, 340)], fill='#2a4a6a', width=2)
    d.line([(60, 346), (600, 346)], fill=accent, width=4)
    # 中部:中央接口卡
    CARD_X0, CARD_Y0 = 120, 400
    CARD_W, CARD_H = 1080, 320
    d.rounded_rectangle([CARD_X0, CARD_Y0, CARD_X0 + CARD_W, CARD_Y0 + CARD_H], radius=18, fill='#0f2440', outline='#2a4a6a')
    d.text((CARD_X0 + 30, CARD_Y0 + 22), title, fill='#ffffff', font=font(34))
    d.line([(CARD_X0 + 30, CARD_Y0 + 70), (CARD_X0 + CARD_W - 30, CARD_Y0 + 70)], fill='#2a4a6a', width=1)
    for i, (k, v) in enumerate(rows):
        yy = CARD_Y0 + 92 + i * 56
        d.text((CARD_X0 + 30, yy), f'· {k}', fill=accent, font=font(26))
        d.text((CARD_X0 + 230, yy + 2), v, fill='#cfe0ef', font=font(24))
    # 右侧 KPI 小卡
    kx0 = 1280
    kwh = 88
    for i, (k, v) in enumerate(kpis):
        yy = 400 + i * (kwh + 24)
        d.rounded_rectangle([kx0, yy, kx0 + 260, yy + kwh], radius=14, fill='#0f2440', outline='#2a4a6a')
        d.text((kx0 + 22, yy + 16), v, fill=accent, font=font(44))
        d.text((kx0 + 22, yy + 70), k, fill='#eaf2f8', font=font(20))
    # 底部
    d.text((60, 850), bottom_label, fill='#5b7c9a', font=font(24))
    d.text((1380, 952), 'v1.0 · 2026-08', fill='#4d6b8a', font=font(20))
    img.save(out, quality=95)
    print('OK 封面已生成', out, img.size)

# 买入信号封面
build(
    'FX8 当日买入信号',
    '当日+上交易日两窗口 · 仅入样宇宙买信号 · 附 5/10/20 日回测高胜率背书',
    ACCENT, (42, 157, 143),
    [('窗口', '当天 + 上个交易日'), ('信号', 'buy / buy_special / buy_aux'),
     ('过滤', '回测白名单 + 入样宇宙(宁可空不能错)'), ('背书', '每信号附 win_rate / score / n')],
    [('2', '日期窗口'), ('5/10/20', '回测维度'), ('100%', '入样校验')],
    '包含: 买入信号 · 回测背书 · 每日收盘后更新',
    '/tmp/buy_signal_cover.png'
)

# 卖出警示封面
build(
    'FX8 卖出警示',
    '最新交易日卖出/止损信号 · 全品种覆盖(含债/全球/港股) · 支持代码过滤',
    ACCENT2, (231, 111, 81),
    [('信号', 'sell / sell_stop_loss'), ('覆盖', '全品种(不限于买入宇宙)'),
     ('过滤', '?code= 匹配 ETF 代码/指数ID/代码'), ('用途', '减仓/止损提醒')],
    [('sell', '信号类型'), ('全品种', '覆盖范围'), ('实时', '每日更新')],
    '包含: 卖出警示 · 止损提醒 · 每日收盘后更新',
    '/tmp/sell_alert_cover.png'
)
