# Vendored OpenAI screenshot subset

This directory contains a deliberately small, modified subset of OpenAI's Codex screenshot skill.

Source: `openai/skills`, `skills/.curated/screenshot/`
Source commit: `49f948faa9258a0c61caceaf225e179651397431`
License: Apache License 2.0 (see `LICENSE.txt`)

AgentSwitchboard only carries the macOS primitives it needs:

- Screen Recording permission preflight/request via CoreGraphics.
- Frontmost layer-0 window discovery via `NSWorkspace` + `CGWindowListCopyWindowInfo`.

The original general-purpose screenshot CLI, Linux/Windows support, output-location logic, interactive capture paths, and Codex-specific environment behavior are intentionally not vendored. AgentSwitchboard keeps its own privacy admission, one-use focused-window authorization, drift checks, image validation, receipts, deduplication, and persistence policy around these OS primitives.

The vendored Swift files are modified derivatives and are marked accordingly in their headers.
