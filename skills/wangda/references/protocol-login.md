# Protocol login (browser-free) — how it works and how to repair it

Depth notes for `wanda auth`. Read this when login breaks, when the platform
changes its front end, or when deciding whether a third-party tool's login can
be reused (it usually cannot).

## Where the protocol lives

`/oauth/` is a separate app from the main SPA. Its bundle is
`https://wangda.chinamobile.com/oauth/scripts/main-<hash>.js`; the hash changes
on every deploy, so re-read `<script src>` from `https://wangda.chinamobile.com/oauth/`
rather than caching a filename.

Distinguish with:

```sh
curl -s https://wangda.chinamobile.com/oauth/ | grep -oE 'scripts/main-[0-9a-f]+\.js'
curl -s https://wangda.chinamobile.com/oauth/scripts/main-<hash>.js -o oauth_main.js
grep -c 'security:"hybrid"' oauth_main.js    # models that need the envelope
```

## Payload envelope

The app wraps only models declared `security:"hybrid"`
(`./app/util/hybrid-crypto`):

```text
key        16 random alphanumerics, per request
secureKey  RSA-PKCS1v15(key)                      -> base64
secureData AES-128-ECB(PKCS7, json(payload), key) -> base64

POST body  secureKey=...&secureData=...   (x-www-form-urlencoded)
```

A 16-character key means AES-128, not AES-256. The RSA public key is public and
needs no account: `GET /oauth/api/v1/setting` returns `rsaPublicKey` (PEM, 2048)
together with `showCaptcha`, `webConfig`, `mainSite`.

## Chain and field map

```text
GET  /api/v1/system/sign/generate?prefix=oauth-login          -> {"sign": ...}
POST /oauth/api/v1/dynamic-password-sign  hybrid  {key, username, sign}
     -> sends the SMS; response may carry phoneNumber for masking
POST /oauth/api/v1/members-encrypt        hybrid  {key, username, password, loginType:'1'}
     -> {members:[{id}], check_token, pass, isWeakPwd}
POST /oauth/api/v1/auth                   PLAIN   {key, userid, check_token, password}
     -> {access_token, token_type, expires_in, redirect_uri}
```

- `key` is the route segment from `#login/no-date`, i.e. the literal `no-date`.
- `auth` is **not** hybrid; posting an envelope there fails.
- `pass` 1 or 3 means the account must pick a department in the web app first;
  report that, do not guess an id.
- Platform error codes seen: 90105 unknown account, 90134 wrong code,
  90984 too many failures (cool down), 422/900000 invalid input.

## Token -> browser

The SPA stores auth in `localStorage` on the `wangda.chinamobile.com` origin and
also accepts a hash redirect:

```js
localStorage.setItem('token', JSON.stringify({access_token, token_type, is_weak_pwd}));
location.href = redirect_uri + '/#access_token=' + access_token + '&token_type=' + ...;
```

`inspect`/`run` set the localStorage entry with CDP before navigating; that is
the whole bridge, so no cookie export, no visible window, and no profile lock.
`expires_in` is about 14400 seconds — check `wanda doctor` `session.fresh`
before a long queue instead of discovering expiry mid-run.

## Renewal: implicit grant, no refresh token

The login is `response_type=token` (implicit): neither `/oauth/api/v1/setting` nor
the `auth` response carries a usable `refresh_token`, and both bundles contain
zero `refresh_token`/`refreshToken` references. The only renewal is a fresh SMS
login. This account has **no password login**, so the `password` field on
`members-encrypt` buys nothing: telling the user to store a static password and
re-login silently is not an option here, and no credential should be kept on the
machine for it.

`expires_in` is a declared window, not a revocation. Measured: a token in
continuous use kept a queue playing for 15.5 hours on one login, while a token
left idle for about 6 hours was refused with
`401 {"message":"Access is Denied"}`. Treat both observations as one rule — idle
time kills the token, activity keeps it alive — and always let the platform
decide instead of a local clock:

```sh
# read-only; reports nothing, writes no learning data
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: <token_type>__<access_token>" \
  https://wangda.chinamobile.com/api/v1/human/member/center
```

The runner already does this when the declared window passes and continues on
`200`, recording `session_note: declared_expired_but_accepted`; only 401/403
parks it. Never answer "you must log in every four hours" from `expires_in`
alone — that prediction is wrong for an active run and the user will (rightly)
remember a night that never asked for a code. The wait budget is still finite:
when `session_wait_seconds` runs out the runner exits as `waiting_login`, the
queue is preserved, and a `resume` is then required (while the runner is alive,
no `resume` is needed).

## Why not reuse a third-party tool's login

A reversed client is a snapshot of the deployment it shipped against. This
platform moved from a fixed AES key on individual fields to the per-request
RSA-wrapped envelope above, so an older tool's constants and field names no
longer match the live site. Diff endpoint names, crypto shape and field names
against the current bundle before porting any of it; `aeskey`-style literals
have disappeared from the bundle entirely.

## Egress check before promising a remote host

```sh
curl -s -o /dev/null -w 'root=%{http_code}\n'  https://wangda.chinamobile.com/
curl -s -o /dev/null -w 'setting=%{http_code}\n' https://wangda.chinamobile.com/oauth/api/v1/setting
```

`root=405` with a 「安全卫士应用防护平台」 page, or `setting=000`, means the host's
egress is refused by the edge WAF. Installing Chrome does not help; the host is
unusable for this platform. Overseas datacenter ranges are refused, mainland
home broadband and domestic VPS are not.

A proxy in the environment produces the same 405 even from a mainland host:
`HTTP_PROXY`/`HTTPS_PROXY` route the API call to the proxy's exit. Set
`NO_PROXY=wangda.chinamobile.com,chinamobile.com` for the invocation (and the
same in lowercase) and re-run `wanda auth --probe --json`; a populated
`probe.public_key_sha256` is the proof, and the probe sends no SMS. The browser
does not honour `NO_PROXY`, so media stalls on a proxied host are a separate,
browser-side problem.


## Session file on Windows: two POSIX assumptions break it

`session.json` is written by `write_private_json` in `auth.py`: mkstemp in the
data dir, `os.fchmod(fd, 0o600)`, then `os.replace`. `read_session` refuses any
file whose `stat.S_IMODE(...) & 0o077` is non-zero.

Both assumptions fail on Windows. `os.fchmod` is Unix-only, so the write raises
`PermissionError` **after** the platform has already accepted the SMS: the
visible result is
`{"schema_version": 1, "status": "failed", "reason": "PermissionError"}` with a
zero-byte `.session.json*.tmp` left beside the real path, and the code is spent.
Even with the write fixed, mkstemp's default mode makes `read_session` raise
`AuthError('session file is readable by others')` on the next command.

Guard both with `os.name != 'nt'` — Windows ACLs govern there, POSIX bits do
not — and prove the fix without burning another code:

```powershell
$py = Join-Path $env:APPDATA 'uv\tools\wangda-cli\Scripts\python.exe'
& $py -c "import tempfile,pathlib;from wangda.auth import write_private_json,read_session;d=pathlib.Path(tempfile.mkdtemp());f=d/'session.json';write_private_json(f,{'access_token':'x','token_type':'y','expires_in':1,'obtained_at':0});print('roundtrip',read_session(f)['access_token'])"
```

Upstream fix: PR #15 on `cnatom/wangda-cli` (`fix/windows-session-write`,
commit `098c0c8`) introduces `_enforce_posix_private_mode()` and gates both call
sites on it, with two tests that simulate a non-POSIX host so they fail on
macOS/Linux CI. Until a release carrying it exists, install the fixed code with

```powershell
uv tool install --force 'git+https://github.com/cnatom/wangda-cli.git@fix/windows-session-write'
```

then confirm `wanda doctor --json` reports `session.present: true` against the
session written by the patched build.

`uv tool` on Windows keeps the code at
`%APPDATA%\uv\tools\wangda-cli\Lib\site-packages\wangda` (interpreter
`…\Scripts\python.exe`), while the executable lands in
`%USERPROFILE%\.local\bin`. Patching site-packages only unblocks the machine in
front of you; the fix belongs upstream with a `tests/` case, and a reinstall
(`uv tool install --force`) silently reverts the local edit.

## Repair checklist when login breaks

1. `wanda auth --probe --json` — separates "egress blocked / endpoint moved"
   from "credentials wrong" without sending an SMS.
2. Re-read the oauth bundle; diff the model list, the endpoints and the field
   names against `auth.py`.
3. Confirm the envelope still matches: random per-request key, RSA-wrapped,
   AES-128-ECB, and which models still declare `security:"hybrid"`.
4. Only then run `wanda auth` again. Under this user's standing instruction the
   agent takes the phone number and the SMS code and feeds the code through
   `--code-stdin`; the code is single-use, never written to a file, a log, a
   commit or the reply, and discarded once the command returns. Every attempt
   spends one code, so clear the session-write path (`doctor`, then the
   round-trip probe above on Windows) before asking for another.

