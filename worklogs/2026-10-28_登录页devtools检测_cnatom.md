# 登录页 devtools 检测

## 状态

文档补充已完成：网大 OAuth 登录页内嵌 devtools 检测，带调试端口的标签页一请求短信验证码就跳 `about:blank`，所以 `wanda login` 打开的窗口无法完成短信登录。改为在同一专用 profile 上开一个不带 `--remote-debugging-port` 的普通 Chrome 登录，关窗后由 CLI 附加接管；视频播放页不受影响。

改动文件：`docs/usage.md` 新增「登录」一节（含 `stop` → 普通窗口登录 → `inspect` 验证的完整命令）、`skills/wangda/SKILL.md` 增加一条 pitfall、`docs/agent-integration.md` 认证段补充一句并链到该节。

## 证据

- 登录页 JS（`oauth/scripts/main-bbff28cb9d.js`）里存在 `You don't have permission to use DEVTOOL!【type =` 与 `clearIntervalWhenDevOpenTrigger 在使用 ondevtoolclose 时无效`，即页面自带 devtools 检测。
- 带 CDP 的窗口：导航到登录页正常渲染，点「获取验证码」后顶层 frame 自行跳 `about:blank`，控制台输出 `You don't have permission to use DEVTOOL!【type = 6】`。
- 同一 profile 用普通 Chrome（无调试端口）打开，本人登录成功；随后 `wanda inspect` 返回 `inspected`，说明登录态已落盘、CLI 可正常附加。
- 播放页（`subject/course` 路由）在 CDP 下正常推进（`cur` 随时间增长、`paused=false`），未触发该检测。

## 如何继续

- 代码层可选修复（未做，需单独任务与测试）：让 `wanda login` 以无调试端口方式启动 Chrome 并记录 pid，供 `stop` 关闭；现在它仍走 `Browser.open(headed=True)`，文档只是给出人工绕行方式。
- 另有一个独立缺陷待修：课程全部节完成后，平台会跳 `#/study/errors/<courseId>&1`（页面文案「您已打开新的课程详情页，点击按钮，可继续学习。」）。`ensure_course_page` 会点「继续学习」恢复，但 `run_course` 的 tick 循环一旦看到该路由就直接 `error_page_stop` 返回，导致整门课 `unconfirmed`。复现见 run `a6ce7e68…`、`faf50a66…` 的 `events-*.jsonl`。
