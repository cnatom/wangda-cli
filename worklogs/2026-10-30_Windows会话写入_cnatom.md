# Windows 下会话文件写入失败

## 状态

已修复（待合并）。Windows 原生主机上 `wanda auth` 在平台认证成功之后报 `{"status": "failed", "reason": "PermissionError"}`：token 已经拿到、验证码被消耗、数据目录里只留下一个 0 字节的 `.session.json*.tmp`。

## 原因

`write_private_json` 在写临时文件后调用 `os.fchmod(fd, 0o600)`。`os.fchmod` 是 POSIX-only，Windows 上直接抛 `PermissionError`，于是写盘在 `os.replace` 之前就中断。

同一模块的 `read_session` 还有一个对称问题：它用 `stat.S_IMODE(...) & 0o077` 判断"文件是否仅本人可读"。Windows 的 `st_mode` 恒定带 group/other 位，所以即使写成功，读回也必然抛 `AuthError: session file is readable by others`。

## 改动

- 新增 `_enforce_posix_private_mode()`：`os.name != 'nt'`。写路径据此跳过 `os.fchmod`，读路径据此跳过 `0o077` 检查；Windows 上的访问控制由 ACL 承担。
- 测试（先红后绿）：
  - `test_write_private_json_survives_hosts_without_posix_modes`：把 `os.fchmod` 换成抛 `PermissionError` 的桩，要求写入仍然落盘、能读回、且不残留 `.tmp`。
  - `test_read_session_skips_posix_mode_check_without_posix_modes`：`0o644` 的文件在非 POSIX 模式下可读。

两处测试通过 monkeypatch `wangda.auth._enforce_posix_private_mode` 模拟 Windows，在 macOS/Linux 的 CI 上也能复现缺陷。

`uv run pytest -q`：151 passed, 2 skipped；`uv run ruff check src tests`：通过。

## 现场绕过

合入前，Windows 主机上是直接改 `%APPDATA%\uv\tools\wangda-cli\Lib\site-packages\wangda\auth.py` 打同样的守卫，并用该 venv 的 `Scripts\python.exe` 做了写入/读回往返验证。`uv tool install --force` 会覆盖这个补丁，所以合并后必须重装：

```powershell
uv tool install --force "git+https://github.com/cnatom/wangda-cli.git"
```

## 如何继续

- 合并本分支后重装工具，再跑一次 `wanda doctor --json` 确认 `session.present`。
- 技能 `wangda` 的「Boundaries and pitfalls」已记录该症状与现场绕过方式；修复发布后把该条改成"仅影响 < 本次修复的版本"。
- 本项目没有 Windows CI runner；该缺陷靠单元测试里的平台模拟覆盖，不要声称已在 Windows CI 上验证。
