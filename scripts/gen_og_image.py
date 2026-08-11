#!/usr/bin/env python3
"""生成 OG 分享图 og.png（1200x630），放 static-site/ 根目录。

深色品牌卡片：品牌双标识 + slogan + 可视化面板（情绪温度计 / 涨跌家数 /
信号灯 / 策略实验室）+ 主站域名。

默认用代表性示例值并在数据面板标注「示例」；传 --live 时从当日
static-site/data/overview.json 读真实情绪分/涨跌家数注入并标注「实时」。

中文字体用 macOS 自带 PingFang.ttc，零第三方依赖（仅 PIL）。
注意：PIL 在 RGB 图像上忽略 RGBA 元组的 alpha，半透明面板需先画在
RGBA overlay 上再 alpha_composite 合成（见 main）。
"""
import argparse
import json
import math
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG_TOP = (31, 35, 41)        # #1f2329
BG_BOT = (45, 50, 57)        # #2d3239
ACCENT = (22, 93, 255)       # #165dff
RED = (230, 73, 46)          # #e6492e
GREEN = (46, 139, 87)        # #2e8b57
PURPLE = (147, 101, 255)     # 辅买/紫
ORANGE = (243, 156, 18)      # 追/橙
ICE = (95, 143, 238)         # 冰点蓝
YELLOW = (247, 203, 60)      # 中性黄
WHITE = (255, 255, 255)
GRAY = (170, 178, 189)       # #aab2bd
LIGHT = (230, 232, 234)

FONT = "/System/Library/Fonts/PingFang.ttc"

PANEL_TAG_EXAMPLE = "示例"
PANEL_TAG_LIVE = "实时"


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


def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def text_w(draw, s, f):
    bbox = draw.textbbox((0, 0), s, font=f)
    return bbox[2] - bbox[0]


def panel_bg(odraw, x, y, w, h):
    """半透明面板底框（画在 RGBA overlay 上，之后 alpha_composite 合成）。"""
    odraw.rounded_rectangle([x, y, x + w, y + h], radius=10,
                            fill=(255, 255, 255, 18), outline=(255, 255, 255, 32), width=1)


def panel_label(draw, x, y, w, label, tag=None):
    """面板左上角标签 + 可选「示例/实时」小标。"""
    draw.text((x + 16, y + 12), label, font=font(17), fill=GRAY)
    if tag:
        tf = font(13)
        tw = text_w(draw, tag, tf)
        draw.text((x + w - 16 - tw, y + 12), tag, font=tf, fill=GRAY)


def panel_thermo(draw, x, y, w, h, value):
    """情绪温度计：0-100 渐变条 + 冰点/过热标尺 + 当前值指针。"""
    x0, x1 = x + 22, x + w - 22
    track_y = y + 58
    track_h = 14
    # 冰点(蓝) -> 中性(黄) -> 过热(红) 渐变条
    for px in range(x0, x1 + 1):
        t = (px - x0) / max(1, (x1 - x0))
        if t < 0.5:
            col = lerp(ICE, YELLOW, t * 2)
        else:
            col = lerp(YELLOW, RED, (t - 0.5) * 2)
        draw.line([(px, track_y), (px, track_y + track_h)], fill=col)
    draw.rounded_rectangle([x0, track_y, x1, track_y + track_h], radius=4,
                           outline=(255, 255, 255, 80), width=1)
    # 标尺刻度 0 / 50 / 100
    sf = font(12)
    for pos, lab in ((0, "0"), (0.5, "50"), (1.0, "100")):
        lx = x0 + int((x1 - x0) * pos)
        draw.line([(lx, track_y + track_h + 3), (lx, track_y + track_h + 7)], fill=GRAY, width=1)
        lw = text_w(draw, lab, sf)
        draw.text((lx - lw // 2, track_y + track_h + 9), lab, font=sf, fill=GRAY)
    # 当前值指针 + 数值 + 区间
    v = max(0.0, min(100.0, value))
    mx = x0 + int((x1 - x0) * (v / 100.0))
    draw.polygon([(mx - 7, track_y - 13), (mx + 7, track_y - 13), (mx, track_y - 2)],
                 fill=ACCENT)
    if v <= 20:
        zone, zc = "冰点", ICE
    elif v >= 80:
        zone, zc = "过热", RED
    else:
        zone, zc = "中性", LIGHT
    vf = font(22, bold=True)
    val_s = f"{value:.1f}"
    draw.text((x + 22, y + 80), val_s, font=vf, fill=WHITE)
    zf = font(15)
    draw.text((x + 22 + text_w(draw, val_s, vf) + 10, y + 84), zone, font=zf, fill=zc)
    bf = font(12)
    draw.text((x + 22, y + 110), "冰点 ≤20 · 过热 ≥80", font=bf, fill=GRAY)


def panel_adv_dec(draw, x, y, w, h, up, down):
    """涨跌家数：红涨 / 绿跌 横向条形。"""
    x0 = x + 22
    bw = w - 44
    bar_h, gap = 16, 12
    scale = max(up, down, 5000)
    y0 = y + 48
    for i, (lab, val, col) in enumerate((("涨", up, RED), ("跌", down, GREEN))):
        by = y0 + i * (bar_h + gap)
        lf = font(15, bold=True)
        draw.text((x0, by), lab, font=lf, fill=col)
        vw = text_w(draw, lab, lf)
        bx0 = x0 + vw + 12
        bx1 = bx0 + int((bw - vw - 12) * (val / scale))
        draw.rounded_rectangle([bx0, by, bx1, by + bar_h], radius=4, fill=col)
        vf = font(15, bold=True)
        draw.text((x0, by + bar_h + 6), f"{val:,}", font=vf, fill=LIGHT)
    bf = font(12)
    draw.text((x0, y + 110), "红涨 · 绿跌（A股口径）", font=bf, fill=GRAY)


def panel_signals(draw, x, y, w, h):
    """信号灯：买/卖/辅买/追 四色圆点（A股红买绿卖约定，与平台信号灯 buy 红/ sell 绿 一致）。"""
    items = (("买", RED), ("卖", GREEN), ("辅买", PURPLE), ("追", ORANGE))
    y0 = y + 48
    for i, (lab, col) in enumerate(items):
        iy = y0 + i * 25
        draw.ellipse([x + 26, iy, x + 42, iy + 16], fill=col)
        draw.text((x + 50, iy - 1), lab, font=font(17), fill=LIGHT)


def panel_lab(draw, x, y, w, h):
    """策略实验室：迷你 sparkline + 能力标签。"""
    x0, x1 = x + 22, x + w - 22
    cy = y + 62
    pts = []
    n = 26
    for i in range(n):
        t = i / (n - 1)
        px = x0 + t * (x1 - x0)
        py = cy - 9 * math.sin(t * 5.2 + 0.7) + 6 * math.cos(t * 9.1)
        pts.append((px, py))
    draw.line(pts, fill=ACCENT, width=3, joint="curve")
    draw.ellipse([pts[-1][0] - 4, pts[-1][1] - 4, pts[-1][0] + 4, pts[-1][1] + 4], fill=ACCENT)
    bf = font(13)
    draw.text((x + 22, y + 96), "凯利回测 · 降亏过滤31项", font=bf, fill=GRAY)
    draw.text((x + 22, y + 112), "AI 速递 · DeepSeek", font=bf, fill=GRAY)


def load_live_data():
    """读当日 overview.json，返回 (情绪分, 涨, 跌) 或 None。"""
    path = "static-site/data/overview.json"
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        score = (d.get("scores") or {}).get("a_sentiment", {}).get("value")
        up_list = d.get("a_width_up_count_6m") or []
        down_list = d.get("a_width_down_count_6m") or []
        up = up_list[-1].get("value") if up_list else None
        down = down_list[-1].get("value") if down_list else None
        if score is None or up is None or down is None:
            return None
        return (float(score), int(up), int(down))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="生成 OG 分享图 static-site/og.png")
    ap.add_argument("--live", action="store_true",
                    help="从 static-site/data/overview.json 读当日真实情绪分/涨跌家数（无数据时回退示例值）")
    args = ap.parse_args()

    live = load_live_data() if args.live else None
    if live:
        score, up, down = live
        tag = PANEL_TAG_LIVE
        print(f"● 使用当日实时数据: 情绪分={score} 涨={up} 跌={down}")
    else:
        score, up, down = 68.4, 3100, 1800
        tag = PANEL_TAG_EXAMPLE
        if args.live:
            print("! --live 但无可用实时数据（overview.json 缺失/字段不全），回退示例值")

    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)
    vgrad(draw)

    # 顶部品牌条：左 tdsignal 蓝标 + 仓库名，右中文主名
    draw.rounded_rectangle([60, 56, 200, 92], radius=18, fill=ACCENT)
    draw.text((78, 62), "tdsignal", font=font(20, bold=True), fill=WHITE)
    draw.text([220, 64], "trade-data-signal", font=font(18), fill=GRAY)
    brand = "信号实验室 · tdsignal"
    bf = font(22, bold=True)
    bw = text_w(draw, brand, bf)
    draw.text((1140 - bw, 62), brand, font=bf, fill=WHITE)

    # 主标题 + slogan
    draw.text((60, 150), "信号实验室", font=font(82, bold=True), fill=WHITE)
    draw.text((60, 252), "盘后复盘 · 情绪温度 · 买卖点信号 · 策略实验室", font=font(34), fill=LIGHT)

    # 分隔线
    draw.line([(60, 330), (1140, 330)], fill=(255, 255, 255, 40), width=1)

    # 可视化面板行（4 面板）
    cy, cw, gap = 372, 250, 18
    xs = [60, 60 + cw + gap, 60 + (cw + gap) * 2, 60 + (cw + gap) * 3]

    # 半透明面板底框画在 RGBA overlay，先合成，再画不透明内容
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for x in xs:
        panel_bg(odraw, x, cy, cw, 130)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    panel_label(draw, xs[0], cy, cw, "情绪温度", tag)
    panel_thermo(draw, xs[0], cy, cw, 130, score)
    panel_label(draw, xs[1], cy, cw, "涨跌家数", tag)
    panel_adv_dec(draw, xs[1], cy, cw, 130, up, down)
    panel_label(draw, xs[2], cy, cw, "信号灯")
    panel_signals(draw, xs[2], cy, cw, 130)
    panel_label(draw, xs[3], cy, cw, "策略实验室")
    panel_lab(draw, xs[3], cy, cw, 130)

    # 底部域名（主站）+ 描述
    draw.text((60, 548), "ss.fx8.store", font=font(26, bold=True), fill=ACCENT)
    draw.text((60, 586), "信号实验室 · tdsignal　A股 / 港股 / 全球  ·  综合情绪分 / 跨市场评分 / 行业热力图 / 模拟回测",
              font=font(16), fill=GRAY)

    img.save("static-site/og.png", "PNG")
    print("✓ static-site/og.png 生成 (1200x630)")


if __name__ == "__main__":
    main()
