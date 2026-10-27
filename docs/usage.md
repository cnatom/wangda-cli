# 使用与配置

## 运行环境

需要 Python 3.11+、Git 和 Google Chrome / Chromium。首次登录需要图形界面。Skill 初始化时会检查运行环境，并使用 uv 安装 CLI；缺少 Python、uv 或浏览器时会提示补齐，不自动修改系统环境。

## 命令行

```sh
wanda doctor --json
wanda login
wanda inspect '<课程或专题链接>' --json
wanda certificate '<专题或专题课程链接>' --json
wanda certificate '<专题或专题课程链接>' --download ./certificates --json
wanda run '<链接 A>' '<链接 B>' --rate 1.5 --background --json
wanda run '<链接 A>' '<链接 B>' --continue-on-error --background --json
wanda status --json
wanda logs --tail 10 --json
wanda pause --json
wanda resume --background --json
wanda stop --json
```

占位符替换为网大主站完整 HTTPS 链接，支持专题和专题内课程：

```text
https://wangda.chinamobile.com/#/study/subject/detail/EXAMPLE_TOPIC/1
https://wangda.chinamobile.com/#/study/course/detail/subject-course/EXAMPLE_COURSE/6/EXAMPLE_TOPIC
```

`run` 新建队列，多个链接顺序执行。`resume` 保留队列并跳过已确认完成的链接。课程续播位置由平台保存的进度决定。

`certificate` 只点击平台已经显示的「领取证书」，领取后刷新页面确认服务端状态。`already_claimed` 表示此前已领取；`not_eligible` 表示条件未满足；`no_certificate` 表示该专题没有证书入口，三者都不会被绕过。`--download DIR` 会在领取后打开证书弹窗并把 PNG 保存到指定目录；默认不下载。刚完成手动登录时加 `--headed` 可复用当前可见窗口。证书含姓名和证书编号，只保存在本地，不要上传或粘贴到聊天、日志和 issue。

后台启动返回启动确认，最终结果以 `status` 为准；不加 `--background` 则前台运行。查询状态和日志不会打开或导航浏览器。运行期间不要执行 `inspect` 或 `certificate`。

`--background` 的 runner 和 worker 在 Windows 上使用隐藏控制台启动，不会额外弹出终端窗口。若仍看到旧终端，说明是旧版本遗留进程；先 `stop`，再用当前版本 `run`/`resume`。

`--continue-on-error` 让队列在单个链接失败或 `unconfirmed` 后继续处理后续链接；同一专题内某门必修课失败时也会跳过该门并继续后续课程。登录失效、暂停和停止仍立即终止。失败项在队列中保留 `failed`/`unconfirmed`，最终整体状态仍为 `failed`/`unconfirmed`，不会把失败项算作完成。

暂停、停止和完成会关闭专用浏览器并保留登录态。`login` 有意保持窗口，供本人登录；结束后可用 `stop` 关闭。机器重启后需显式恢复任务。

## 配置

优先级：CLI > `WANDA_*` 环境变量 > TOML > 默认值。`resume` 使用之前的配置作为低优先级基线，当前显式设置优先。示例见 [config.example.toml](../config.example.toml)。

```sh
wanda --config ./config.toml doctor
wanda run '<链接>' --data-dir ./.runtime --background
wanda status --data-dir ./.runtime
```

同一任务每次调用必须使用相同配置和数据目录。默认目录由 platformdirs 选择：macOS Application Support、Linux XDG data、Windows 本地应用数据目录。浏览器 profile、状态和日志保存在本地；CDP 默认使用空闲本地端口。

环境变量：`WANDA_CONFIG`、`WANDA_DATA_DIR`、`WANDA_PROFILE`、`WANDA_BROWSER`、`WANDA_PORT`、`WANDA_RATE`、`WANDA_HEADED`、`WANDA_CONTINUE_ON_ERROR`、`WANDA_RETRIES`、`WANDA_STALE_SECONDS`、`WANDA_CONFIRMATION_SECONDS`、`WANDA_POLL_SECONDS`。

不要使用日常浏览器 profile。登录态和日志不要共享或提交。参见 [安全说明](../SECURITY.md)。

## 支持范围

- 支持视频项（type 10）和 URL 项的正常页面点击（type 3），未知必修类型需人工处理。
- 支持 1.0 / 1.2 / 1.5 倍速，实际可用性以平台规则为准。
- 专用浏览器以 `--mute-audio` 启动，播放器同时设置 `muted` 和 `volume=0`，播放默认完全静音。
- 完成判定核对课程目录和对应专题卡片；确认超时返回 `unconfirmed`，不反复重播。
- 证书领取只使用平台可见的「领取证书」入口，可保存平台生成的证书 PNG；不伪造资格或证书。
- 不做考试、不伪造学时或完成记录、不绕过账号并发限制。
- 页面和账号权限变化可能影响运行，首次使用建议验证一门短课程。

CI 覆盖 macOS / Linux / Windows 和 Python 3.11 / 3.14。真实账号视频课验收范围为 macOS 27.0 / Chrome 155，不能据此声称所有系统、课程类型均已实测。参见 [验证说明](verification.md) 和 [验收报告](acceptance-2026-10-21.md)。

## 开发

```sh
git clone https://github.com/cnatom/wangda-cli.git
cd wangda-cli
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
uv build
```

运行时无需 Node.js；开发中的 DOM 回放测试需要 Node.js。实现入口见 [架构](architecture.md) 和 [代码清单](../CODE_INVENTORY.md)。
