#!/usr/bin/env python3
"""生成 OG 分享图 og.png（1200x630），放 static-site/ 根目录。

深色品牌卡片：品牌标题 + slogan + 当日关键数据 + 域名。
中文字体用 macOS 自带 PingFang.ttc。
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG_TOP = (31, 35, 41)        # #1f2329
BG_BOT = (45, 50, 57)        # #2d3239
ACCENT = (22, 93, 255)       # #165dff
RED = (230, 73, 46)          # #e6492e
GREEN = (46, 139, 87)        # #2e8b57
WHITE = (255, 255, 255)
GRAY = (170, 178, 189)       # #aab2bd
LIGHT = (230, 232, 234)

FONT = "/System/Library/Fonts/PingFang.ttc"


def font(size, bold=False):
    # PingFang.ttc index: 0=Regular, 1=Light, 2=Thin, 3=Ultralight, 4=Medium, 5=Semibold
    idx = 5 if bold else 4
    return ImageFont.truetype(FONT, size, index=idx)


def vgrad(draw):
    """垂直渐变背景。"""
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))


def card(draw, x, y, w, h, label, value, vcolor):
    """单个数据卡片：标签 + 大数值。"""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=(255, 255, 255, 18), outline=(255, 255, 255, 30), width=1)
    lf = font(18)
    vf = font(40, bold=True)
    draw.text((x + 18, y + 14), label, font=lf, fill=GRAY)
    bbox = draw.textbbox((0, 0), value, font=vf)
    draw.text((x + 18, y + 44), value, font=vf, fill=vcolor)


def main():
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)
    vgrad(draw)

    # 顶部品牌条
    draw.rounded_rectangle([60, 56, 200, 92], radius=18, fill=ACCENT)
    draw.text((78, 62), "tdsignal", font=font(20, bold=True), fill=WHITE)
    draw.text([220, 64], "trade-data-signal", font=font(18), fill=GRAY)

    # 主标题
    draw.text((60, 150), "A股情绪看板", font=font(82, bold=True), fill=WHITE)
    draw.text((60, 252), "盘后复盘 · 情绪数据 · 买卖点信号", font=font(34), fill=LIGHT)

    # 分隔线
    draw.line([(60, 330), (1140, 330)], fill=(255, 255, 255, 40), width=1)

    # 数据卡片行
    cy = 372
    cw, ch, gap = 348, 130, 24
    card(draw, 60, cy, cw, ch, "A股综合情绪分", "68.4", ACCENT)
    card(draw, 60 + cw + gap, cy, cw, ch, "涨停 / 跌停", "64 / 12", RED)
    card(draw, 60 + (cw + gap) * 2, cy, cw, ch, "成交额(亿)", "9,876", GREEN)

    # 底部域名
    draw.text((60, 548), "tdsignal-ujpzw01zm.maozi.io", font=font(26, bold=True), fill=ACCENT)
    draw.text((60, 584), "A股 / 港股 / 全球  ·  综合情绪分 / 跨市场评分 / 行业热力图 / 模拟回测", font=font(16), fill=GRAY)

    img.save("static-site/og.png", "PNG")
    print("✓ static-site/og.png 生成 (1200x630)")


if __name__ == "__main__":
    main()
