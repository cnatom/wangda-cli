# 使用与配置

## 运行环境

需要 Python 3.11+、Git 和 Google Chrome / Chromium。首次登录需要图形界面。Skill 初始化时会检查运行环境，并使用 uv 安装 CLI；缺少 Python、uv 或浏览器时会提示补齐，不自动修改系统环境。

## 命令行

```sh
wanda doctor --json
wanda login
wanda auth --probe --json
wanda auth --username '<工号或手机号>' --json
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

`--watch` 让队列常驻：一轮跑完后不退出，把还没确认完成的链接重新排队，`--watch-interval`（默认 1800 秒）后再复查，最多 `watch_max_passes`（默认 6）轮，超了按最后一轮状态收尾。配合 `--background` 和一台国内常开的机器，就是无人值守模式；`status`/`pause`/`stop` 行为不变。

登录拿到的 token 声明有效期约 4 小时（`expires_in: 14400`）。这是**提示而不是吊销**：到期时 runner 会先用只读接口 `/api/v1/human/member/center` 问一次平台还认不认这个 token，仍然认就继续跑并在 `status` 里记 `session_note: declared_expired_but_accepted`；只有平台真的返回 401/403 才停到 `waiting_login` 等重新登录。探针失败（网络异常）不会中断队列，因为真过期的话下一页就会直接露出登录墙。该接口不写任何学习数据。

，且平台用的是 implicit 授权、**没有 refresh_token**，无法静默续期。watch 模式在 token 过期时不会判失败：它会把状态置为 `waiting_login`（`reason=session_expired_waiting_for_auth`）并原地等待，你在任意时刻重跑一次 `wanda auth` 写入新 token，队列随后自动继续，不需要重新排队或重启。等待上限由 `session_wait_seconds`（默认 6 小时）控制。

`certificate` 只点击平台已经显示的「领取证书」，领取后刷新页面确认服务端状态。`already_claimed` 表示此前已领取；`not_eligible` 表示条件未满足；`no_certificate` 表示该专题没有证书入口，三者都不会被绕过。`--download DIR` 会在领取后打开证书弹窗并把 PNG 保存到指定目录；默认不下载。刚完成手动登录时加 `--headed` 可复用当前可见窗口。证书含姓名和证书编号，只保存在本地，不要上传或粘贴到聊天、日志和 issue。

`status` 自带 `progress` 汇总，一条命令就能回答「刷到哪了」：`completed` / `total` / `percent`、各状态计数（`pending`、`running`、`unconfirmed`、`failed`）、`current`（正在播的课程 id、`position` / `duration`、`rate`、`sections` 小节计数器）、`eta`（剩余时间估算）、`pass`（watch 第几轮）与 `session_note`（如 `declared_expired_but_accepted`）。

`eta` 的算法：把本次 run 里每门课 `course_start → course_done` 的实测耗时取平均，加上当前课程剩余时长（`(duration - position) / rate`），再乘以待跑门数，所以它是「按这台机器、这个账号当前的真实节奏」推出来的，不是理论值；没有历史样本时退化为只算当前课程剩余，并标 `basis: current_course_only`。`unconfirmed` 项不计入 ETA，它们要等 watch 下一轮重试。

后台启动返回启动确认，最终结果以 `status` 为准；不加 `--background` 则前台运行。查询状态和日志不会打开或导航浏览器。运行期间不要执行 `inspect` 或 `certificate`。

`--background` 的 runner 和 worker 在 Windows 上使用隐藏控制台启动，不会额外弹出终端窗口。若仍看到旧终端，说明是旧版本遗留进程；先 `stop`，再用当前版本 `run`/`resume`。

`--continue-on-error` 让队列在单个链接失败或 `unconfirmed` 后继续处理后续链接；同一专题内某门必修课失败时也会跳过该门并继续后续课程。登录失效、暂停和停止仍立即终止。失败项在队列中保留 `failed`/`unconfirmed`，最终整体状态仍为 `failed`/`unconfirmed`，不会把失败项算作完成。

必修项类型处理：`10` 走完整课程会话；`1` 文档、`2` 图片、`6` 单项视频点击卡片后让它的查看页停留 `item_dwell_seconds`（默认 20 秒），由平台自己记账；`3` 是普通 URL 点击。`9` 考试、`14` 直播、`16` 嵌套专题不会被点击：先把其余必修项跑完，再以 `unconfirmed` 报 `Required items need manual handling: type …`。停留时间不代替完成判定，专题卡片状态没变成「已完成」就是未确认。

注意：`1/2/6` 在参考工具里是**课程内小节**的类型；本账号的专题卡片目前只观测到 `10` 与 `3`，所以专题页上的 `1/2/6` 属于未验证分支（出现时同样点击+停留，仍以卡片状态判定）。课程内小节的推进由页面内的 worker 按「未完成即点击」处理，与类型无关。

课程完成判定有两级依据：优先看页面的「完成 X 节 / 共 Y 节」计数器；部分课程页不渲染这个计数器，此时退回到「每一节都显示已完成」，并要求连续两拍成立才判完成。两者都取自页面可见状态，不读接口。

专题页有两种布局：标准卡片带 `.study-status`（已完成/学习中/未开始），专区式卡片只有「开始学习/继续学习」按钮、没有状态元素。后者现在也能正常解析（状态记为空、按钮文案存 `btn`）。这类布局无法从卡片确认完成，因此单门课程的 `run` 会在专题卡片复核失败后，回退为按课程页自身计数器/逐节状态确认，结果标 `confirmation: course_page`；只要专题页上有任何状态元素，就不会走这个回退。

暂停、停止和完成会关闭专用浏览器并保留登录态。`login` 会在你登录并关闭那扇窗后自动接管并写入会话。机器重启后需显式恢复任务。

## 登录

默认用 `wanda login`：它用专用 profile 打开一扇**不带调试端口**的普通 Chrome 窗口，你在这扇窗里完成短信登录，然后**把它关掉**，CLI 会立刻附着同一 profile、读出网页自己写下的 `localStorage["token"]`，写进 `<data-dir>/session.json`（0600）。

```sh
wanda login                      # 打开干净窗口，登录完关窗即可，默认最多等 600 秒
wanda login --timeout 1200       # 慢慢来
```

为什么要关窗再接管：登录页（`/oauth/`）内嵌 devtools 检测，只要标签页带着已连接的调试会话，点「获取验证码」后页面会自己跳到 `about:blank`（控制台留 `You don't have permission to use DEVTOOL!【type = 6】`）。所以登录必须发生在没有调试端口的窗口里，CLI 只能在事后附着。视频播放页不受该检测影响。

接管时的判定来自页面可见状态，而不是「localStorage 里有没有 token」：残留的过期 token 在 `about:blank` 上也读得出来（空白页继承 opener 的源），所以必须同时满足「在 wangda.chinamobile.com 上」「没有登录墙」「正文非空」才认。任何一条不满足都会报 `LoginRequired`，不会把过期会话当成登录成功。

登录态本身也存在 profile 里：即使 `session.json` 缺失，`inspect`/`run` 用同一个 profile 也能直接用。`session.json` 的作用是让 `doctor` 能报剩余时间，并给 `--watch` 的过期等待提供依据。

### 免图形界面的协议登录（`wanda auth`）

`wanda auth` 走与网页相同的短信登录链路，不需要浏览器：读 `/oauth/api/v1/setting` 拿 RSA 公钥，对 `dynamic-password-sign` 和 `members-encrypt` 使用与前端一致的 hybrid 信封（每次随机 16 位密钥，RSA 包裹成 `secureKey`，报文 AES-128-ECB 加密成 `secureData`），`auth` 换到 token 后写入 `<data-dir>/session.json`（权限 0600）。

```sh
wanda auth --probe --json                                  # 只读校验公钥与 sign 接口，不发短信
wanda auth --username '<工号或手机号>' --json               # 发短信后在本地提示符输入验证码
printf '%s\n' '<验证码>' | wanda auth --username '<...>' --code-stdin --json
```

验证码只在本地终端读取，不写日志、不进快照；`session.json` 里是 token，不要粘贴、上传或提交。`auth` 只负责认证，课程仍由浏览器真实播放：`inspect`/`run` 打开页面前会把这个 token 注入专用 profile 的 `localStorage["token"]`，所以登录成功后不需要再开浏览器窗口。token 有效期约 4 小时（`expires_in` 14400），`doctor` 报 `session.fresh: false` 时重跑 `auth`。

平台前置 WAF 会拦境外数据中心出口：实测美国 VPS 访问首页直接返回「安全卫士应用防护平台」405 或连接中断。远程长跑要用国内出口（家宽或国内 VPS），不要用境外云主机。

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
