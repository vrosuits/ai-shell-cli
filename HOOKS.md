# Notification hooks and reviewed changes

Hooks are opt-in, declarative notifications. They do not receive application
objects, executable callbacks, prompts, source code, paths, credentials, command
arguments or configuration values. There is no incoming HTTP server and no
runtime endpoint for changing code, configuration, plugins or autonomy.

## Enable hooks explicitly

```bash
python ai_shell_cli.py --hooks examples/hooks.json --mode color
```

The example enables local logging and leaves the external webhook disabled.
Hook configuration is read once at startup. Editing a manifest requires a restart.
Use version control, review and tests for configuration changes, as for source.

```json
{
  "version": 1,
  "hooks": [
    {
      "name": "audit",
      "enabled": true,
      "type": "log",
      "events": ["startup", "shutdown", "error", "before_execute", "after_execute"]
    },
    {
      "name": "notifications",
      "enabled": false,
      "type": "webhook",
      "events": ["after_generate", "after_execute", "error"],
      "url": "https://your-service.example/events",
      "secret_env": "AISHELL_WEBHOOK_NOTIFICATIONS"
    }
  ]
}
```

Only `log` and `webhook` handlers are supported. Script/import/callback handlers
and unknown configuration fields are rejected. At most 16 handlers and 64 KiB
of configuration are accepted. Each handler has a unique name, explicit enabled
boolean and an allowlisted event subscription. Enabled webhook handlers require
a dedicated `AISHELL_WEBHOOK_*` environment variable containing a random signing
secret of at least 32 bytes. Supply it through your secret manager; do not commit
it or put it in the manifest. A separate secret per destination is preferable.

Endpoints must be HTTPS, without credentials, query parameters or fragments.
They are selected by the local operator, never by event data. An operator may
choose an internal service, so this is not a public-IP-only destination policy.
Notifications ignore proxy environment settings, verify TLS certificates, do not
follow redirects, and never read response bodies. Responses cannot issue commands
or change state. The HTTP timeout is three seconds per network operation. There
are no automatic retries or durable delivery queues; a failed notification is
logged and does not repeat the underlying action.

## Stable event contract (version 1)

Every event contains exactly these fields:

```json
{
  "version": 1,
  "id": "0123456789abcdef0123456789abcdef",
  "timestamp": 1793400000,
  "event": "after_execute",
  "operation": "execute",
  "outcome": "completed"
}
```

- `id`: fresh 32-character hexadecimal event identifier.
- `timestamp`: integer Unix seconds.
- `event`: `startup`, `shutdown`, `error`, or `before_` / `after_` plus an action.
- Actions: `generate`, `execute`, `save`, `shell`, `patch`, `plugin_load`.
- `operation`: action name, or `session` for lifecycle/session errors.
- `outcome`: `started`, `completed`, `failed`, `cancelled`, or `blocked`.

A successful action emits before/after. A raised action error emits before,
error, and after with `failed`. Execution and shell declines currently report
`cancelled`, including a policy denial; unsuccessful child exit codes report
`failed`. A session-level failure can also emit `error`, so receivers should not
interpret every error event as a distinct failed action. `shutdown` is emitted
on normal exit and handled interruption; SIGKILL, power loss or an unwritable
log cannot guarantee delivery. Credential setup emits no hook events.

The host publishes fresh event records and accepts no modifications back.
Future incompatible schemas must use a new version; do not add arbitrary event
fields to version 1. Notification hooks are observers, not approval or mutation
middleware.

## Webhook authentication and receiver validation

Headers:

```text
Content-Type: application/json
X-AIShell-Timestamp: <timestamp>
X-AIShell-Signature: sha256=<lowercase hex digest>
```

The digest is HMAC-SHA256 over `ASCII(timestamp) + b"." + exact_body_bytes`.
Verify the raw body before decoding or processing it. The helper
`aishell_core.hooks.verify_notification(body, headers, secret, seen)` checks:

1. A 4 KiB body limit, signature format and constant-time MAC comparison.
2. A five-minute timestamp window and equality with the signed event timestamp.
3. The exact v1 schema, known events/operations/outcomes and event identifier.
4. Replay rejection using an application-owned dictionary of event IDs and times.

The helper only returns a validated notification; it does not dispatch local
operations. Run any receiver separately. Receiver applications must serialize
access to replay state, persist it if replay protection must survive restarts,
rate-limit requests, and use notifications only for external monitoring/events.
Do not route authenticated events to `exec`, shell execution, patch application,
configuration writes, or plugin installation. Authentication does not authorize
self-modification.

## Activity logging

With `--hooks`, all lifecycle/action events, handler dispatches, and delivery
results are written as JSON Lines to
`~/.local/state/ai-shell-cli/hooks.jsonl`. Choose an explicit output with
`--hook-log /path/to/hooks.jsonl`. The log is owner-only on POSIX and rejects
symlink/nonregular/multiply-linked targets. It contains event metadata and fixed
statuses, never webhook URLs, signing secrets, source, prompts, exception text,
or response bodies. Without `--hooks` the feature creates no logs or requests.

Configuration/audit failures prevent hook dispatch; a failed before-action audit
prevents the action. Shutdown audit errors are reported to stderr. A log failure
after execution cannot undo an action already completed. This is an operational
log, not tamper-proof storage; configure external retention/rotation as needed.

## Executable plugin tools

Notification hooks never execute untrusted code. The existing explicit `:tool`
interface is separate and now **requires Linux Bubblewrap**. Install the OS
`bubblewrap` package and enable user namespaces. There is no unsandboxed fallback
when Bubblewrap is absent, blocked, or fails.

Tools still pass the dangerous-command approval policy. Their processes run with:

- A fresh namespace set, no host network, no capabilities, no inherited secrets.
- Read-only system runtime directories and the CLI's Python virtual environment.
- Only their source snapshot, private `/tmp`, private `/work`, and private proc/dev.
- No host workspace, home, configuration, Git directory or writable host mounts.
- No interactive stdin; a 30-second timeout; process resource limits (10 seconds
  CPU, 512 MiB address space, 1 MiB file size, 64 descriptors, no core dumps).
- Sanitized stderr presentation of at most 64 KiB of captured output.

There is no host artifact-copy or patch-application channel from plugin execution.
Tools needing project files must be redesigned for explicit inputs in a future
reviewed interface. The current tools cannot inspect the host working directory;
for example `disk` reports the sandbox's mounts. Installed runtime code is trusted.
The sandbox is not a VM, does not protect against kernel vulnerabilities, and
per-process limits are not aggregate cgroup quotas. Windows/macOS plugin execution
is unavailable; declarative skills, commands, log hooks and webhooks still work.

Ordinary user-requested generated scripts and `:run path` keep their documented
execution semantics. Explicitly exporting plugin source and later running it as
a normal script is a separate user action outside the plugin sandbox. Do not
use that path to run untrusted code.

## Propose changes for human review

Generate the proposed replacement source, then:

```text
:patch relative/path/to/existing_file.py
```

This writes a unique `.patch` to
`~/.local/state/ai-shell-cli/proposals/` (override with `--proposal-dir`). The target
file is only read, never changed. Targets must remain inside the current workspace;
symlinks, traversal, absolute targets and files larger than 1 MiB are rejected.
Patches cannot overwrite existing artifacts. No Git operation, approval bypass,
auto-apply, commit, push, merge or deployment occurs.

Review the diff, obtain human approval, then apply/test/commit through your normal
workflow and submit a pull request if appropriate. Runtime webhook input cannot
invoke `:patch` or select its target. The command currently proposes a single-file
replacement, not a repository-wide autonomous refactor.

## Test

```bash
python -m unittest discover -s tests -v
AISHELL_REQUIRE_SANDBOX=1 python -m unittest discover -s tests -v
```

The second command requires real Bubblewrap isolation; tests fail if it is
unavailable. Otherwise the OS-dependent integration tests explicitly skip while
fail-closed unit tests still run. Webhook tests use in-memory HTTP transports and
synthetic secrets; they send no external notifications.
