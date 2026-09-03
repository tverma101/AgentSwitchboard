//! Terminal-palette theme engine ported from terminal-code.
//!
//! Source: `zenbu-labs/terminal-code` at commit `4e54ddf` (MIT, Zenbu Labs),
//! files `src/theme/color.ts`, `src/theme/generate.ts`, and
//! `src/terminal/osc.ts`. Behavioral port only: the Oklch math, surface
//! ladder, semantic hue picking, legibility pushing, OSC reply parsing, and
//! fallback palette are carried over so the native control center wears the
//! same "Terminal Code" theme the donor generates for VS Code. The VS Code
//! color-key map and token colors have no cell equivalent and are not ported;
//! instead the surfaces and legible accents drive the Ratatui [`Colors`].

/// An sRGB triple with one byte per channel.
pub type Rgb = [u8; 3];

/// Oklch triple. Oklch keeps lightness perceptually even, so the same step
/// looks like the same step whatever hue a terminal theme happens to use.
#[derive(Debug, Clone, Copy)]
pub struct Oklch {
    pub l: f64,
    pub c: f64,
    pub h: f64,
}

fn clamp(value: f64, low: f64, high: f64) -> f64 {
    value.max(low).min(high)
}

fn to_linear(channel: u8) -> f64 {
    let c = f64::from(channel) / 255.0;
    if c <= 0.04045 {
        c / 12.92
    } else {
        ((c + 0.055) / 1.055).powf(2.4)
    }
}

fn from_linear(channel: f64) -> u8 {
    let c = if channel <= 0.0031308 {
        channel * 12.92
    } else {
        1.055 * channel.powf(1.0 / 2.4) - 0.055
    };
    (clamp(c, 0.0, 1.0) * 255.0).round() as u8
}

pub fn to_oklch([r, g, b]: Rgb) -> Oklch {
    let lr = to_linear(r);
    let lg = to_linear(g);
    let lb = to_linear(b);
    let l = (0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb).cbrt();
    let m = (0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb).cbrt();
    let s = (0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb).cbrt();
    let lightness = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
    let a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
    let bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
    Oklch {
        l: lightness,
        c: a.hypot(bb),
        h: bb.atan2(a),
    }
}

pub fn from_oklch(color: Oklch) -> Rgb {
    let a = color.h.cos() * color.c;
    let b = color.h.sin() * color.c;
    let lc = (color.l + 0.3963377774 * a + 0.2158037573 * b).powi(3);
    let mc = (color.l - 0.1055613458 * a - 0.0638541728 * b).powi(3);
    let sc = (color.l - 0.0894841775 * a - 1.291485548 * b).powi(3);
    [
        from_linear(4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc),
        from_linear(-1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc),
        from_linear(-0.0041960863 * lc - 0.7034186147 * mc + 1.707614701 * sc),
    ]
}

pub fn luminance([r, g, b]: Rgb) -> f64 {
    0.2126 * to_linear(r) + 0.7152 * to_linear(g) + 0.0722 * to_linear(b)
}

pub fn contrast(a: Rgb, b: Rgb) -> f64 {
    let (high, low) = if luminance(a) >= luminance(b) {
        (luminance(a), luminance(b))
    } else {
        (luminance(b), luminance(a))
    };
    (high + 0.05) / (low + 0.05)
}

// Ported donor API; consumed by the native control-center status and page views.
#[allow(dead_code)]
pub fn is_dark(color: Rgb) -> bool {
    luminance(color) < 0.25
}
pub fn mix(from: Rgb, to: Rgb, amount: f64) -> Rgb {
    let t = clamp(amount, 0.0, 1.0);
    [
        (f64::from(from[0]) + (f64::from(to[0]) - f64::from(from[0])) * t).round() as u8,
        (f64::from(from[1]) + (f64::from(to[1]) - f64::from(from[1])) * t).round() as u8,
        (f64::from(from[2]) + (f64::from(to[2]) - f64::from(from[2])) * t).round() as u8,
    ]
}

/// Step a surface away from its neighbours, so one flat terminal background
/// can become the ladder of panels an editor needs.
///
/// This works in sRGB rather than Oklch on purpose. Oklch lightness is so
/// compressed near black that a perceptually even step off #000000 still
/// lands on #010101, which would flatten every panel into the same colour on
/// the pure black terminal themes people actually use. A background with no
/// room in the direction asked for steps the other way instead.
pub fn shade(base: Rgb, amount: i32) -> Rgb {
    let size = amount.abs();
    let up = amount >= 0;
    let room = if up {
        255 - i32::from(*base.iter().max().unwrap_or(&0))
    } else {
        i32::from(*base.iter().min().unwrap_or(&0))
    };
    let direction = if room >= size {
        if up {
            1
        } else {
            -1
        }
    } else if up {
        -1
    } else {
        1
    };
    base.map(|channel| clamp(f64::from(channel) + f64::from(direction * size), 0.0, 255.0) as u8)
}

/// Push a colour until it is legible on its background. Terminal themes are
/// sometimes very low contrast, and an editor cannot afford that.
pub fn legible(color: Rgb, on: Rgb, target: f64) -> Rgb {
    if contrast(color, on) >= target {
        return color;
    }
    let lighten = luminance(on) < 0.5;
    let base = to_oklch(color);
    let mut best = color;
    for step in 1..=40 {
        let l = clamp(
            base.l + (if lighten { step } else { -step }) as f64 * 0.02,
            0.0,
            1.0,
        );
        best = from_oklch(Oklch {
            l,
            c: base.c,
            h: base.h,
        });
        if contrast(best, on) >= target {
            return best;
        }
    }
    // Oklch can leave the sRGB gamut before it reaches the requested ratio.
    // A neutral fallback is preferable to silently returning an unreadable
    // accent; every background has a black/white endpoint that gives the
    // terminal a deterministic contrast floor.
    let black = [0, 0, 0];
    let white = [255, 255, 255];
    let endpoint = if contrast(black, on) >= contrast(white, on) {
        black
    } else {
        white
    };
    if contrast(endpoint, on) >= target {
        endpoint
    } else {
        best
    }
}

fn focus_surface(background: Rgb, text: Rgb) -> Rgb {
    let mut best = background;
    let mut best_score = 0.0;
    for step in 1..=19 {
        let candidate = mix(background, text, f64::from(step) / 20.0);
        let score = contrast(candidate, background).min(contrast(text, candidate));
        if score > best_score {
            best = candidate;
            best_score = score;
        }
        if contrast(candidate, background) >= 3.0 && contrast(text, candidate) >= 3.0 {
            return candidate;
        }
    }
    for candidate in [[0, 0, 0], [255, 255, 255]] {
        let score = contrast(candidate, background).min(contrast(text, candidate));
        if score > best_score {
            best = candidate;
            best_score = score;
        }
        if score >= 3.0 {
            return candidate;
        }
    }
    best
}

/// Which ansi slot best represents a hue, judged by angle rather than by
/// index, because plenty of terminal themes do not put red in slot one.
fn nearest_hue(palette: &[Rgb], degrees: f64, background: Rgb) -> Rgb {
    let target = degrees * std::f64::consts::PI / 180.0;
    let mut best = palette[0];
    let mut best_score = f64::INFINITY;
    for color in palette {
        let oklch = to_oklch(*color);
        if oklch.c < 0.02 {
            continue;
        }
        let delta = (oklch.h - target)
            .sin()
            .atan2((oklch.h - target).cos())
            .abs();
        let score = delta - contrast(*color, background).min(8.0) * 0.02;
        if score < best_score {
            best_score = score;
            best = *color;
        }
    }
    best
}

#[derive(Debug, Clone, Copy)]
pub struct Semantic {
    pub red: Rgb,
    pub green: Rgb,
    pub yellow: Rgb,
    pub blue: Rgb,
    #[allow(dead_code)]
    pub magenta: Rgb,
    #[allow(dead_code)]
    pub cyan: Rgb,
}

/// The bright half of the palette reads better on an editor surface than the
/// dim half, so accents are chosen from slots eight to fifteen where they
/// exist.
pub fn semantic_colors(palette: &TerminalPalette) -> Semantic {
    let bright = &palette.ansi[9..16];
    let pool: &[Rgb] = if bright.iter().any(|color| to_oklch(*color).c > 0.02) {
        bright
    } else {
        &palette.ansi[1..7]
    };
    let bg = palette.background;
    Semantic {
        red: nearest_hue(pool, 29.0, bg),
        green: nearest_hue(pool, 142.0, bg),
        yellow: nearest_hue(pool, 90.0, bg),
        blue: nearest_hue(pool, 264.0, bg),
        magenta: nearest_hue(pool, 328.0, bg),
        cyan: nearest_hue(pool, 195.0, bg),
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Surfaces {
    pub editor: Rgb,
    #[allow(dead_code)]
    pub raised: Rgb,
    pub sunken: Rgb,
    #[allow(dead_code)]
    pub overlay: Rgb,
    pub border: Rgb,
    pub hover: Rgb,
    #[allow(dead_code)]
    pub active: Rgb,
}

pub fn surfaces(background: Rgb, foreground: Rgb) -> Surfaces {
    Surfaces {
        editor: background,
        raised: shade(background, 6),
        sunken: shade(background, -10),
        overlay: shade(background, 20),
        border: mix(background, foreground, 0.14),
        hover: mix(background, foreground, 0.08),
        active: mix(background, foreground, 0.16),
    }
}

#[derive(Debug, Clone)]
pub struct TerminalPalette {
    pub background: Rgb,
    pub foreground: Rgb,
    /// The sixteen ANSI slots, in order.
    pub ansi: [Rgb; 16],
}

/// Donor fallback palette, used when the terminal does not answer OSC color
/// queries (non-TTY, SSH without passthrough, tmux without passthrough).
pub const FALLBACK_BACKGROUND: Rgb = [13, 15, 19];
pub const FALLBACK_FOREGROUND: Rgb = [230, 233, 239];
pub const FALLBACK_ANSI: [Rgb; 16] = [
    [26, 27, 30],
    [229, 72, 77],
    [48, 164, 108],
    [245, 165, 36],
    [93, 156, 255],
    [186, 148, 255],
    [94, 201, 227],
    [200, 205, 215],
    [90, 96, 106],
    [255, 108, 112],
    [76, 194, 138],
    [255, 196, 84],
    [124, 178, 255],
    [206, 176, 255],
    [126, 220, 240],
    [235, 238, 245],
];

impl Default for TerminalPalette {
    fn default() -> Self {
        Self {
            background: FALLBACK_BACKGROUND,
            foreground: FALLBACK_FOREGROUND,
            ansi: FALLBACK_ANSI,
        }
    }
}

/// Terminals answer colour queries as rgb:RRRR/GGGG/BBBB, at whatever width
/// they feel like, so each component is scaled by its own digit count.
pub fn parse_color(reply: &str) -> Option<Rgb> {
    let body = reply.strip_prefix("rgb:")?;
    let mut parts = body.split('/');
    let scale = |raw: &str| {
        let digits = raw.len();
        if digits == 0 || digits > 4 || !raw.bytes().all(|b| b.is_ascii_hexdigit()) {
            return None;
        }
        let value = u32::from_str_radix(raw, 16).ok()?;
        let max = 16u32.pow(digits as u32) - 1;
        Some(((f64::from(value) / f64::from(max)) * 255.0).round() as u8)
    };
    Some([
        scale(parts.next()?)?,
        scale(parts.next()?)?,
        scale(parts.next()?)?,
    ])
}

#[derive(Debug, Default)]
pub struct ParsedReplies {
    pub background: Option<Rgb>,
    pub foreground: Option<Rgb>,
    pub ansi: [Option<Rgb>; 16],
}

/// Parse a raw byte stream of OSC 10/11/4 replies terminated by BEL or ST.
pub fn parse_replies(raw: &str) -> ParsedReplies {
    let mut parsed = ParsedReplies::default();
    let bytes = raw.as_bytes();
    let mut index = 0;
    while index + 2 < bytes.len() {
        if bytes[index] != 0x1b || bytes[index + 1] != b']' {
            index += 1;
            continue;
        }
        let start = index + 2;
        let mut end = None;
        let mut cursor = start;
        while cursor < bytes.len() {
            if bytes[cursor] == 0x07 {
                end = Some((cursor, 1));
                break;
            }
            if bytes[cursor] == 0x1b && cursor + 1 < bytes.len() && bytes[cursor + 1] == b'\\' {
                end = Some((cursor, 2));
                break;
            }
            cursor += 1;
        }
        let Some((stop, skip)) = end else {
            break;
        };
        let body = &raw[start..stop];
        let mut sections = body.splitn(3, ';');
        match (sections.next(), sections.next(), sections.next()) {
            (Some("11"), Some(color), None) => {
                if let Some(rgb) = parse_color(color) {
                    parsed.background = Some(rgb);
                }
            }
            (Some("10"), Some(color), None) => {
                if let Some(rgb) = parse_color(color) {
                    parsed.foreground = Some(rgb);
                }
            }
            (Some("4"), Some(slot), Some(color)) => {
                if let Ok(slot) = slot.parse::<usize>() {
                    if slot < 16 {
                        if let Some(rgb) = parse_color(color) {
                            parsed.ansi[slot] = Some(rgb);
                        }
                    }
                }
            }
            _ => {}
        }
        index = stop + skip;
    }
    parsed
}

pub fn with_fallbacks(parsed: Option<ParsedReplies>) -> TerminalPalette {
    let fallback = TerminalPalette::default();
    let Some(parsed) = parsed else {
        return fallback;
    };
    let mut ansi = FALLBACK_ANSI;
    for (slot, reply) in parsed.ansi.iter().enumerate() {
        if let Some(color) = reply {
            ansi[slot] = *color;
        }
    }
    TerminalPalette {
        background: parsed.background.unwrap_or(fallback.background),
        foreground: parsed.foreground.unwrap_or(fallback.foreground),
        ansi,
    }
}

fn build_query() -> String {
    let mut query = String::from("\x1b]11;?\x07\x1b]10;?\x07");
    for slot in 0..16 {
        query.push_str(&format!("\x1b]4;{slot};?\x07"));
    }
    // The device-attributes reply comes after the colours, so it marks the end.
    query.push_str("\x1b[c");
    query
}

/// Query the enclosing terminal for its palette over /dev/tty, like the donor.
/// Returns `None` when there is no TTY or the terminal stays silent; callers
/// must fall back to [`TerminalPalette::default`]. donor-parity timeouts:
/// 400ms idle settle, 2000ms hard cap.
#[cfg(unix)]
pub fn query_terminal() -> Option<ParsedReplies> {
    use std::fs::OpenOptions;
    use std::io::{Read, Write};
    use std::sync::mpsc;
    use std::time::Duration;

    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open("/dev/tty")
        .ok()?;
    let reader = file.try_clone().ok()?;
    let (sender, receiver) = mpsc::channel::<Vec<u8>>();
    std::thread::spawn(move || {
        let mut reader = reader;
        let mut buffer = [0u8; 1024];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(count) => {
                    if sender.send(buffer[..count].to_vec()).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
    });

    let mut writer = file;
    if writer.write_all(build_query().as_bytes()).is_err() {
        return None;
    }
    let _ = writer.flush();

    let idle = Duration::from_millis(400);
    let cap = Duration::from_millis(2000);
    let started = std::time::Instant::now();
    let mut raw: Vec<u8> = Vec::new();
    loop {
        if started.elapsed() >= cap {
            break;
        }
        match receiver.recv_timeout(idle) {
            Ok(chunk) => {
                raw.extend_from_slice(&chunk);
                if raw
                    .windows(3)
                    .any(|w| w[0] == 0x1b && w[1] == b'[' && w[2] == b'?')
                {
                    break;
                }
            }
            Err(_) => break,
        }
    }
    if raw.is_empty() {
        return None;
    }
    Some(parse_replies(&String::from_utf8_lossy(&raw)))
}

#[cfg(not(unix))]
pub fn query_terminal() -> Option<ParsedReplies> {
    None
}

/// Cell-opaque theme derived from a terminal palette. Terminals cannot do
/// alpha, so every translucent donor token is pre-composited onto its surface
/// with [`mix`].
#[derive(Debug, Clone, Copy)]
pub struct Colors {
    pub bg: ratatui::style::Color,
    pub panel: ratatui::style::Color,
    pub panel2: ratatui::style::Color,
    pub border: ratatui::style::Color,
    pub text: ratatui::style::Color,
    pub muted: ratatui::style::Color,
    #[allow(dead_code)]
    pub faint: ratatui::style::Color,
    pub accent: ratatui::style::Color,
    pub accent_dim: ratatui::style::Color,
    pub good: ratatui::style::Color,
    pub warn: ratatui::style::Color,
    pub bad: ratatui::style::Color,
}

fn rgb(color: Rgb) -> ratatui::style::Color {
    ratatui::style::Color::Rgb(color[0], color[1], color[2])
}

impl Colors {
    pub fn generate(palette: &TerminalPalette) -> Self {
        let bg = palette.background;
        let fg = palette.foreground;
        let surfaces = surfaces(bg, fg);
        let accent = semantic_colors(palette);
        let text = legible(fg, bg, 4.5);
        let active = focus_surface(bg, text);
        let primary = legible(accent.blue, bg, 4.5);
        let muted = legible(mix(text, bg, 0.4), bg, 4.5);
        let faint = legible(mix(text, bg, 0.62), bg, 3.0);
        Self {
            bg: rgb(surfaces.editor),
            panel: rgb(surfaces.sunken),
            panel2: rgb(surfaces.hover),
            border: rgb(legible(surfaces.border, bg, 3.0)),
            text: rgb(text),
            muted: rgb(muted),
            faint: rgb(faint),
            accent: rgb(primary),
            accent_dim: rgb(active),
            good: rgb(legible(accent.green, bg, 4.5)),
            warn: rgb(legible(accent.yellow, bg, 4.5)),
            bad: rgb(legible(accent.red, bg, 4.5)),
        }
    }

    pub fn fallback() -> Self {
        Self::generate(&TerminalPalette::default())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn black_white_contrast_is_twenty_one() {
        assert!((contrast([0, 0, 0], [255, 255, 255]) - 21.0).abs() < 0.01);
    }

    #[test]
    fn shade_steps_panels_off_pure_black_without_flattening() {
        let black = [0, 0, 0];
        // No room upward... there is room upward: steps up.
        assert_eq!(shade(black, 6), [6, 6, 6]);
        assert_eq!(shade(black, 20), [20, 20, 20]);
        // No room downward from black: steps the other way instead.
        assert_eq!(shade(black, -10), [10, 10, 10]);
        assert_eq!(shade([255, 255, 255], 10), [245, 245, 245]);
    }

    #[test]
    fn legible_pushes_low_contrast_accents_to_target() {
        let editor = [13, 15, 19];
        let dim = [40, 44, 52];
        assert!(contrast(dim, editor) < 4.5);
        let pushed = legible(dim, editor, 4.5);
        assert!(contrast(pushed, editor) >= 4.5);
        // Already-legible colors pass through untouched.
        assert_eq!(legible([235, 238, 245], editor, 4.5), [235, 238, 245]);
    }

    #[test]
    fn semantic_hues_come_from_bright_slots() {
        let palette = TerminalPalette::default();
        let semantic = semantic_colors(&palette);
        assert_eq!(semantic.red, [255, 108, 112]);
        assert_eq!(semantic.green, [76, 194, 138]);
        assert_eq!(semantic.blue, [124, 178, 255]);
    }

    #[test]
    fn semantic_colors_consider_the_sixteenth_bright_slot() {
        let mut palette = TerminalPalette::default();
        palette.ansi[9..15].fill([0, 0, 0]);
        palette.ansi[15] = [255, 0, 0];
        let semantic = semantic_colors(&palette);
        assert_eq!(semantic.red, [255, 0, 0]);
    }

    #[test]
    fn surfaces_form_a_dark_ladder() {
        let surfaces = surfaces([13, 15, 19], [230, 233, 239]);
        assert_eq!(surfaces.editor, [13, 15, 19]);
        assert!(luminance(surfaces.raised) > luminance(surfaces.editor));
        assert!(luminance(surfaces.sunken) < luminance(surfaces.editor));
        assert!(luminance(surfaces.overlay) > luminance(surfaces.raised));
    }

    #[test]
    fn osc_replies_parse_scaled_components() {
        let parsed = parse_replies("\x1b]11;rgb:0000/0000/0000\x07\x1b]10;rgb:ffff/ffff/ffff\x07\x1b]4;9;rgb:ff00/0000/0000\x1b\\");
        assert_eq!(parsed.background, Some([0, 0, 0]));
        assert_eq!(parsed.foreground, Some([255, 255, 255]));
        // Donor scaling is per-digit-count: ff00/ffff * 255 rounds to 254.
        assert_eq!(parsed.ansi[9], Some([254, 0, 0]));
        assert_eq!(parsed.ansi[0], None);
    }

    #[test]
    fn short_hex_replies_scale_by_digit_count() {
        assert_eq!(parse_color("rgb:f/f/f"), Some([255, 255, 255]));
        assert_eq!(parse_color("rgb:00/00/00"), Some([0, 0, 0]));
        assert!(parse_color("not-a-color").is_none());
    }

    #[test]
    fn fallbacks_fill_silent_slots() {
        let palette = with_fallbacks(None);
        assert_eq!(palette.background, FALLBACK_BACKGROUND);
        assert_eq!(palette.ansi[1], [229, 72, 77]);
        let partial = ParsedReplies {
            background: Some([1, 2, 3]),
            ..ParsedReplies::default()
        };
        let merged = with_fallbacks(Some(partial));
        assert_eq!(merged.background, [1, 2, 3]);
        assert_eq!(merged.foreground, FALLBACK_FOREGROUND);
    }

    #[test]
    fn fallback_theme_keeps_text_legible() {
        let colors = Colors::fallback();
        assert_ne!(colors.bg, colors.text);
        assert_ne!(colors.panel, colors.bg);
    }

    fn as_rgb(color: ratatui::style::Color) -> Rgb {
        match color {
            ratatui::style::Color::Rgb(r, g, b) => [r, g, b],
            other => panic!("expected RGB color, got {other:?}"),
        }
    }

    #[test]
    fn fallback_theme_has_a_focus_and_text_contrast_contract() {
        let colors = Colors::fallback();
        let bg = as_rgb(colors.bg);
        let active = as_rgb(colors.accent_dim);
        assert!(contrast(as_rgb(colors.text), bg) >= 4.5);
        assert!(contrast(as_rgb(colors.muted), bg) >= 4.5);
        assert!(contrast(as_rgb(colors.accent), bg) >= 4.5);
        assert!(contrast(as_rgb(colors.text), active) >= 4.5);
        assert!(contrast(as_rgb(colors.text), active) >= 3.0);
        assert!(contrast(active, bg) >= 3.0);
    }
}
