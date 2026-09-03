# ChatGPT provider status and generation

## Symptom

FCC had a usable saved ChatGPT account and six cached OpenAI model references,
but the Admin config and model inventory reported `OpenAI / ChatGPT` as
`disconnected`. A fresh server process therefore made the configured provider
look unavailable even though the provider model-list check succeeded.

## Root cause

`provider_config_status()` is intentionally configuration-only and always
returns connected-account providers as `disconnected`. The runtime-owned
connected-account managers were not being overlaid into the Admin status,
config, or model responses consumed by the native control center.

## Sandbox account boundary

`t-fcc-server` changes `FCC_CONFIG_DIR` to the sandbox state directory. The
OpenAI provider therefore reads `auth/openai.json` from that directory, while
the live server reads `~/.fcc/auth/openai.json`. Sandbox startup copies the
managed `.env` only; it does not copy FCC-owned ChatGPT credentials. Connect
the account from the sandbox Admin UI before selecting an `openai/...` model.

## Recovery

`ApplicationRuntime.admin_status()` now merges the live connected-account
state using only `connected`, `state`, `status`, and a short label. The config
route uses that same runtime status, so `/admin/api/config`,
`/admin/api/status`, and `/admin/api/models` agree. Account email, tokens,
authorization URLs, codes, and error payloads are not copied into the provider
inventory. A connected account remains registered while a refresh/reconnect is
in progress if its existing credentials are still present.

## Validation

- Focused Admin tests passed.
- Safe Python CI passed: `3840 passed, 4 skipped, 173 deselected`.
- Fresh local FCC health was healthy on `4.64.0`.
- Live config, status, and model responses reported OpenAI/ChatGPT as
  `connected` and exposed six explicit `openai/...` model IDs.
- An authenticated loopback request explicitly selecting `openai/gpt-5.4`
  returned the sentinel `FCC_CHATGPT_SMOKE_OK`.

## Residual gap

The working tree remains intentionally dirty and unpublished. A connected
status proves the local account lifecycle and the tested model request, not
that every advertised ChatGPT model will remain available indefinitely.
