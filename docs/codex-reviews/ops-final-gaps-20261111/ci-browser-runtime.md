# 浏览器 CI 运行环境收尾

两次独立运行 43036247563、43041098266 的 fx-browser job 均在组合安装步骤耗尽10分钟，实际页面测试未执行；不算页面断言失败，也不算验收通过。中间因后续 push 被 concurrency 取消的运行单独记录，不能混作同一种故障。

43043140084 拆步骤后，固定 playwright@1.62.1 npm 包安装仅2秒成功；后续仍停留在系统依赖安装。已证实的边界是安装链，不声称已经定位到某个 apt 镜像站、锁或 Ubuntu 版本。Playwright该版本 install-deps 实际调用 apt-get update 和 apt-get install，原始时间/步骤/annotations保留在本轮私有证据。

改为官方预装浏览器及系统库的 Playwright v1.62.1-noble 容器，npm仍安装相同1.62.1，固定官方registry返回且与manifest内容散列一致的OCI digest：

`sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`

这消除了每次运行都做 apt 同步的依赖；不增加job总时限，不跳过浏览器测试、不修改真实页面断言。容器含浏览器/系统库而不含项目的 npm Playwright 包，两个版本必须一致。镜像获取本身仍依赖网络，失败须如实保留；不能因此推断所有网络问题根治。

依据：[Playwright官方Docker说明](https://playwright.dev/docs/docker)、[官方CI容器用法](https://playwright.dev/docs/ci#via-containers)、[固定1.62.1依赖安装源码](https://github.com/microsoft/playwright/blob/v1.62.1/packages/playwright-core/src/server/registry/dependencies.ts)。

最终容器真实执行结果、完整head和CI链接以私有总报告为准。当前文档不预写PASS。只影响隔离CI运行环境；未部署生产、未改变系统服务。

## 随后的整套 CI 失败及收尾

固定242ee37a9的浏览器和unit job已通过，但完整脚本统计为5438 tests / 29 failures / 19 errors / 7 skipped，不能称一次全绿。

- 21项失败：裸子进程没加载既有missing-only `_ci_stubs`，本机有akshare而CI没有；补共享垫片，真实producer/notify及网络/进程/写入审计均保留。
- 19个setup调用点：共享DRIVER改了dispatch断言，但R2夹具仍替换旧文本，13个直接与6个间接消费者被唯一性检查拦住；同步锚点且保留所有行为断言。
- 8项失败：本轮新入口加入push和PR列表时顺序不一致，发布门禁要求逐项相等，按预期fail-closed。真实旧输入复现8 failed / 104 passed。改为唯一 `&ops_inputs` 路径列表，PR通过alias复用，触发集合与所有job不变，发布门禁代码/断言不改。

GitHub官方支持[工作流YAML anchors/aliases](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#yaml-anchors-and-aliases)。这次删除第二份完整列表，后续新增入口只维护一处。最终整套CI结论仍以最终固定head的原始记录为准。

采用alias后的首轮定向验收有25个负控夹具失败（87 passed），原记录保留：PyYAML会让两处引用同一个list，旧负控在两处各remove一次等于删同一对象两次；单独改PR也会同时改push，未构造出预期漂移。现在仅在负控临时数据中复制两份独立list，再执行原删除/漂移操作及原门禁断言；生产仍唯一列表，未放宽生产判断或删除负控。
