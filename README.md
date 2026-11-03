# Wanda

[![skills.sh](https://img.shields.io/badge/skills.sh-cnatom%2Fwangda--cli-111)](https://www.skills.sh/cnatom/wangda-cli)

中国移动网大学习助手：课程播放、进度查询、暂停续学、证书领取。

## 功能

- 顺序学习课程与专题必修项，跳过已完成和选修内容。
- 后台播放，支持进度查询、暂停与恢复。
- 后台运行不弹出终端窗口。
- 可选 `--continue-on-error`：单个课程失败后继续刷后续课程，失败项不计为完成。
- 默认完全静音播放。
- 领取已完成专题的结业证书，可按需下载证书 PNG。
- 登录默认 `wanda login`：干净窗口完成短信登录，关窗后 CLI 接管；无图形界面时用 `wanda auth`。
- 完成后核对平台状态，自动关闭专用浏览器并保留登录态。

## 安装

```sh
npx skills add cnatom/wangda-cli
```

交给智能体执行：

```text
安装技能：npx skills add cnatom/wangda-cli
```

装到 `.agents/skills/wangda`，Claude Code 走软链，其他 agent 直接读该目录。

## 用法

```text
帮我学习这个专题：〈网大专题链接〉
帮我领取这个专题的证书：〈网大专题链接〉
查看当前学习进度。
暂停学习，之后继续。
```

## 要求

安装命令要 Node.js；运行要 Python 3.11+、Git、uv 和 Chrome / Chromium。首次使用时智能体会检查环境并安装 CLI。

## 文档

- [使用与配置](docs/usage.md)
- [智能体接入](docs/agent-integration.md)
- [JSON 契约](docs/json-contract.md)
- [开发架构](docs/architecture.md)
- [验证说明](docs/verification.md) · [验收报告](docs/acceptance-2026-10-21.md)

## 须知

非中国移动官方项目。使用本人获授权的账号，遵守平台与单位规定；自动播放不替代本人学习，不伪造学习记录，不处理考试。登录态与日志只存本地，请勿共享。详见 [安全说明](SECURITY.md)。

## License

[MIT](LICENSE). Copyright 2026 cnatom.
