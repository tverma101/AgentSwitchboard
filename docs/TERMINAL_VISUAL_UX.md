# Terminal visual UX

Status: current-source verified for local image presentation; this document
does not claim Claude Code TUI or provider transport ownership.

Harness keeps visual presentation outside Claude Code's upstream TUI. The local
`fcc-attachment` companion validates one PNG, JPEG, or WebP source, prints a
compact attachment card, and renders a thumbnail only when the current output
terminal is explicitly recognized. The preview is terminal-local and does not
change the model request or add image bytes to receipts or logs.

## Generic image sources

Use a local path or the macOS clipboard:

```bash
fcc-attachment --path screenshot.png
fcc-attachment --clipboard
fcc-attachment --path screenshot.png --no-preview
```

The path/clipboard bytes are read in memory only and are not persisted by this
command. Clipboard input uses the system Swift/AppKit pasteboard boundary and
accepts PNG directly or converts a TIFF representation to PNG. The command
prints a metadata-only card with a short content hash, safe label, dimensions,
media type, encoded size, and an `attached` state. `--no-preview` forces the
card-only form.

This command is a local acknowledgement companion, not an image transport
adapter. Claude Code's own input surface and FCC's protocol boundary remain
responsible for sending an image to the selected model; #19 owns that
end-to-end transport contract.

## Capability detection

The preview probe fails closed when stdout is not a TTY, the session is SSH, or
output is inside tmux or screen. Direct iTerm2 and Kitty sessions are
recognized from their standard environment markers. Sixel markers are recorded
as detected, but remain a metadata-card fallback because Harness does not
implement a Sixel encoder.

Supported-terminal thumbnails are capped at 512 KiB, downscaled before
encoding, and cached in at most eight bounded entries. Full image bytes never
enter normal logs, receipts, or learning storage through this presentation
surface.

## Appshot relationship

Capture a focused window for an explicit Claude session with `fcc-appshot`; it
continues to own capture authorization, session binding, queue persistence, and
Appshot receipts. It uses the same terminal preview/card surface after capture.
No browser, computer-use, or second TUI/runtime is introduced here.
