# 独立网大 CLI 与通用 Skill

## 状态

已实现，本地验证完成。GitHub public 发布与远端 CI 待核验。

## 范围与文件

- `src/wangda/`：标准 Python 包、CLI、配置、浏览器、队列守护与平台播放适配器。
- `skills/wangda/SKILL.md`：通用技能，wheel 中一并打包，可由 `wanda skill-path` 定位。
- `tests/`：合成 DOM 回归、配置、锁、真实子进程生命周期、异常恢复、脱敏及可选离线 Chrome 测试。
- `docs/`：架构、JSON 契约、智能体接入、验证范围。
- 没有服务端。未改动原个人技能和正在运行的任务。

## 本地验证

- `uv run pytest -q`：57 passed, 1 skipped（浏览器测试默认不自动启动）。
- 单独启用离线真实 Chrome 测试：1 passed；使用全新临时 profile，无账号、无平台访问，结束后无该 profile 的浏览器残留。
- Ruff：通过。
- sdist / wheel 构建及 Twine metadata 检查：通过。将元数据版本固定 2.4，避免当前构建器默认 2.5 与 Twine 6 的兼容问题。
- 独立 wheel-only 环境安装：版本、status 和随包 Skill 定位通过。
- detect-secrets：唯一初始命中是拒绝凭据 URL 的合成测试样例，已明确标记测试白名单；不含真实凭据。
- 新增有界停滞恢复、CDP 重连引用保持、PID 创建时间校验，避免无限重载及误杀复用 PID。

## 未验证项

独立包尚未完成登录网大的真实课程端到端验收；不借用或上传已有登录态。跨系统 CI 不等于各系统真实平台播放验收。

## 减法

移除 Hermes 私有路径与运行依赖、Bash/launchd 守卫、个人工作目录、并发及拦截限制实验。Skill 不包含第二套播放器，没有提前搭通用学习平台框架或 MCP 服务。

## 如何继续

1. 核验 GitHub public 仓库、远端分支提交及三系统六组合 CI。
2. 初次真实使用时按 `docs/verification.md` 选一门获准的短课完成平台验收。
3. 用户决定切换前保留原本地技能，不自动替换其驱动、profile 或守卫。
