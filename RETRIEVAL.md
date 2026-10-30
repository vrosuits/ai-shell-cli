# Retrieval and tool-using agents

AI Shell can search the web, extract webpages, find/download images, read cloud
files, and run multi-turn research, coding and review agents. These are opt-in
commands and capabilities; retrieved content does not become an instruction to
change the program or its configuration.

## Direct retrieval commands

```text
:search recent research on battery recycling
:page https://example.com
:images red panda
:image https://example.com/photo.png
:cloud ls documents
:cloud ls documents "reports/2026"
:cloud read documents "reports/2026/summary.txt"
:cloud pull assets "illustrations/diagram.png"
```

- `:search` uses the existing OpenAI client/model with hosted web search and
  returns the answer plus structured citation titles and URLs. It uses API
  credits and requires search support for the configured model/account.
- `:page` retrieves public HTTPS HTML, text, JSON or Markdown, returning text,
  links and image URLs. HTML scripts/styles are omitted, never executed. This
  is not a browser: JavaScript-rendered pages, login flows, PDFs and arbitrary
  document conversion are not supported.
- `:images` searches **Wikimedia Commons**, returning up to five results with
  source URLs and available license/attribution metadata. It is not an index of
  all web images. Check the linked source's reuse requirements.
- `:image` downloads an inert PNG, JPEG, GIF or WebP artifact. MIME type and file
  signature must agree. SVG and executable formats are rejected. Images are not
  automatically opened, rendered or passed to a vision model; signature checks
  are not a complete image decoder/security scanner.
- `:cloud ls` lists one directory; `read` shows one UTF-8 file locally; `pull`
  saves one file as an inert `.bin` artifact. Neither command sends file content
  to OpenAI. The agent cloud tools do send approved results to the model.

Direct commands are explicit user requests. Downloads get unique random names,
owner-only POSIX permissions and checksums under
`~/.local/state/ai-shell-cli/artifacts/`. Use `--artifact-dir PATH` to choose a
location. Downloads never overwrite source or execute themselves. Raw mode emits
JSON for retrieval and agent results; ordinary script generation still emits
source. Other modes print readable results and progress to stderr.

## Public network boundary

Public URL fetching uses HTTPS on port 443, certificate validation, no URL
credentials, no cookies, no proxy environment, and a fixed user agent. DNS results
are checked for private, loopback, link-local, multicast and reserved addresses.
The socket connects to the validated numeric IP while TLS verifies the original
hostname, avoiding a second hostname resolution at connection time. Redirects
are limited to three and each destination is revalidated.

Pages are limited to 1 MiB and extracted text to 24,000 characters. Image
artifacts are limited to 5 MiB. Responses must honor identity encoding; compressed
responses are rejected. The socket timeout is ten seconds, with an elapsed-time
check between reads. OS DNS resolution can exceed that timeout; this is not a
hard process-wide deadline. The first validated IP is tried; there is no retry or
browser fallback. HTTPS endpoints can still have server-side effects for GETs,
and query strings can reveal supplied data to the destination.

Hosted OpenAI web search runs at the provider, so local socket protections do not
control its crawlers. It receives the search query and returns citations. Search
and agent availability/pricing follow the configured API account; the program
never silently switches models or providers.

## Read-only cloud setup

Install [rclone](https://rclone.org/install/) and configure the desired account
with its normal OAuth/credential workflow. Use provider-side **read-only scopes**
and a dedicated account/folder where practical. AI Shell does not create cloud
credentials or grant remote access automatically.

Create an operator-owned configuration:

```json
{
  "version": 1,
  "rclone_config": "~/.config/rclone/rclone.conf",
  "remotes": {
    "documents": "gdrive:AI-Shell-ReadOnly",
    "assets": "onedrive:AI-Shell-Assets"
  }
}
```

```bash
python ai_shell_cli.py --mode color --cloud-config examples/cloud.json
```

Adapt the example names to your real configured remotes. Google Drive, OneDrive,
Dropbox, S3 and other backends are available through rclone; the CLI itself does
not contain provider-specific OAuth clients. No private cloud account is assumed
to exist just because the app is installed.

The adapter invokes only `lsjson` and `cat`, with an explicit configuration file,
no shell interpolation and bounded responses. Aliases and root prefixes come
from the operator configuration, never model output. Absolute object paths,
traversal, inline backends and wildcards are rejected. `read`/`pull` first checks
that the target is one file of known size at most 1 MiB, then enforces the byte
limit while reading. Directory listing output is capped at 1 MiB and 100 displayed
entries. Cloud subprocesses have a 30-second kill timer and do not inherit
OpenAI or webhook credentials. Backend errors are not echoed with secrets.

The configured rclone executable, configuration and remote backend are trusted.
Some rclone backends can alias other remotes or local paths, and credentials can
have wider access than a prefix. Prefix validation is not a substitute for
provider-side authorization. Do not load an untrusted rclone configuration or
credential-helper command. OAuth refreshes may update rclone's own credential
cache; the adapter exposes no cloud write/delete/sync command. Complex cloud-native
document exports and unknown-size objects may require an explicit export outside
this interface.

## Run an agent

```bash
# Research with automatic public retrieval at autonomy 5:
python ai_shell_cli.py --mode color --autonomy 5 \
  --agent 'Compare three battery-recycling approaches and cite sources'

# Isolated Python computation with a coding role:
python ai_shell_cli.py --mode color --autonomy 6 --agent-role coder \
  --agent-tools python \
  --agent 'Compute and verify the first 20 Fibonacci numbers using Python'

# Review and propose a patch; every patch proposal still requires approval:
python ai_shell_cli.py --mode color --agent-role reviewer \
  --agent-tools python,patches \
  --agent 'Review this supplied replacement code and propose a patch for module.py: ...'

# Private cloud research (interactive approvals required):
python ai_shell_cli.py --mode color --cloud-config examples/cloud.json \
  --agent-tools cloud --agent 'Summarize reports in the documents alias'
```

Inside the CLI, use `:agent TASK` with the same startup settings. Each task starts
a fresh conversation. Roles (`researcher`, `coder`, `reviewer`) change instructions,
not permissions. This is a local, caller-owned Responses API function-calling
loop, not a hosted background service, persistent multi-agent swarm, or an
unbounded autonomous process.

Capabilities selected with `--agent-tools`:

| Capability | Tools | Approval |
| --- | --- | --- |
| `web` | `web_search`, `fetch_page` | Automatic at autonomy 5+, otherwise manual. |
| `images` | `search_images`, `download_image` | Automatic at autonomy 5+, otherwise manual. |
| `cloud` | `cloud_list`, `cloud_read` | Always manual; names/content will be sent to the model. |
| `python` | `python` | Automatic only at autonomy 6; always inside required Bubblewrap isolation. |
| `patches` | `propose_patch` | Always manual; creates a patch only, never applies it. |

The default capability set is `web,images`. Unknown/disabled tools and malformed
arguments are rejected by host code even if the model requests them. When `cloud`
is enabled, every public search/fetch/image request also requires approval at
all autonomy levels, preventing silent forwarding of private results to public
services. Declined identical calls are not reapproved within the same task. No
terminal means no manual approval; those tools return a denial to the agent.
Enabling cloud tools does not authorize sending all files: approve each access.

The Python tool has the same no-workspace/no-network Bubblewrap isolation as
plugin tools, with a 30-second process timeout and resource limits. It receives
only the code supplied by the agent, exposes no general shell tool, and returns
at most 16,000 characters. It can compute over supplied data but cannot open host
files or downloaded artifacts. Patches use the existing review-only artifact
interface. Agent tools cannot edit policy, add capabilities, apply patches,
commit, merge or deploy. Ordinary manually requested script execution remains a
separate interface with its existing policy.

## Budgets, errors and evidence

Defaults: eight model turns, twenty function calls, 24,000 reported tokens and a
180-second scheduling budget. Configure with `--agent-turns`, `--agent-calls`,
`--agent-tokens`, `--agent-seconds`. Per-call API timeout is at most 45 seconds,
with API retries disabled. Search tools may make a separate bounded API request;
their reported tokens are included in the total.

Token/time limits stop scheduling further work after measured use; they are not
strict billing or wall-clock caps. The request already in flight can exceed the
remaining token budget through input usage, and tools have their own timeouts.
Hosted search charges are separate from token counts. Use provider account limits
for a strict spending ceiling. Ctrl-C interrupts foreground work; tasks are not
resumed automatically. An incomplete response or exhausted budget returns a
non-success status, not a fabricated completed report. Tool failures are returned
to the model as generic errors without leaking exception text.

The runner labels retrieved/tool content untrusted and instructs the model to
ignore embedded instructions. Host-side permissions enforce the boundary even if
those instructions are ignored. Model-written answers can still be mistaken or
contain invented citations: inspect returned source URLs and tool results when
accuracy matters. No image-understanding or automatic local-file upload is added.

With `--hooks`, new `before/after_retrieve` and `before/after_agent` events extend
the existing metadata-only audit trail. It logs activity/outcomes, not prompts,
queries, URLs, code or private results. Code changes still use normal human review,
tests, version control and deployment. See [HOOKS.md](HOOKS.md).

## Validation

Offline tests cover DNS pinning/private address rejection, redirect revalidation,
body limits, HTML extraction, image signatures, cloud root and file-size checks,
real rclone reads against synthetic local fixtures, function-call continuation,
capability/approval enforcement, bounded execution and real sandboxed Python.
Public smoke checks exercised a webpage and Wikimedia search. Private provider
OAuth and paid OpenAI agent/search calls are not covered by those checks.
