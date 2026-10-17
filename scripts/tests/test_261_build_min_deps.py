# -*- coding: utf-8 -*-
"""#261 选项①: build_min 依赖面机检(映射一致性 + CSS 压缩), 供 CI ⑧ 步跑。

背景: `.github/workflows/ci.yml` 的「部署版本一致性·校验3」(min 内容 == git HEAD 源重建,
`scripts/check_version_consistency.py`)原有 step 级 continue-on-error, 注释标注其转正前提为
「P0-1 补 build_min pytest + pip install rcssmin」(#261 选项①)。本文件补上 build_min 侧
可 CI 化的部分, 使该前提名副其实:

  1. **映射一致性**:`check_version_consistency.MIN_PAIRS` 与 `build_min.PAIRS` 是两份手写副本
     (一份带 `static-site/` 前缀、一份不带)。若二者漂移, 校验3 会静默比对错误的配对集合 = 假绿,
     机检锁死(与 §22「代码内常量登记点必须机检比对一致」同精神)。
  2. **CSS 压缩**:rcssmin 可导入时, `build_min._minify_css_content` 应真压缩(去注释/空白、变短);
     未装则 skip。CI ①③b 步已 `pip install rcssmin` ⇒ CI 上应真跑(不是 skip)。

**显式不测 JS(terser)侧(§10.8 边界声明)**:`npx terser` 首次运行需联网下载, 放进 CI 会引入
网络依赖(不稳、且拖慢常驻门禁), 与 ci.yml 校验3 的「尽力而为」定位一致 ⇒ 本文件不测 JS 压缩路径,
不假装覆盖。terser 侧的真实覆盖由校验3 步(联网可用时)承担。
"""
from __future__ import annotations

import pytest

import build_min
import check_version_consistency as cvc

_PREFIX = "static-site/"


def test_min_pairs_match_build_min_pairs():
    """校验3 的配对集合(MIN_PAIRS)必须与 build_min.PAIRS 逐项相同(防两份手写副本漂移致假绿)。"""
    assert all(s.startswith(_PREFIX) and d.startswith(_PREFIX) for s, d in build_min.PAIRS), (
        f"build_min.PAIRS 出现非 {_PREFIX!r} 前缀项: {build_min.PAIRS}"
    )
    expected = [(s.removeprefix(_PREFIX), d.removeprefix(_PREFIX)) for s, d in build_min.PAIRS]
    assert cvc.MIN_PAIRS == expected, (
        "MIN_PAIRS 与 build_min.PAIRS 漂移(校验3 会比对错误的配对集合, 属假绿):\n"
        f"  check_version_consistency.MIN_PAIRS = {cvc.MIN_PAIRS}\n"
        f"  build_min.PAIRS 换算            = {expected}"
    )


def test_css_minify_really_compresses():
    """rcssmin 可用时, CSS min 应真压缩(去注释、去多余空白、变短)。未装则 skip(CI 已装 ⇒ 真跑)。"""
    pytest.importorskip("rcssmin", reason="rcssmin 未装(CI ③b 步 pip install rcssmin; 本地可选)")
    src = b"/* header comment */\n.a {\n    color: red;\n}\n\n.b {  margin : 0 ; }\n"
    out = build_min._minify_css_content(src)
    assert out != src
    assert b"/*" not in out, f"rcssmin 未去掉注释: {out!r}"
    assert len(out) < len(src), f"压缩后未变短: {len(out)} !< {len(src)}"