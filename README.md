<div align="center">

<h1>
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="assets/free-claude-code-wordmark-light.svg">
    <img src="assets/free-claude-code-wordmark-dark.svg" alt="Free Claude Code" width="610">
  </picture>
</h1>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json&style=for-the-badge)](https://github.com/astral-sh/uv)
[![Testing: Pytest](https://img.shields.io/badge/Testing-Pytest-00c0ff.svg?style=for-the-badge)](https://docs.pytest.org/)
[![Type checking: Ty](https://img.shields.io/badge/type%20checking-ty-ffcc00.svg?style=for-the-badge)](https://pypi.org/project/ty/)
[![Code style: Ruff](https://img.shields.io/badge/code%20formatting-ruff-f5a623.svg?style=for-the-badge)](https://github.com/astral-sh/ruff)
[![Logging: Loguru](https://img.shields.io/badge/logging-loguru-4ecdc4.svg?style=for-the-badge)](https://github.com/Delgan/loguru)

[Quick Start](#quick-start) · [Providers](#choose-a-provider) · [Clients](#connect-your-client) · [Integrations](#optional-integrations) · [Manage](#manage-your-installation)

</div>

## What Harness is

Harness keeps the Claude Code client and terminal experience while routing its
requests through a local FCC gateway:

```text
Claude Code / fccdanger -> FCC -> selected provider protocol -> model
```

The current personal release path is terminal-only. `fcc-server` reports local
health and control endpoints but never opens a desktop browser or launches a
terminal-browser presentation. The verified Muse path is
`opencode_go/muse-spark-1.2-contributor` over OpenCode Go's Responses protocol.

This repository is a personal Harness fork. The release head is version
`4.30.2`; examples below describe this checkout, not every feature proposed in
the open design backlog.

## What You Get

- **Use Claude Code in the terminal.** Run `fcc-claude` or the personal
  `fccdanger` launcher through the local FCC gateway.
- **Choose a configured model.** Set an exact `provider/model` reference or a
  stable alias in FCC's managed environment file.
- **Preserve coding-agent behavior.** The release path covers streaming text,
  file tools, repeated tool calls, provider receipts, and one compact/resume
  cycle with the literal Claude client.
- **Save time and tokens.** Five built-in optimizations handle quota probes, command-prefix detection, title generation, suggestion mode, and filepath extraction locally instead of calling your provider; optionally enable [RTK](https://github.com/rtk-ai/rtk) to filter noisy terminal output before it reaches the model.
- **Keep provider boundaries visible.** FCC records metadata-only usage,
  fault-attribution receipts, and pre-network provider-policy decisions; it
  does not silently select a different provider when the configured native
  route is unsupported.

## Release status

| Status | Current scope |
| --- | --- |
| **Shipped and locally verified** | Terminal `fcc-server`/`fccdanger`, FCC routing, OpenCode Go native protocols, text and file-tool loops, the settings-layer proxy-routing firewall, bounded client context and hard text-tool-result governance, global context-discipline policy, reasoning capability/visibility receipts, model catalog visibility, stable aliases, and compact/resume proof. |
| **Implemented but boundary-specific** | Image metadata validation, focused-window Appshot capture, optional learning/memory/skills, Codex/Pi launchers, and messaging integrations. These require their own client/provider permissions and are not part of the minimal Muse release claim. |
| **Planned or design-only** | Full live reasoning-effort matrix, capability-aware helper/fallback routing, browser/CDP control, computer use, portable FCC profiles, and exhaustive Claude-version/subagent compatibility. See [#66](https://github.com/tverma101/Harness/issues/66). |

<div align="center">
  <img src="assets/pic.png" alt="Claude Code running with Free Claude Code" width="700">
  <p><em>Claude Code running with FCC.</em></p>
</div>

## Quick Start

<a id="install"></a>

### 1. Install or update

From this checkout, install the current local code into uv's tool environment:

```bash
uv tool install --editable . --force
```

The repository installers remain available for a full machine setup:
[install.sh](scripts/install.sh) and [install.ps1](scripts/install.ps1). Review
them before running. Re-run the editable uv command after local changes so the
installed `fcc-server`, `fcc-claude`, and `fccdanger` commands use this release
head.

### 2. Start FCC

Run:

```bash
fcc-server
```

Keep this terminal open. In this personal fork, use the terminal command as the
canonical server lifecycle on macOS, Linux, and Windows. Desktop/tray support
may exist in the package, but it is not the documented release path and does
not change the terminal-only browser policy.

To print the installed Free Claude Code version without starting the server,
run `fcc-server --version`.

Startup never launches a desktop browser or a terminal-browser child. The server
reports its local control endpoint for explicit local clients:

```text
INFO:     FCC control endpoint: http://127.0.0.1:8082/admin (terminal-only; browser launch disabled)
```

Use the port shown in your terminal if it differs from `8082`.

`fcc-server --terminal` and `fcc-server --no-browser` are accepted as explicit
terminal-only compatibility flags. Browser-opening flags and presentation
environment variables are intentionally unsupported. If another FCC server
is already healthy on the configured port, a second `fcc-server` invocation
reports that instance and exits instead of attempting a second bind.

<a id="nvidia-nim-provider"></a>

### 3. Configure the provider and model

The terminal-first configuration source is `~/.fcc/.env`. Copy the relevant
entries from [.env.example](.env.example), set the provider credential, and
choose an exact model reference. For the verified Muse path:

```dotenv
OPENCODE_API_KEY=your-opencode-key
MODEL=opencode_go/muse-spark-1.2-contributor
ANTHROPIC_AUTH_TOKEN=freecc
```

Restart `fcc-server` after changing configuration. The local `/admin` endpoint
is an explicit local control/API surface; startup only reports it and never
opens it in a browser.

Model discovery is controlled by `MODEL_CATALOG_MODE` and
`MODEL_CATALOG_ALLOWLIST` in `~/.fcc/.env`. Use `all` to expose discovered
provider models, or `curated` with exact `provider/model` refs separated by
commas or new lines. Curated mode also accepts `provider/*` and `*` wildcards.
Explicitly configured `MODEL` routes remain usable even when hidden from
discovery. Optional stable client-facing aliases use
`MODEL_ALIASES=fast=opencode_go/minimax-m2.7`; the alias is accepted by the
gateway while receipts and provider dispatch retain the exact target ref. See
[Configuration](docs/CONFIGURATION.md) for the complete policy.

### 4. Run Your Coding Agent

Claude Code:

```bash
fcc-claude
```

For this personal fork's terminal-only, skip-permissions workflow:

```bash
fccdanger
```

`fccdanger` is only a convenience alias for `fcc-claude` that adds
`--dangerously-skip-permissions`; it still uses the FCC proxy and never opens a
browser or starts a second server.

Codex:

```bash
fcc-codex
```

Pi:

```bash
fcc-pi
```

The launchers use the current `~/.fcc/.env` settings. Normal CLI arguments still
work, for example:

```bash
fcc-codex exec "hello"
```

`fcc-pi` registers FCC only for that Pi process; your existing Pi settings, sessions, credentials, and extensions remain unchanged.

For a cheap global context-discipline leash, explicitly install FCC's bounded
read/output guidance into Claude's global instruction file:

```bash
fcc-learning context-policy install
fcc-learning context-policy status
```

The operation is idempotent, preserves unrelated `CLAUDE.md` text, and creates
one recovery copy before its first mutation. Remove only the managed block with
`fcc-learning context-policy uninstall`. This is advisory guidance; the
launcher context cap remains the actual client budget.

The compact/resume claim is backed by the sanitized
[Muse receipt](smoke/receipts/muse-auto-compact-2026-08-23.json). It records the
literal Claude Code version, the effective 50K context window, an automatic
compact boundary, a post-compact tool turn, resume success, and the OpenCode Go
Responses route. The local debug trace and prompt content are intentionally not
published.

### Inspect usage and model labels

FCC's local usage ledger records requests, input/output
tokens, cache reads, daily activity, failures, and model breakdowns over the
last 7, 30, or 90 days. FCC records the final Anthropic-compatible usage event
in <code>~/.fcc/usage.db</code>; prompt and response content is never stored.
The graph starts recording after this version is installed, so older requests
are not retroactively reconstructed.

Model labels are cosmetic: the exact provider model id remains the value sent to
the router, and custom model ids remain supported. Use the generated local
catalog at `~/.fcc/codex-model-catalog.json` when a client needs discovery.

## Choose a provider

1. Obtain the provider credential from the provider's normal account page.
2. Put the credential and exact `MODEL` reference in `~/.fcc/.env`.
3. Restart `fcc-server` and verify the route with a terminal client and the
   local receipts/logs. If a provider cannot list models, an exact
   `<provider-id>/<provider-model-id>` value remains supported.

<details>
<summary><strong>Provider catalog</strong></summary>

| Provider | Configuration | Example `MODEL` |
| --- | --- | --- |
| [NVIDIA NIM](https://build.nvidia.com/settings/api-keys) | `NVIDIA_NIM_API_KEY` | `nvidia_nim/nvidia/nemotron-3-super-120b-a12b` |
| [OpenAI / ChatGPT](https://learn.chatgpt.com/docs/auth) | FCC connected-account state | `openai/<model-id>` |
| [Azure OpenAI](https://learn.microsoft.com/azure/foundry/openai/how-to/chatgpt) | `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_BASE_URL` | `azure_openai/<deployment-name>` |
| [OpenRouter](https://openrouter.ai/keys) | `OPENROUTER_API_KEY` | `open_router/openrouter/free` |
| [Google AI Studio (Gemini)](https://aistudio.google.com/apikey) | `GEMINI_API_KEY` | `gemini/models/gemini-3.1-flash-lite` |
| [Google Vertex AI](https://cloud.google.com/vertex-ai/generative-ai/docs/start/openai) | `VERTEX_PROJECT_ID` + ADC | `vertex/google/gemini-3.5-flash` |
| [DeepSeek](https://platform.deepseek.com/api_keys) | `DEEPSEEK_API_KEY` | `deepseek/deepseek-chat` |
| [Mistral La Plateforme](https://console.mistral.ai/) | `MISTRAL_API_KEY` | `mistral/devstral-small-latest` |
| [Mistral Codestral](https://console.mistral.ai/) | `CODESTRAL_API_KEY` | `mistral_codestral/codestral-latest` |
| [OpenCode Zen](https://opencode.ai/auth) | `OPENCODE_API_KEY` | `opencode_zen/gpt-5.3-codex` |
| [OpenCode Go](https://opencode.ai/auth) | `OPENCODE_API_KEY` | `opencode_go/minimax-m2.7` |
| [Vercel AI Gateway](https://vercel.com/docs/ai-gateway/models-and-providers) | `AI_GATEWAY_API_KEY` | `vercel/openai/gpt-5.5` |
| [Amazon Bedrock](https://console.aws.amazon.com/bedrock/) | `AWS_BEARER_TOKEN_BEDROCK` | `bedrock/openai.gpt-oss-120b` |
| [Hugging Face Inference Providers](https://huggingface.co/settings/tokens) | `HUGGINGFACE_API_KEY` | `huggingface/Qwen/Qwen3-Coder-480B-A35B-Instruct:fastest` |
| [Cohere](https://dashboard.cohere.com/api-keys) | `COHERE_API_KEY` | `cohere/command-a-plus-05-2026` |
| [GitHub Models](https://github.com/marketplace?type=models) | `GITHUB_MODELS_TOKEN` | `github_models/openai/gpt-4.1` |
| [Wafer](https://wafer.ai/) | `WAFER_API_KEY` | `wafer/DeepSeek-V4-Pro` |
| [Kimi API](https://platform.moonshot.ai/console/api-keys) | `KIMI_API_KEY` | `kimi/kimi-k2.5` |
| [Kimi Code](https://www.kimi.com/code/console) | `KIMI_CODE_API_KEY` | `kimi_code/k3` |
| [MiniMax](https://platform.minimax.io/user-center/basic-information/interface-key) | `MINIMAX_API_KEY` | `minimax/MiniMax-M3` |
| [Cerebras Inference](https://cloud.cerebras.ai/) | `CEREBRAS_API_KEY` | `cerebras/gpt-oss-120b` |
| [Groq](https://console.groq.com/keys) | `GROQ_API_KEY` | `groq/llama-3.3-70b-versatile` |
| [SambaNova](https://cloud.sambanova.ai/apis) | `SAMBANOVA_API_KEY` | `sambanova/Meta-Llama-3.3-70B-Instruct` |
| [Kilo.ai](https://kilo.ai) | `KILO_API_KEY` | `kilo/kilo-auto/free` |
| [Fireworks AI](https://fireworks.ai/account/api-keys) | `FIREWORKS_API_KEY` | `fireworks/accounts/fireworks/models/llama-v3p3-70b-instruct` |
| [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/) | `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` | `cloudflare/@cf/moonshotai/kimi-k2.6` |
| [Z.ai](https://z.ai/manage-apikey/apikey-list) | `ZAI_API_KEY` | `zai/glm-5.2` |
| [Ollama Cloud](https://ollama.com/settings/keys) | `OLLAMA_API_KEY` | `ollama_cloud/qwen3-coder:480b` |
| [LM Studio](https://lmstudio.ai/) | `LM_STUDIO_BASE_URL` | `lmstudio/<model-id>` |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | `LLAMACPP_BASE_URL` | `llamacpp/<model-id>` |
| [Ollama](https://ollama.com/) | `OLLAMA_BASE_URL` | `ollama/<model-tag>` |

</details>

<details>
<summary><strong>Provider-specific setup</strong></summary>

- OpenAI uses your ChatGPT subscription rather than an API key. Complete the
  local FCC connected-account flow, use device code on headless systems, and
  restart an already-running agent after connecting.
- Azure OpenAI uses the deployment names from your resource. Set
  `AZURE_OPENAI_BASE_URL` to its complete v1 endpoint, such as
  `https://YOUR-RESOURCE-NAME.openai.azure.com/openai/v1/`, and select a
  deployment that supports Chat Completions. Enter the deployment name as a
  custom model slug if it does not appear in the model dropdown.
- Mistral Codestral uses a separate key from Mistral La Plateforme.
- Kimi Code subscription keys use `kimi_code/`; Kimi API credit keys use
  `kimi/`. Kimi Code plans are for personal interactive coding-agent use under
  [Kimi's community guidelines](https://www.kimi.com/code/docs/en/kimi-code/community-guidelines.html).
- OpenCode Zen and OpenCode Go share `OPENCODE_API_KEY` but use the explicit
  `opencode_zen/` and `opencode_go/` model prefixes.
- For Amazon Bedrock, set `BEDROCK_BASE_URL` to the URL for the same region as
  the API key and select one of the listed models.
- Vertex AI uses Google Application Default Credentials instead of an API key.
  Locally, run `gcloud auth application-default login` once; service-account
  files and attached service accounts also work. Set `VERTEX_PROJECT_ID`, and
  optionally change `VERTEX_LOCATION` from its `global` default.
- Cloudflare requires both its API token and account ID.
- For Ollama Cloud, use the exact model IDs returned by discovery or listed by
  the provider. Local Ollama uses the separate `ollama/` prefix.
- Prefer tool-capable models for coding agents. Local models also need enough context for the agent's system prompt and tool definitions.

</details>

<details>
<summary><strong>Local provider setup</strong></summary>

### LM Studio

Start LM Studio's local server, load a tool-capable model, and use the model identifier shown by LM Studio with the `lmstudio/` prefix. The default URL is `http://localhost:1234/v1`.

### llama.cpp

Start `llama-server` with its OpenAI-compatible Chat Completions API and enough context for the model. Use the local model ID with the `llamacpp/` prefix. `LLAMACPP_BASE_URL` defaults to `http://localhost:8080/v1`; FCC accepts either the server root or an explicit `/v1` suffix.

### Ollama

```bash
ollama pull llama3.1
ollama serve
```

Use the tag shown by `ollama list` with the `ollama/` prefix. `OLLAMA_BASE_URL` defaults to `http://localhost:11434`; FCC accepts either the root URL or an explicit `/v1` suffix.

</details>

<details>
<summary><strong>Optional model-tier routing</strong></summary>

`MODEL` is the fallback for every request. Select a model for `MODEL_FABLE`, `MODEL_OPUS`, `MODEL_SONNET`, or `MODEL_HAIKU` to override an individual Claude Code tier; select **None** to use `MODEL`.

For example, route Opus to `nvidia_nim/nvidia/nemotron-3-super-120b-a12b`, Sonnet to `open_router/openrouter/free`, Haiku to `lmstudio/qwen3.5-coder`, and keep `MODEL` on `zai/glm-5.2`.

</details>

<details>
<summary><strong>Reasoning control</strong></summary>

Set `REASONING_POLICY` and its optional tier overrides in `~/.fcc/.env`.

| Selection | Behavior |
| --- | --- |
| **From client** (default) | Use the effort sent by Claude Code, Codex, or Pi. If none is sent, keep the provider default. |
| **Off** | Request reasoning to be disabled. |
| **Low**, **Medium**, **High**, **X-High**, or **Max** | Override the client with the selected reasoning level. |
| **Inherit** (Fable, Opus, Sonnet, and Haiku only) | Use the root Reasoning selection. |

Providers that do not support a selected control retain their own behavior.

</details>

<a id="connect-your-client"></a>

## Connect Your Client

For the supported release path, start `fcc-server`, then run `fcc-claude`,
`fccdanger`, `fcc-codex`, or `fcc-pi` in a terminal. The editor/App examples
below are reference-only integrations; they are not part of the terminal-only
Muse release proof and have not been used to establish the stable product gate.

FCC owns Claude's gateway routing for `fcc-claude`, `fccdanger`, and managed
sessions. Do not set `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, or
`ANTHROPIC_API_KEY` in an active Claude settings `env` block for those launchers:
user `CLAUDE_CONFIG_DIR/settings.json`, project `.claude/settings.json`,
project-local `.claude/settings.local.json`, or an explicit `--settings`
overlay. Claude Code applies those settings over the process environment. The
FCC launchers fail closed with the source and conflicting key names instead of
launching a session that could bypass FCC. If you use `--setting-sources` to
disable a layer, FCC honors that explicit filter. Direct editor integrations
must be treated as separate, experimental clients because they configure their
own environment rather than using the FCC launcher firewall.

### Visual attachments and Appshots

FCC validates PNG, JPEG, and WebP image bytes before forwarding them and exposes
metadata-only attachment receipts (hash, dimensions, size, and media type). The
model catalog exposes known vision support and accepted image types; a known
non-vision model rejects image input before provider I/O, while unknown metadata
remains permissive so stale discovery data does not break requests. The
terminal fallback is a compact `[img ... · attached]` card; Kitty and iTerm2
capability detection is available to the wrapper without emitting escape codes
to unsupported terminals. `fcc-appshot` exposes a demand-only macOS
focused-window capture helper backed by
`free_claude_code.cli.visuals.capture_focused_window`; it requires the user to
grant Screen Recording/Accessibility permissions and never sends a model request
itself.

For an explicit session-scoped capture, use `fcc-appshot --session-id <id>` (or
set `FCC_CLAUDE_SESSION_ID`). The helper writes the PNG and a metadata-only
receipt to the local Appshot queue; a wrapper/session consumer can read that
receipt and attach the image without injecting keystrokes into the Claude TUI.

<details>
<summary><strong>Claude Code in VS Code</strong></summary>

Reference-only: this configures the editor extension directly and is not part of
the supported terminal-only release gate. Use `fcc-claude` or `fccdanger` for
the verified path.

Install the [Claude Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code). Open VS Code's user settings as JSON and add:

```json
"claudeCode.disableLoginPrompt": true,
"claudeCode.environmentVariables": [
  { "name": "ANTHROPIC_BASE_URL", "value": "http://localhost:8082" },
  { "name": "ANTHROPIC_AUTH_TOKEN", "value": "freecc" },
  { "name": "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "value": "1" },
  { "name": "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "value": "190000" },
  { "name": "DISABLE_AUTOUPDATER", "value": "1" },
  { "name": "DISABLE_FEEDBACK_COMMAND", "value": "1" },
  { "name": "DISABLE_ERROR_REPORTING", "value": "1" }
]
```

Match the port and authentication token to `~/.fcc/.env`, then reload the extension.

</details>

<details>
<summary><strong>Codex App</strong></summary>

Start FCC, then edit your Codex configuration:

- Windows: `%USERPROFILE%\.codex\config.toml`
- macOS: `~/.codex/config.toml`

Add the matching model-catalog path and replace `YOUR_USERNAME`.

Windows:

```toml
model_catalog_json = "C:/Users/YOUR_USERNAME/.fcc/codex-model-catalog.json"
```

macOS:

```toml
model_catalog_json = "/Users/YOUR_USERNAME/.fcc/codex-model-catalog.json"
```

Then add the shared FCC settings:

```toml
model_provider = "fcc"
model = "nvidia_nim/nvidia/nemotron-3-super-120b-a12b"

[model_providers.fcc]
name = "Free Claude Code"
base_url = "http://127.0.0.1:8082/v1"
http_headers = { Authorization = "Bearer freecc" }
wire_api = "responses"
```

Match the model, port, and bearer token to `~/.fcc/.env`. Restart the Codex App
after setup or model changes, then select an FCC model from its model picker.

</details>

<details>
<summary><strong>Codex in VS Code</strong></summary>

Install the [Codex extension](https://marketplace.visualstudio.com/items?itemName=openai.chatgpt). Create or edit `~/.codex/config.toml` (`%USERPROFILE%\.codex\config.toml` on Windows):

```toml
model_provider = "fcc"
model = "nvidia_nim/nvidia/nemotron-3-super-120b-a12b"

[model_providers.fcc]
name = "Free Claude Code"
base_url = "http://127.0.0.1:8082/v1"
http_headers = { Authorization = "Bearer freecc" }
wire_api = "responses"
```

Match `model`, the port, and bearer token to `~/.fcc/.env`, then restart VS Code. For WSL-backed Codex, edit the file inside WSL.

</details>

<details>
<summary><strong>Claude Code in JetBrains ACP</strong></summary>

Reference-only: this configures JetBrains' external ACP process directly and is
not part of the supported terminal-only release gate. Use `fcc-claude` or
`fccdanger` for the verified path.

Edit the installed Claude ACP configuration:

- Windows: `C:\Users\%USERNAME%\AppData\Roaming\JetBrains\acp-agents\installed.json`
- Linux/macOS: `~/.jetbrains/acp.json`

Set the environment for `acp.registry.claude-acp`:

```json
"env": {
  "ANTHROPIC_BASE_URL": "http://localhost:8082",
  "ANTHROPIC_AUTH_TOKEN": "freecc",
  "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
  "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "190000",
  "DISABLE_AUTOUPDATER": "1",
  "DISABLE_FEEDBACK_COMMAND": "1",
  "DISABLE_ERROR_REPORTING": "1"
}
```

Match the port and token to `~/.fcc/.env`, then restart the IDE.

</details>

<details>
<summary><strong>Claude Code still asks you to log in</strong></summary>

If Claude Code asks you to log in after you configure the FCC URL and token, open its state file:

- Windows: `%USERPROFILE%\.claude.json`
- macOS/Linux/WSL: `~/.claude.json`

Merge this property into the existing JSON without removing its other fields:

```json
"hasCompletedOnboarding": true
```

If the file does not exist, create it with a complete JSON object:

```json
{
  "hasCompletedOnboarding": true
}
```

Restart Claude Code or the IDE after saving the file.

</details>

<a id="optional-integrations"></a>

## Optional Integrations

Optional integrations remain configured through the local settings surface. They
are outside the minimal terminal-only Muse release proof and should be enabled
only after the core `fccdanger` path is healthy.

<details>
<summary><strong>Discord bot</strong></summary>

1. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Message Content Intent** and invite it with read, send,
   message-history, and **Manage Messages** permissions so `/clear` can remove
   user prompts.
3. Set **Messaging Platform** to **discord**.
4. Enter **Discord Bot Token**, **Allowed Discord Channels**, and an absolute **Allowed Directory**.
5. Apply the settings and restart the server if requested.

</details>

<details>
<summary><strong>Telegram bot</strong></summary>

1. Create a bot with [@BotFather](https://t.me/BotFather).
2. Get your numeric user ID from [@userinfobot](https://t.me/userinfobot).
   In groups, grant the bot permission to delete messages.
3. Set **Messaging Platform** to **telegram**.
4. Enter **Telegram Bot Token**, **Allowed Telegram User ID**, and an absolute **Allowed Directory**.
5. Apply the settings and restart the server if requested.

</details>

### Messaging commands

| Usage | Behavior |
| --- | --- |
| `/stats` | Show session state. |
| Standalone `/stop` | Cancel all work. |
| Reply with `/stop` | Cancel only the selected request while other queued requests continue. |
| Standalone `/clear` | Reset all FCC state and remove every tracked message in that chat, including user prompts, voice notes, FCC replies, Telegram's online notice, and the clear command itself. |
| Reply with `/clear` | Delete the selected message and its literal platform reply subtree while preserving its ancestors and siblings. |

<details>
<summary><strong>Voice notes</strong></summary>

Choose the voice backend you want, then re-run the installer with its option.

| Voice backend | macOS/Linux option | Windows option |
| --- | --- | --- |
| NVIDIA NIM transcription | `--voice-nim` | `-VoiceNim` |
| Local Whisper on CPU or CUDA | `--voice-local` | `-VoiceLocal` |
| Both backends | `--voice-all` | `-VoiceAll` |
| Local Whisper with CUDA 13.0 | `--voice-local --torch-backend cu130` | `-VoiceLocal -TorchBackend cu130` |

The examples below install NVIDIA NIM transcription. To use another backend,
replace the final option with the matching one from the table.

From this checkout, install the optional extra with the local installer:

```bash
./scripts/install.sh --voice-nim
```

On Windows, run `scripts/install.ps1 -VoiceNim` in PowerShell.

Restart `fcc-server`. Set `VOICE_NOTE_ENABLED`, `WHISPER_DEVICE`, and
`WHISPER_MODEL` in `~/.fcc/.env`. Local gated models need
`HUGGINGFACE_API_KEY`; NVIDIA NIM transcription needs `NVIDIA_NIM_API_KEY`.

</details>

## Manage Your Installation

### Update

Re-run the matching command from [Install Or Update](#install).

### Uninstall

Stop every running FCC command before uninstalling.

**Removes**

- Free Claude Code's installed commands and managed state
- `~/.fcc/`

**Keeps**

- uv and Python
- Claude Code, Codex, Pi, and RTK
- Shared PATH entries

From the checkout, use the matching local uninstaller:

```bash
./scripts/uninstall.sh
```

On Windows, run `scripts/uninstall.ps1` in PowerShell.

## Project Links

- [Report bugs or request features](https://github.com/tverma101/Harness/issues)
- [Architecture and extension guide](ARCHITECTURE.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [Claude context policy](docs/CLAUDE_CONTEXT_POLICY.md)
- [Learning, memory, and skills](docs/CLAUDE_LEARNING.md)
- [Terminal-only startup contract](docs/ADMIN_TERMINAL_BROWSER.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Contributing guide](CONTRIBUTING.md)

## License

MIT License. See [LICENSE](LICENSE) for details.
