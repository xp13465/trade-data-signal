#!/usr/bin/env python3
"""生成 qr.js：公网域名 URL 的 QR 矩阵数据，供分享图 canvas 绘制二维码。

矩阵为 0/1 二维数组（1=黑格），前端 drawShareCard 用 fillRect 同步绘制，
无需加载外部图片（避免 toDataURL 跨域污染 + 异步竞态）。
写 static-site/qr.js。
"""
import qrcode

URL = "https://tdsignal-ujpzw01zm.maozi.io/"


def main():
    qr = qrcode.QRCode(
        version=None,  # 自动选最小版本（URL 长度决定）
        error_correction=qrcode.constants.ERROR_CORRECT_M,  # 中等纠错，扫码可靠
        box_size=1,
        border=0,  # quiet zone 由前端绘制时补
    )
    qr.add_data(URL)
    qr.make(fit=True)
    modules = qr.modules  # list[list[bool]]
    n = len(modules)
    rows = []
    for row in modules:
        rows.append("[" + ",".join("1" if c else "0" for c in row) + "]")
    js = (
        "// 自动生成，勿手改。由 scripts/gen_qr_js.py 生成。\n"
        f"// 扫码访问：{URL}\n"
        f"window.QR_URL = {URL!r};\n"
        f"window.QR_SIZE = {n};\n"
        f"window.QR_MODULES = [\n" + ",\n".join(rows) + "\n];\n"
    )
    for path in ["static-site/qr.js"]:
        with open(path, "w") as f:
            f.write(js)
        print(f"✓ {path} ({n}x{n} 矩阵)")


if __name__ == "__main__":
    main()
