# 稳定性维护：第三阶段（2.0.4）

日期：2026-09-19。基线：2.0.3 发布后的 5fe0191。分支：stability-stage3。
以下保留本地开发阶段记录，当时不包含推送和发布。2026-09-22 用户另行授权发布，结果见末尾。

## Refactor Gate Decision

- Module：CLI → BLREC_IPV4 → requests / aiohttp 的启动网络策略。
- Structural decision：Local Fix；Execution decision：Local Fix Only。
- Triggered thresholds / Evidence：P1，默认启动与 `--no-ipv4` 均写入 `1`；P2，`bool('False')`、`bool('0')` 均为真，已用真实参数解析及隔离进程复现。
- Behavior contract：显式命令行参数优先于环境变量；缺省允许系统选择 IPv4/IPv6。环境变量接受忽略大小写及首尾空白的 `1/true/yes/on` 和 `0/false/no/off`，未设置或空串为关闭强制 IPv4。无效值在启动前报错且不输出原始值；显式参数可覆盖无效环境值。
- State ownership：一个无副作用的解析函数供 CLI 和网络模块共用；网络模块仍在首次导入时应用启动策略，不支持运行中修改环境或模块热重载。
- Smallest safe next step：三态命令行参数、共享解析、隔离进程回归测试。
- Expected files：cli/main.py、bili/net.py、新增 bili/network_settings.py、tests/test_network_settings.py，另附本说明。
- Forbidden files and changes：连接池生命周期、录制逻辑、配置格式、HTTP 接口、礼物兼容、Windows 启动脚本、依赖及发布流程。
- Pre-change baseline：原 35 项测试中 33 项通过、2 项跳过。新增 7 项测试在修改前出现 14 处失败断言（含参数化子用例）。
- Verification gate：实际 Typer 参数入口、独立进程验证两种 HTTP 客户端的网络策略、原网络生命周期测试及全套回归、独立复核。
- Patch budget：单一行为链，源码和测试 4 文件 / 180 行，维护说明不超过 60 行；总计 5 文件 / 240 行。实际 5 文件 / 186 行增删，完整工作区范围检查和差异检查通过。相比默认预算增加的是隔离进程测试，不扩大功能。
- Deletion safety：不删除文件、配置或用户数据，仅替换错误的布尔判断。
- Rollback path：本地独立提交，可单独撤回本阶段提交，不重置用户工作区。
- Deferred risks：真实 IPv6 线路、B 站可达性、容器和长时运行需要独立验收；不等同于离线测试通过。
- Authorization status：approved local fix。使用 code-quality-workflow，已核对 A0 目标、红线和验收。

## 验证与交接

- 新增 7 项回归测试，覆盖命令行优先级、真假环境值、非法值不回显、系统不支持 IPv6、帮助与版本入口；使用独立子进程避免污染其他测试的网络设置。
- 全套 42 项测试：40 项通过、2 项跳过（Windows 不适用的 POSIX 权限检查和已取消要求的私有样本）。未读取或查找录制样本。
- 独立只读复核通过，并另行复跑全部 14 项网络测试；真实 `python -m blrec` 的非法环境返回 2，非法环境下 `--version` 仍返回 0。CLI 导入不会提前加载网络模块。
- 本机真实 HTTP 探针：自动模式下 requests / aiohttp 均成功访问 IPv4、IPv6 回环地址；强制 IPv4 时两者均能访问 IPv4、拒绝 IPv6。四种组合、两种客户端共 8 次请求符合预期；没有连接外网。这只是本机协议栈证据，不代表真实 IPv6 线路或 B 站可达性。
- 本地环境：Windows / Python 3.12.14 / aiohttp 3.9.5，复用原目录部分依赖；4 个源码/测试文件通过 Python 3.11 语法检查，但不等同于 Python 3.11 实际运行验收。
- 本阶段不推送、不建发布标签；程序版本暂为 2.0.3。下次获准发布时递增至 2.0.4，并重新执行双架构容器验收，不能沿用 2.0.3 的云端结果。

## 使用变化与未验证边界

- 默认启动现在允许系统选择 IPv4/IPv6，修复过去无条件强制 IPv4 的错误。若网络的 IPv6 线路不稳定，可显式传 `--ipv4`，或设 `BLREC_IPV4=1`，保持旧版实际效果；现有 Windows 启动脚本已显式传该参数，本轮未改。
- `--no-ipv4` 表示不强制 IPv4，不表示只用 IPv6；系统不支持 IPv6 时仍使用 IPv4。该开关控制外发请求，不改变网页监听地址，后者仍由 `--host` 决定。
- `BLREC_IPV4` 必须在首次导入网络模块前设置。网页内重启不重新加载该策略；更改部署环境后须重新启动程序进程。不支持先加载 net 再嵌入 CLI 启动、模块热重载或运行中切换策略。
- 未做本阶段 Docker/Linux 双架构、真实直播或长时断网重连验收；未修改上一阶段记录的并发重启、部分初始化失败等独立风险。
- 下一门槛：用户确认本地结果后，单独授权验收发布。没有把自动测试结果标成用户已验收。

## 2.0.4 发布结果

2026-09-22 获准发布。仅补充版本、更新日志与 Docker 部署说明，3 文件 / 45 行增删；源码行为仍为 924c344 的已复核修复。中途执行权限检查超时，用户确认重试后继续，没有绕过验收。

- 本地复跑 42 项：40 项通过、2 项跳过。独立审查沿用开发阶段的同一修复结论，本轮独立复验曾受工具阻塞，不误记为新的独立执行结果。
- 主分支和正式标签两次云端验收通过；正式版本在 Python 3.11 / Linux amd64、arm64 原生环境各 41 项通过、1 项已免除的样本回放跳过。
- 双架构真实容器网页、API、程序及安装包版本、FFmpeg、依赖、配置写入和重启保留均通过。
- 候选与正式镜像匿名拉取和启动通过；发布机额外通过 QEMU 启动 ARM64。
- 独立匿名读取 GHCR：源码地址、提交、2.0.4 版本、GPL-3.0-only 标签及双架构清单正确；latest 与 2.0.4 摘要一致，2.0.3 摘要未改变。
- 真实直播、外网 IPv6 可达性、长期录制和断网重连仍未验收。不再要求私有样本。

源码提交：`013710b69c88937fa91c7bed7a023ba5c04c6d8b`，标签：`v2.0.4`。

多架构摘要：`sha256:113de0bcb8e87460adfc040acd80a2b7aee2f921873a18be28178f67da956874`。

- amd64：`sha256:b1893edc38fc7f5881289150e29a8bb1614a195562755141b1197e1d56b691f9`
- arm64：`sha256:0489d2f91ddb8e884b85c5d1039ee9b5144c4eda21abb107bd184488623081dd`
- [主分支验收](https://github.com/junpakugenso/blrec/actions/runs/35738716481)
- [正式发布验收](https://github.com/junpakugenso/blrec/actions/runs/35743130065)
- [GitHub 发布说明](https://github.com/junpakugenso/blrec/releases/tag/v2.0.4)
- [启动、升级与回退](docker-maintenance.md)
