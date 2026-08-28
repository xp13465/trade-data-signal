# 信号凯利移动端参数栏错位修复方案（2026-08-26）

## 结论

- 基线：main `705304269`。
- 只改 `static-site/lab.css` 的 `@media (max-width: 600px)` 凯利参数段；不改 DOM、JS、算法和数据。
- 根因不是 toggle 漏写换行，而是移动端把两个语义不同的组都强行放进 `repeat(2, 1fr)` 网格：
  - `.lab-sigkelly-toggle-group-rec` 内的组标题是 `white-space: nowrap`，没有跨双列。它的最小内容宽度把一个 grid track 撑大，另一个 track 被压到极窄。
  - `.lab-sigkelly-toggle-group-poscap` 不是同质 toggle 列表，而是「AI仓位建议 label + K 按钮 + AI降亏总开关 + 模式选择 + 展开/重置按钮」的复合控制流。两列网格会把这些相关控件拆散并挤压。
- 已用 Playwright/Chromium 以 390×844、mobile/touch 环境复现：
  - 参数容器宽约 `366px`。
  - 推荐组实际内容宽 `851px`，grid tracks 计算为 `547.688px 14px`。
  - 多个推荐 toggle 渲染成宽 `14px`、高 `189-256px` 的窄高条。
  - 仓位控制组的第一个 label 内容需求宽 `745px`，实际格宽只有 `45px`。
- 注入候选 CSS 后实测：
  - 推荐组 tracks 变为 `174px 174px`。
  - 推荐组高度从约 `1885px` 降到约 `654px`。
  - 子项宽度恢复到 `174px`，高度回到正常 `25-77px` 区间。
  - 仓位控制组变为纵向整行堆叠，子项宽度均为约 `342-352px`，无窄列。

## 修改方案

定位：`static-site/lab.css:1925-1935`。

将这一行：

```css
.lab-sigkelly-toggle-group-rec,
.lab-sigkelly-toggle-group-poscap {
  grid-template-columns: repeat(2, 1fr);
  display: grid;
  gap: 4px;
}
```

改为：

```css
.lab-sigkelly-toggle-group-rec {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
}

.lab-sigkelly-toggle-group-rec > .lab-sigkelly-toggle-tier {
  grid-column: 1 / -1;
}

.lab-sigkelly-toggle-group-poscap {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
}

.lab-sigkelly-toggle {
  white-space: normal;
}

.lab-sigkelly-toggle-group-rec > *,
.lab-sigkelly-toggle-group-poscap > * {
  min-width: 0;
  max-width: 100%;
}

.lab-sigkelly-toggle-tier {
  white-space: normal;
}

.lab-sigkelly-fee-label {
  white-space: normal;
}

.lab-sigkelly-kbtns {
  flex-wrap: wrap;
  max-width: 100%;
}

.lab-sigkelly-toggle-detail-btn {
  max-width: 100%;
  white-space: normal;
  text-align: left;
}
```

所有新增规则必须留在现有 `@media (max-width: 600px)` 内。不要改基础样式，也不要改其他 lab 组件的 600px 断点。

## 构建与缓存

1. `python3 scripts/build_min.py`
2. 运行项目的 asset version bump 流程，确保 `index.html` 中 `lab.min.css?v=` 更新。
3. 如部署链要求，同步 bump `sw.js CACHE_VERSION`。
4. 本单不 commit、不 push；实施分支自检后交 reviewer。

## 验收标准

### 移动端 390px

- 打开 `/index.html#lab?sub=sigkelly`。
- 展开「⚙️ 参数」和「AI降亏过滤详情」。
- `.lab-sigkelly-toggle-group-rec` 必须是 grid，tracks 为两个相等的 `minmax(0, 1fr)` 结果；390px 下每列约 `174px`。
- 组标题独占一整行，不再占据单列。
- 所有推荐 toggle 宽度约等于列宽，高度不得出现超过 `120px` 的窄高条。
- `.lab-sigkelly-toggle-group-poscap` 必须是纵向 flex；AI仓位建议、K 按钮、AI降亏过滤、模式下拉、详情按钮各自整行或自然换行，不得互相拆成碎列。
- 页面不得出现横向滚动。

### 桌面零变化

- 在 768px、1024px、1440px 验证凯利参数栏布局不变。
- `.lab-sigkelly-toggle-group-poscap` 在桌面仍保持既有横向 flex/wrap 行为。
- `.lab-sigkelly-toggle-group-rec` 在桌面仍保持既有 flex/wrap 行为。

### 机检

```bash
python3 -m http.server 8123 --bind 127.0.0.1 --directory /Users/linhuichen/code/trade/static-site
```

Playwright 断言要点：

```js
const rec = document.querySelector('.lab-sigkelly-toggle-group-rec');
const poscap = document.querySelector('.lab-sigkelly-toggle-group-poscap');
getComputedStyle(rec).display === 'grid';
getComputedStyle(rec).gridTemplateColumns.split(' ').length === 2;
Math.abs(parseFloat(getComputedStyle(rec).gridTemplateColumns.split(' ')[0]) -
         parseFloat(getComputedStyle(rec).gridTemplateColumns.split(' ')[1])) < 2;
getComputedStyle(poscap).display === 'flex';
getComputedStyle(poscap).flexDirection === 'column';
[...rec.children].every(el => el.getBoundingClientRect().height < 120);
[...poscap.children].filter(el => el.getBoundingClientRect().width > 0)
                    .every(el => Math.abs(el.getBoundingClientRect().width -
                                          poscap.getBoundingClientRect().width + 14) < 4);
document.documentElement.scrollWidth <= window.innerWidth + 2;
```

最后一条中 `+14` 是当前 poscap 左右 padding 的近似值；实施时可直接改断言为「子项 right 不超过容器 right + 2」，避免硬编码 padding。

## 影响面与红线

- 允许：只修改 `static-site/lab.css` 对应 media block，随后重建 min/css 版本号。
- 禁止：改 `lab.js` DOM 结构、过滤算法、回测口径、localStorage key、数据文件。
- 禁止：顺手统一其他组件的 600px 断点。
- 禁止：让 tooltip 逻辑从 CSS `data-tip` 改成 JS 弹层；本单只修布局。
