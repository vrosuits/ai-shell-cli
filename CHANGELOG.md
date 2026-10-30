# Changelog

## Unreleased

- Add cited web search, bounded public HTTPS pages, Wikimedia image search and
  inert raster-image downloads.
- Add read-only rclone cloud aliases, directory listing, UTF-8 reads and downloads.
- Add bounded Responses API agents with research/code/review roles, explicit tool
  capabilities, private-data approvals, isolated Python and review-only patches.
- Add retrieval/agent hook events, documented budgets, provider setup and tests.

- Add opt-in, versioned notification hooks around lifecycle and important actions.
- Add HTTPS webhook signatures, strict event validation and a receiver verification
  helper with timestamp and replay checks. No incoming server or response actions.
- Add private JSONL event/dispatch/result logs without prompt/source/credential data.
- Require Bubblewrap isolation for executable plugin tools; no host workspace,
  home, network, writable host mounts or unsafe fallback. This changes plugin-tool
  behavior and makes execution unavailable on systems without Linux Bubblewrap.
- Add `:patch` for inert single-file change proposals requiring human review.
- Add webhook/security tests and real sandbox integration checks in CI.

## 2.0.0

- Add classic, true-color highlighted, raw source, and summary display modes.
- Add Unicode panels, ASCII/color fallbacks, progress indicators and optional sound.
- Add seven execution-approval levels, with manual approval as the default.
- Apply configurable dangerous-command rules to scripts, plugin tools, shell
  launches and overwrites. Execute reviewed scripts from temporary snapshots.
- Add explicit JSON plugins containing tools, prompt commands and skills.
- Add one-shot generation/execution and an offline terminal demo.
- Add hidden-input API-key setup with passphrase-encrypted `.env` storage,
  authenticated encryption, atomic writes and owner-only POSIX permissions.
- Require HTTPS for API transport and remove OpenAI environment variables from
  executed programs' inherited environment.
- Forward Node launcher arguments and prefer the local Python virtual environment.
- Add offline regression tests and GitHub Actions checks for Python and Node.

### Upgrading

Python 3.10+ is required. Reinstall `requirements.txt` to add Rich and
cryptography. Existing `OPENAI_API_KEY` environment variables still work;
credential migration is optional. The default display is classic and default
execution approval is manual. There are no automatic key migrations or API calls
in the test suite.

Terminal UI and status messages now use stderr; raw mode emits source on stdout.
Executed source uses a temporary script path while retaining the working
directory, which can affect sibling imports and scripts that inspect their own
location. See README for details. Command-policy matching is heuristic, not a
sandbox; full autonomy should only be used with trusted code.

## 1.0.0 — preserved classic version

Preserves commit `e69d64d45fbea9e498bb26b6f071b9e375d79f06`, the published
`main` branch immediately before the 2.0 upgrade. This release tag is being added
retrospectively to make the old version easy to download and check out.

- Structured script generation through the OpenAI Responses API.
- Language-aware filenames, saving and interpreter selection.
- Manual confirmation before script execution or shell launch.

The original history and existing `master` branch are retained.
