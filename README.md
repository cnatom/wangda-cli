# Wanda

中国移动网大学习助手，支持课程播放、证书领取、进度查询与暂停续学。

## 功能

- 顺序学习课程与专题必修项，跳过已完成和选修内容。
- 后台播放，支持进度查询、暂停与恢复。
- 后台运行不弹出终端窗口。
- 默认完全静音播放，不输出声音。
- 领取已完成专题的结业证书，可按需下载证书 PNG。
- 完成后核对平台状态，自动关闭专用浏览器并保留登录态。

## 安装

通过 skills.sh 安装：

```sh
npx skills add cnatom/wangda-cli --skill wangda
```

安装命令需要 Node.js / npx。运行需要 Python 3.11+、Git、uv 和 Chrome / Chromium；首次使用时，智能体会检查环境并安装 CLI。登录由本人在浏览器中完成。

## 使用

安装后，直接告诉智能体：

> 帮我学习这个专题：〈网大专题链接〉

> 帮我领取这个专题的证书：〈网大专题链接〉

> 查看当前学习进度。

> 暂停学习，之后继续。

## 文档

- [使用与配置](docs/usage.md)
- [智能体接入](docs/agent-integration.md)
- [JSON 契约](docs/json-contract.md)
- [开发架构](docs/architecture.md)
- [验证说明](docs/verification.md) · [验收报告](docs/acceptance-2026-10-21.md)

## 使用须知

非中国移动官方项目。请使用本人获授权的账号并遵守平台与单位规定；自动播放不替代本人学习。不伪造学习记录，不处理考试。登录态和日志仅保存在本地，请勿共享。详见 [安全说明](SECURITY.md)。

## License

[MIT](LICENSE). Copyright 2026 cnatom.
