# wangda-cli

中国移动网大真实播放工具。**独立 CLI + 通用 Agent Skill**，不绑定 Hermes、Claude Code、Codex 或其他智能体，也可以由人直接运行。

仅做真实播放和正常页面交互，不伪造学时、心跳或完成记录，不绕过同账号并发限制。非中国移动官方项目。使用前确认账号授权及平台、单位的学习规定；自动播放不代表本人理解或满足必须亲自参与的培训义务。

## 能做什么

- 专用 Chrome/Chromium，手动登录后顺序播放课程与专题中的必修项。
- 多链接持久化队列，暂停、停止、恢复及有限重试。
- 后台独立运行，不需要模型持续在线或额外系统守卫。
- `status` / `logs` 只读本地状态，不导航页面、不打断播放。
- 结构化 JSON、明确退出码，可被任何具备本地命令执行能力的智能体调用。
- 通用 `SKILL.md` 随包分发，支持标准技能加载，也支持直接读取说明。

## 安装

需要 **Python 3.11+** 和已安装的 **Google Chrome / Chromium**。登录需要图形界面。运行不需要 Node.js；只有开发测试中的 DOM 回放需要 Node。

使用 uv：

```sh
uv tool install 'git+https://github.com/cnatom/wangda-cli.git'
wanda doctor --json
```

或使用 pip，建议在虚拟环境中安装：

```sh
python -m pip install 'git+https://github.com/cnatom/wangda-cli.git'
wanda doctor --json
```

尚未发布到 PyPI，不要直接安装未经核实的同名包。

## 快速开始

```sh
# 用户本人在专用窗口完成登录，不向智能体提供验证码或 token
wanda login

# 只在没有任务运行时查看课程/专题清单
wanda inspect '<网大课程或专题链接>' --json

# 后台顺序执行；多个链接也按顺序，不会并发
wanda run '<链接 A>' '<链接 B>' --rate 1.5 --background --json

# 查询不会打开网页或改变浏览器模式
wanda status --json
wanda logs --tail 10 --json

wanda pause --json
wanda resume --background --json
wanda stop --json
```

`<...>` 是占位符，换成完整链接。支持的链接形式：

- `https://wangda.chinamobile.com/#/study/subject/detail/EXAMPLE_TOPIC/1`
- `https://wangda.chinamobile.com/#/study/course/detail/subject-course/EXAMPLE_COURSE/6/EXAMPLE_TOPIC`

示例 ID 为虚构。链接必须来自网大 HTTPS 主站，不接受其他域名、携带凭据的查询参数或任意页面路径。

不加 `--background` 时前台运行，结束返回任务结果；后台运行先返回启动确认，之后以 `status` 为准。`run` 新建队列，`resume` 保留已有队列、跳过已确认完成的链接。部分课程能续到哪里由平台保存的进度决定，不承诺零进度损失。

`pause` / `stop` / 完成会关闭专用浏览器并保留登录态。`login` 则有意保持窗口，供用户登录；不再需要时用 `stop` 关闭。登录、巡检和运行共用锁，运行期间不会允许另一个命令接管窗口。

## 接入智能体

```sh
wanda skill-path --json
```

将输出的 `SKILL.md` 所在目录复制到智能体支持的技能目录，或让它直接读取该文件。仓库中的原始位置为 `skills/wangda/SKILL.md`。**不支持技能格式的智能体也可直接调用 CLI**；没有本地执行工具的纯聊天模型不能自行运行。

详细说明：[智能体接入](docs/agent-integration.md)、[JSON 契约和退出码](docs/json-contract.md)。不需要 MCP 服务，也不需要为不同智能体复制一份业务代码。

## 配置与数据隔离

优先级：CLI > `WANDA_*` 环境变量 > TOML > 默认值。示例见 [config.example.toml](config.example.toml)。全局参数可以放在子命令前后。

`resume` 以此前保存的执行配置为基线，当前显式 CLI、环境变量和 TOML 设置仍优先于该基线。

```sh
wanda --config ./config.toml doctor
wanda run '<链接>' --data-dir ./.runtime --background
wanda status --data-dir ./.runtime
```

同一任务的每次调用必须使用相同数据目录。默认通过 platformdirs 选择系统用户数据目录：macOS 的 Application Support、Linux 的 XDG data、Windows 的本地应用数据目录。浏览器 profile、状态和日志均在该目录下，不使用任何智能体的私有目录。默认由 Chrome 选择空闲的本地 CDP 端口。

可用环境变量：`WANDA_CONFIG`、`WANDA_DATA_DIR`、`WANDA_PROFILE`、`WANDA_BROWSER`、`WANDA_PORT`、`WANDA_RATE`、`WANDA_HEADED`、`WANDA_RETRIES`、`WANDA_STALE_SECONDS`、`WANDA_CONFIRMATION_SECONDS`、`WANDA_POLL_SECONDS`。

**不要将 profile 指向日常浏览器目录。** 登录态与本地日志属于私人数据，不要提交、共享或上传到 GitHub。详见 [安全说明](SECURITY.md)。

## 验证与已知边界

- 运行核心按跨平台方式实现；CI 覆盖 macOS / Linux / Windows，Python 3.11 / 3.14。
- 本地做离线真实无头 Chrome 验证，自动测试使用合成页面与进程，不包含账号或内部课件。
- **已完成 macOS 27.0 / Chrome 155 的真实账号视频课端到端验收**，包括平台入账、队列、暂停恢复、只读状态、主动停止与未登录边界。详见 [验收报告](docs/acceptance-2026-10-21.md)。不代表其他系统和所有课程类型均已实测。
- 网大页面、账号权限或规则变化可能影响运行。首次使用先验证一门短课程，最终以平台页面确认为准。
- 课程页与专题汇总状态可能不同步。0.1.1 起，单门课也必须核对其对应专题卡片；超出确认窗口返回 `unconfirmed`，不会仅凭播放页完成或总数增加报成功。
- 支持视频项（type 10）及 URL 项的正常页面点击（type 3）；未知必修类型停下等待人工处理。
- 仅接受 1.0 / 1.2 / 1.5 倍速；实际可用性仍以平台规则为准。
- 不做考试、不做同账号并发、不伪造记录、不提供托管登录服务；后台运行不等于开机自启，机器重启后显式 `resume`。

测试方法与人工验收清单见 [verification.md](docs/verification.md)。架构与继续开发入口见 [architecture.md](docs/architecture.md)、[CODE_INVENTORY.md](CODE_INVENTORY.md) 和 [工作记录](worklogs/)。无需运行服务端。

## 开发

```sh
git clone https://github.com/cnatom/wangda-cli.git
cd wangda-cli
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
uv build
```

改造复用了原技能的播放和回归逻辑，移除了个人路径、Hermes 依赖、Bash/launchd 守卫及并发拦截实验，没有新增通用平台框架或重复播放器实现。

## License

[MIT](LICENSE). Copyright 2026 cnatom.
