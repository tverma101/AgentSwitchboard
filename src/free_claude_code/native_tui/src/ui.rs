use crate::api::{ConfigField, ProviderStatus};
use crate::app::{
    match_palette, pretty, Activity, App, ChromeGeometry, EditorFocus, Focus, Hitbox, Modal, Page,
    TextInput, UiAction, CONTEXT_MAX, CONTEXT_MIN,
};
use crate::theme::Colors;
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;
use serde_json::Value;
use std::collections::HashMap;

pub fn render(frame: &mut Frame, app: &mut App) {
    let c = app.colors;
    app.hitboxes.clear();
    let area = frame.area();
    frame.render_widget(Block::default().style(Style::default().bg(c.bg)), area);

    // The native TUI is a control center, not a code editor. Its shell has one
    // direct page navigator and one page surface; files opened from an
    // explicit CLI request may still use the read-only viewer, but they never
    // add editor tabs or a second navigation rail to the default UI.
    let mut constraints = vec![Constraint::Length(3), Constraint::Min(10)];
    // A seven-row status panel is useful at a normal terminal size, but it
    // must not consume the page surface on a compact terminal. Keep the
    // toggle state so it comes back when the terminal is enlarged.
    let panel_open = app.panel_open && area.height >= 30;
    if panel_open {
        constraints.push(Constraint::Length(7));
    }
    constraints.push(Constraint::Length(1));
    constraints.push(Constraint::Length(1));
    let vertical = Layout::default()
        .direction(Direction::Vertical)
        .constraints(constraints)
        .split(area);
    let (body, panel, statusbar, footer) = if panel_open {
        (vertical[1], Some(vertical[2]), vertical[3], vertical[4])
    } else {
        (vertical[1], None, vertical[2], vertical[3])
    };

    let mut side = Vec::new();
    if app.sidebar_open {
        let width = if body.width >= 90 {
            30
        } else if body.width >= 64 {
            24
        } else {
            20
        };
        side.push(Constraint::Length(width.min(body.width.saturating_sub(20))));
    }
    side.push(Constraint::Min(20));
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints(side)
        .split(body);
    let (sidebar, editor) = if app.sidebar_open {
        (Some(cols[0]), cols[1])
    } else {
        (None, cols[0])
    };

    app.geometry = ChromeGeometry {
        top: vertical[0],
        // Kept as zero-sized compatibility fields for callers that inspect
        // the old geometry struct. No tab strip or activity gutter is drawn.
        tabs: Rect::default(),
        gutter: Rect::default(),
        sidebar: sidebar.unwrap_or_default(),
        main: editor,
        editor,
        panel: panel.unwrap_or_default(),
        statusbar,
        footer,
    };

    render_topbar(frame, app, vertical[0]);
    if let Some(sidebar) = sidebar {
        render_page_nav(frame, app, sidebar);
    }
    render_editor(frame, app, editor);
    if let Some(panel) = panel {
        render_panel(frame, app, panel);
    }
    render_statusbar(frame, app, statusbar);
    render_footer(frame, app, footer);
    render_modal(frame, app, area);
}

fn render_topbar(frame: &mut Frame, app: &App, area: Rect) {
    let c = app.colors;
    let (brand_width, status_width) = if area.width >= 90 {
        (28, 40)
    } else {
        let slot = (area.width / 3).max(1);
        (slot, slot)
    };
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Length(brand_width.min(area.width)),
            Constraint::Min(1),
            Constraint::Length(status_width.min(area.width)),
        ])
        .split(area);
    frame.render_widget(
        Paragraph::new(trim_to("AgentSwitchboard", chunks[0].width as usize))
            .style(
                Style::default()
                    .fg(c.text)
                    .bg(c.panel)
                    .add_modifier(Modifier::BOLD),
            )
            .block(bottom_border(c)),
        chunks[0],
    );
    frame.render_widget(
        Paragraph::new(trim_to(app.page.label(), chunks[1].width as usize))
            .alignment(ratatui::layout::Alignment::Center)
            .style(
                Style::default()
                    .fg(c.text)
                    .bg(c.panel)
                    .add_modifier(Modifier::BOLD),
            )
            .block(bottom_border(c)),
        chunks[1],
    );
    let state = if app.error.is_some() {
        Span::styled("● ERROR", Style::default().fg(c.bad))
    } else {
        Span::styled("● FCC LOCAL", Style::default().fg(c.good))
    };
    frame.render_widget(
        Paragraph::new(Line::from(vec![
            state,
            Span::raw("  "),
            Span::styled(
                trim_to(
                    &app.status_text(),
                    chunks[2].width.saturating_sub(10) as usize,
                ),
                Style::default().fg(c.muted),
            ),
        ]))
        .alignment(ratatui::layout::Alignment::Right)
        .style(Style::default().bg(c.panel))
        .block(bottom_border(c)),
        chunks[2],
    );
}

// Retained only for explicit-file compatibility tests; the direct FCC shell
// never calls this renderer.
#[allow(dead_code)]
fn render_tabs(frame: &mut Frame, app: &mut App, area: Rect) {
    if area.height == 0 || area.width == 0 {
        return;
    }
    let c = app.colors;
    frame.render_widget(Block::default().style(Style::default().bg(c.panel)), area);
    let mut x = area.x;
    // FCC pages are selected by the sidebar. Only open workspace files get a
    // tab, so the shell never shows two competing selections.
    let mut tabs: Vec<(String, bool, UiAction, Option<UiAction>)> = Vec::new();
    for (index, file) in app.files.iter().enumerate() {
        let active = matches!(app.editor_focus, EditorFocus::File(pos) if pos == index);
        tabs.push((
            format!("  {}", file.title()),
            active,
            UiAction::ActivateTab(index),
            Some(UiAction::CloseFile(index)),
        ));
    }
    for (label, active, action, close) in tabs {
        let mut width = label.chars().count() as u16 + 2;
        if close.is_some() {
            width += 3;
        }
        let remaining = area.right().saturating_sub(x);
        if remaining < 8 || x >= area.right() {
            break;
        }
        width = width.min(remaining);
        let rect = Rect {
            x,
            y: area.y,
            width,
            height: 1,
        };
        let style = if active {
            Style::default()
                .fg(c.text)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(c.muted).bg(c.panel)
        };
        frame.render_widget(
            Paragraph::new(trim_to(&label, width as usize - 1)).style(style),
            rect,
        );
        app.hitboxes.push(Hitbox { rect, action });
        x += width;
        if let Some(close) = close {
            if x + 3 <= area.right() {
                let close_rect = Rect {
                    x,
                    y: area.y,
                    width: 3,
                    height: 1,
                };
                frame.render_widget(
                    Paragraph::new(" x ").style(Style::default().fg(c.muted).bg(if active {
                        c.accent_dim
                    } else {
                        c.panel
                    })),
                    close_rect,
                );
                app.hitboxes.push(Hitbox {
                    rect: close_rect,
                    action: close,
                });
                x += 3;
            }
        }
    }
}

#[allow(dead_code)]
fn render_activity_bar(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    let block = Block::default()
        .borders(Borders::RIGHT)
        .border_style(Style::default().fg(c.border))
        .style(Style::default().bg(c.panel));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let (errors, warnings) = app.problem_counts();
    let problems = errors + warnings;
    let mut y = inner.y;
    for activity in Activity::ALL {
        if y >= inner.bottom() {
            break;
        }
        let cell = Rect {
            x: inner.x,
            y,
            width: inner.width,
            height: 1,
        };
        let label = if activity == Activity::Diagnostics && problems > 0 {
            format!(
                "{} {} {}",
                activity.icon(),
                activity.label(),
                problems.min(99)
            )
        } else {
            format!("{} {}", activity.icon(), activity.label())
        };
        let active = app.activity == activity;
        let style = if active {
            Style::default()
                .fg(c.accent)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(c.muted).bg(c.panel)
        };
        frame.render_widget(
            Paragraph::new(trim_to(&label, inner.width as usize)).style(style),
            cell,
        );
        app.hitboxes.push(Hitbox {
            rect: cell,
            action: UiAction::Activity(activity),
        });
        y += 1;
    }
}

#[allow(dead_code)]
fn sidebar_chrome(frame: &mut Frame, c: Colors, area: Rect) -> Rect {
    let block = Block::default()
        .borders(Borders::RIGHT)
        .border_style(Style::default().fg(c.border))
        .style(Style::default().bg(c.panel));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    inner
}

#[allow(dead_code)]
fn sidebar_header(frame: &mut Frame, c: Colors, inner: Rect, title: &str, subtitle: &str) {
    frame.render_widget(
        Paragraph::new(Line::from(Span::styled(
            title,
            Style::default().fg(c.muted).add_modifier(Modifier::BOLD),
        ))),
        Rect {
            x: inner.x + 1,
            y: inner.y,
            width: inner.width.saturating_sub(2),
            height: 1,
        },
    );
    frame.render_widget(
        Paragraph::new(trim_to(subtitle, inner.width.saturating_sub(2) as usize))
            .style(Style::default().fg(c.text)),
        Rect {
            x: inner.x + 1,
            y: inner.y + 1,
            width: inner.width.saturating_sub(2),
            height: 1,
        },
    );
}

#[allow(dead_code)]
fn render_sidebar(frame: &mut Frame, app: &mut App, area: Rect) {
    match app.activity {
        Activity::Explorer => render_explorer(frame, app, area),
        Activity::Search => render_search_panel(frame, app, area),
        Activity::SourceControl => render_git_panel(frame, app, area),
        Activity::Providers | Activity::Models | Activity::Diagnostics => {
            render_page_nav(frame, app, area)
        }
    }
}

fn workspace_name(app: &App) -> String {
    app.workspace
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| app.workspace.to_string_lossy().into_owned())
}

fn relative_path(app: &App, path: &std::path::Path) -> String {
    path.strip_prefix(&app.workspace)
        .unwrap_or(path)
        .to_string_lossy()
        .into_owned()
}

#[allow(dead_code)]
fn render_explorer(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    let inner = sidebar_chrome(frame, c, area);
    sidebar_header(frame, c, inner, "EXPLORER", &workspace_name(app));
    let top = inner.y + 2;
    let height = inner.bottom().saturating_sub(top) as usize;
    if height == 0 {
        return;
    }
    if app.tree.is_empty() {
        frame.render_widget(
            Paragraph::new("Empty folder").style(Style::default().fg(c.muted).bg(c.panel)),
            Rect {
                x: inner.x + 1,
                y: top,
                width: inner.width.saturating_sub(2),
                height: 1,
            },
        );
        return;
    }
    let start = if app.tree_cursor >= height {
        app.tree_cursor - height + 1
    } else {
        0
    };
    let open_paths: std::collections::HashSet<String> = app
        .files
        .iter()
        .map(|file| file.path.to_string_lossy().into_owned())
        .collect();
    for (offset, entry) in app.tree.iter().enumerate().skip(start).take(height) {
        let y = top + offset as u16 - start as u16;
        let row = Rect {
            x: inner.x,
            y,
            width: inner.width,
            height: 1,
        };
        let indent = "  ".repeat(entry.depth.min(6));
        let max_name = inner
            .width
            .saturating_sub((indent.chars().count() as u16) + 5) as usize;
        let (icon, mut style) = if entry.is_dir {
            let open = app.expanded.contains(&entry.path);
            (
                if open { "▾" } else { "▸" },
                Style::default().fg(c.text).bg(c.panel),
            )
        } else {
            (" ", Style::default().fg(c.muted).bg(c.panel))
        };
        if !entry.is_dir && open_paths.contains(&entry.path.to_string_lossy().into_owned()) {
            style = style.fg(c.accent);
        }
        if offset == app.tree_cursor && app.focus == Focus::Sidebar {
            style = Style::default()
                .fg(c.text)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD);
        }
        let text = format!("{indent}{icon} {}", trim_to(&entry.name, max_name.max(1)));
        frame.render_widget(Paragraph::new(text).style(style), row);
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::ActivateTree(offset),
        });
    }
}

#[allow(dead_code)]
fn render_search_panel(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    let inner = sidebar_chrome(frame, c, area);
    let subtitle = if app.search_query.is_empty() {
        "Press / to search".to_string()
    } else {
        format!("{} · {} hits", app.search_query, app.search_hits.len())
    };
    sidebar_header(frame, c, inner, "SEARCH", &subtitle);
    let top = inner.y + 2;
    let height = inner.bottom().saturating_sub(top) as usize;
    if height == 0 {
        return;
    }
    if app.search_hits.is_empty() {
        let hint = if app.search_query.is_empty() {
            "Type / to search the workspace"
        } else {
            "No results"
        };
        frame.render_widget(
            Paragraph::new(hint).style(Style::default().fg(c.muted).bg(c.panel)),
            Rect {
                x: inner.x + 1,
                y: top,
                width: inner.width.saturating_sub(2),
                height: 1,
            },
        );
        return;
    }
    // Flatten grouped hits so the cursor row stays visible.
    enum SearchRow {
        Header(String),
        Hit(usize),
    }
    let mut rows: Vec<SearchRow> = Vec::new();
    let mut last_path: Option<&std::path::Path> = None;
    for (index, hit) in app.search_hits.iter().enumerate() {
        if last_path != Some(hit.path.as_path()) {
            last_path = Some(hit.path.as_path());
            rows.push(SearchRow::Header(relative_path(app, &hit.path)));
        }
        rows.push(SearchRow::Hit(index));
    }
    let cursor_row = rows
        .iter()
        .position(|row| matches!(row, SearchRow::Hit(index) if *index == app.sidebar_cursor))
        .unwrap_or(0);
    let start = cursor_row.saturating_sub(height.saturating_sub(1));
    for (offset, row) in rows.iter().enumerate().skip(start).take(height) {
        let y = top + offset as u16 - start as u16;
        let row_rect = Rect {
            x: inner.x,
            y,
            width: inner.width,
            height: 1,
        };
        match row {
            SearchRow::Header(label) => {
                frame.render_widget(
                    Paragraph::new(trim_to(label, inner.width.saturating_sub(2) as usize))
                        .style(Style::default().fg(c.muted).bg(c.panel)),
                    Rect {
                        x: row_rect.x + 1,
                        y,
                        width: row_rect.width.saturating_sub(2),
                        height: 1,
                    },
                );
            }
            SearchRow::Hit(index) => {
                let Some(hit) = app.search_hits.get(*index) else {
                    continue;
                };
                let selected = *index == app.sidebar_cursor && app.focus == Focus::Sidebar;
                let style = if selected {
                    Style::default()
                        .fg(c.text)
                        .bg(c.accent_dim)
                        .add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(c.muted).bg(c.panel)
                };
                let text = format!(
                    "  {}: {}",
                    hit.line,
                    trim_to(&hit.text, inner.width.saturating_sub(8) as usize)
                );
                frame.render_widget(Paragraph::new(text).style(style), row_rect);
                app.hitboxes.push(Hitbox {
                    rect: row_rect,
                    action: UiAction::OpenSearchHit(*index),
                });
            }
        }
    }
}

#[allow(dead_code)]
fn git_change_style(c: Colors, staged: char, unstaged: char) -> Style {
    let base = Style::default().bg(c.panel);
    if staged == '?' || unstaged == '?' {
        base.fg(c.muted)
    } else if unstaged == 'D' || staged == 'D' {
        base.fg(c.bad)
    } else if unstaged != ' ' {
        base.fg(c.warn)
    } else {
        base.fg(c.good)
    }
}

#[allow(dead_code)]
fn render_git_panel(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    let inner = sidebar_chrome(frame, c, area);
    let subtitle = if app.git_branch.is_empty() {
        "not a git checkout".to_string()
    } else {
        format!("⑂ {}", app.git_branch)
    };
    sidebar_header(frame, c, inner, "SOURCE CONTROL", &subtitle);
    let top = inner.y + 2;
    let height = inner.bottom().saturating_sub(top) as usize;
    if height == 0 {
        return;
    }
    if let Some(error) = app.git_error.clone() {
        frame.render_widget(
            Paragraph::new(trim_to(&error, inner.width.saturating_sub(2) as usize))
                .style(Style::default().fg(c.muted).bg(c.panel)),
            Rect {
                x: inner.x + 1,
                y: top,
                width: inner.width.saturating_sub(2),
                height: 1,
            },
        );
        return;
    }
    if app.git_changes.is_empty() {
        frame.render_widget(
            Paragraph::new("Working tree clean").style(Style::default().fg(c.good).bg(c.panel)),
            Rect {
                x: inner.x + 1,
                y: top,
                width: inner.width.saturating_sub(2),
                height: 1,
            },
        );
        return;
    }
    let start = if app.sidebar_cursor >= height {
        app.sidebar_cursor - height + 1
    } else {
        0
    };
    for (offset, change) in app.git_changes.iter().enumerate().skip(start).take(height) {
        let y = top + offset as u16 - start as u16;
        let row = Rect {
            x: inner.x,
            y,
            width: inner.width,
            height: 1,
        };
        let mut style = git_change_style(c, change.staged, change.unstaged);
        if offset == app.sidebar_cursor && app.focus == Focus::Sidebar {
            style = style.bg(c.accent_dim).add_modifier(Modifier::BOLD);
        }
        let text = format!(
            "{}{} {}",
            change.staged,
            change.unstaged,
            trim_to(&change.path, inner.width.saturating_sub(5) as usize)
        );
        frame.render_widget(
            Paragraph::new(text).style(style),
            Rect {
                x: row.x + 1,
                y,
                width: row.width.saturating_sub(1),
                height: 1,
            },
        );
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::OpenGitChange(offset),
        });
    }
}

fn render_page_nav(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    let block = Block::default()
        .borders(Borders::RIGHT)
        .border_style(Style::default().fg(c.border))
        .style(Style::default().bg(c.panel));
    let inner = block.inner(area);
    frame.render_widget(block, area);

    let title = Rect {
        x: inner.x + 2,
        y: inner.y + 1,
        width: inner.width.saturating_sub(3),
        height: 2,
    };
    frame.render_widget(
        Paragraph::new(Line::from(vec![
            Span::styled("CONTROL", Style::default().fg(c.muted)),
            Span::raw("  "),
            Span::styled(
                "CENTER",
                Style::default().fg(c.text).add_modifier(Modifier::BOLD),
            ),
        ])),
        title,
    );

    // Use the whole sidebar for the finite FCC page list. The old layout
    // reserved six rows for a repeated active-model/context summary, which
    // hid pages on 80x24 terminals and made focused pages disappear.
    let nav_top = inner.y + 4;
    let nav_height = inner.bottom().saturating_sub(nav_top) as usize;
    let offset = list_offset(app.sidebar_cursor, Page::ALL.len(), nav_height);
    for (visible, page) in Page::ALL.iter().skip(offset).take(nav_height).enumerate() {
        let index = offset + visible;
        let y = nav_top + visible as u16;
        let row = Rect {
            x: inner.x + 1,
            y: y.min(inner.bottom().saturating_sub(1)),
            width: inner.width.saturating_sub(2),
            height: 1,
        };
        let selected = index == app.sidebar_cursor;
        let hovered = app.mouse.map(|(x, y)| contains(row, x, y)).unwrap_or(false);
        let focused = selected && app.focus == Focus::Sidebar;
        let style = if focused {
            Style::default()
                .fg(c.text)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD)
        } else if selected {
            Style::default()
                .fg(c.text)
                .bg(c.panel2)
                .add_modifier(Modifier::BOLD)
        } else if hovered {
            Style::default().fg(c.text).bg(c.panel2)
        } else {
            Style::default().fg(c.muted).bg(c.panel)
        };
        let marker = if focused {
            "▌ "
        } else if selected {
            "· "
        } else {
            "  "
        };
        frame.render_widget(
            Paragraph::new(format!(
                "{marker}{}",
                trim_to(page.label(), row.width.saturating_sub(2) as usize)
            ))
            .style(style),
            row,
        );
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::Navigate(*page),
        });
    }
}

fn render_editor(frame: &mut Frame, app: &mut App, area: Rect) {
    // Snapshot the visible file window first so rendering can push hitboxes.
    let snapshot = match app.editor_focus {
        EditorFocus::File(position) => app.files.get(position).map(|file| {
            let height = area.height.saturating_sub(1) as usize;
            let scroll = file.scroll.min(file.lines.len().saturating_sub(1).max(0));
            let end = (scroll + height.max(1)).min(file.lines.len());
            (
                relative_path(app, &file.path),
                scroll,
                file.lines.len(),
                file.truncated,
                file.lines[scroll..end].to_vec(),
                app.find_needle.clone(),
            )
        }),
        EditorFocus::Page => None,
    };
    let Some((relpath, scroll, total, truncated, window, needle)) = snapshot else {
        render_page(frame, app, area);
        return;
    };
    let c = app.colors;
    let crumbs = Rect {
        x: area.x + 1,
        y: area.y,
        width: area.width.saturating_sub(2),
        height: 1,
    };
    let mut crumb = trim_to(&relpath, crumbs.width as usize);
    if truncated {
        crumb.push_str("  … truncated (e opens externally)");
    }
    frame.render_widget(
        Paragraph::new(crumb).style(Style::default().fg(c.muted).bg(c.bg)),
        crumbs,
    );
    let digits = total.to_string().len().max(1);
    let mut y = area.y + 1;
    if window.is_empty() {
        frame.render_widget(
            Paragraph::new("— empty or binary file —").style(Style::default().fg(c.muted).bg(c.bg)),
            Rect {
                x: area.x + 1,
                y,
                width: area.width.saturating_sub(2),
                height: 1,
            },
        );
    }
    for (offset, line) in window.iter().enumerate() {
        if y >= area.bottom() {
            break;
        }
        let number = scroll + offset + 1;
        let base = if app.focus == Focus::Editor {
            Style::default().fg(c.text).bg(c.bg)
        } else {
            Style::default().fg(c.muted).bg(c.bg)
        };
        let hi = Style::default()
            .fg(c.text)
            .bg(c.accent_dim)
            .add_modifier(Modifier::BOLD);
        let mut spans = vec![Span::styled(
            format!("{:>width$} │ ", number, width = digits),
            Style::default().fg(c.muted).bg(c.bg),
        )];
        spans.extend(highlight_line(line, &needle, base, hi));
        frame.render_widget(
            Paragraph::new(Line::from(spans)),
            Rect {
                x: area.x + 1,
                y,
                width: area.width.saturating_sub(2),
                height: 1,
            },
        );
        y += 1;
    }
    app.hitboxes.push(Hitbox {
        rect: area,
        action: UiAction::FocusEditor,
    });
}

/// Split a viewer line into base/highlight spans for a case-insensitive
/// needle, tracking byte offsets through `char_indices` so multi-byte text
/// can never panic on a slice boundary.
fn highlight_line<'a>(line: &'a str, needle: &str, base: Style, hi: Style) -> Vec<Span<'a>> {
    if needle.is_empty() {
        return vec![Span::styled(line, base)];
    }
    let needle_lower = needle.to_lowercase();
    let needle_chars: Vec<char> = needle_lower.chars().collect();
    let chars: Vec<(usize, char)> = line.char_indices().collect();
    let mut spans = Vec::new();
    let mut segment_start = 0usize;
    let mut index = 0usize;
    while index < chars.len() {
        let matches = chars[index..]
            .iter()
            .take(needle_chars.len())
            .map(|(_, ch)| ch.to_lowercase().collect::<String>())
            .collect::<String>()
            == needle_lower;
        if matches && !needle_chars.is_empty() {
            let (byte_start, _) = chars[index];
            let (last_byte, last_char) = chars[index + needle_chars.len() - 1];
            let byte_end = last_byte + last_char.len_utf8();
            if segment_start < byte_start {
                spans.push(Span::styled(&line[segment_start..byte_start], base));
            }
            spans.push(Span::styled(&line[byte_start..byte_end], hi));
            segment_start = byte_end;
            index += needle_chars.len();
        } else {
            index += 1;
        }
    }
    if segment_start < line.len() {
        spans.push(Span::styled(&line[segment_start..], base));
    }
    if spans.is_empty() {
        spans.push(Span::styled(line, base));
    }
    spans
}

fn render_page(frame: &mut Frame, app: &mut App, area: Rect) {
    match app.page {
        Page::Dashboard => render_dashboard(frame, app, area),
        Page::Providers => render_providers(frame, app, area),
        Page::Repositories => render_repos(frame, app, area),
        Page::Models => render_models(frame, app, area),
        Page::Routing => render_field_page(frame, app, area, Page::Routing),
        Page::Context => render_context(frame, app, area),
        Page::Local => render_field_page(frame, app, area, Page::Local),
        Page::Settings => render_field_page(frame, app, area, Page::Settings),
        Page::Usage => render_usage(frame, app, area),
        Page::Diagnostics => render_diagnostics(frame, app, area),
    }
}

fn render_dashboard(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;

    let status = app.status_text();
    let status_kind = app
        .status
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("offline");
    let status_style = match status_kind.to_ascii_lowercase().as_str() {
        "running" | "ready" | "healthy" => Style::default().fg(c.good),
        "offline" | "error" | "failed" => Style::default().fg(c.bad),
        _ => Style::default().fg(c.warn),
    };
    let active_route = app.status_model();
    let launch_route = app
        .config_value("MODEL")
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "not configured".to_string());
    let inventory = app.model_inventory();
    let free_models = inventory
        .iter()
        .filter(|model| app.model_price_state(model) == crate::app::ModelPriceState::Free)
        .count();
    let (provider_count, ready_providers, attention_providers) = dashboard_provider_counts(app);
    let catalog_mode = app
        .model_catalog_mode()
        .unwrap_or_else(|| "server".to_string());
    let allowlist_count = app.model_catalog_allowlist().len();
    let mut allowlist_models = app
        .model_catalog_allowlist()
        .into_iter()
        .collect::<Vec<_>>();
    allowlist_models.sort_by_key(|model| model.to_ascii_lowercase());
    let pending = dashboard_pending_label(&app.status);
    let feedback = dashboard_feedback(app);
    let attention_labels = dashboard_attention_labels(app);
    let git = if let Some(error) = &app.git_error {
        error.clone()
    } else if app.git_branch.is_empty() {
        "not checked".to_string()
    } else {
        format!("{} · {} change(s)", app.git_branch, app.git_changes.len())
    };
    let workspace = app.workspace.to_string_lossy().into_owned();

    // On a narrow terminal, a two-column dashboard turns every value into a
    // clipped label. Collapse to one dense operational card instead.
    if area.width < 72 {
        let actions = [
            ("R", UiAction::Refresh),
            ("Normal", UiAction::LaunchClaude(false)),
            ("Danger", UiAction::LaunchClaude(true)),
        ];
        let rows = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Min(10),
                Constraint::Length(action_bar_height(area.width, &actions)),
            ])
            .split(area);
        let compact_width = rows[0].width.saturating_sub(2) as usize;
        dashboard_card(
            frame,
            c,
            rows[0],
            "DASHBOARD",
            vec![
                compact_kv(c, "Status", &status, compact_width, status_style),
                compact_kv(
                    c,
                    "MODEL",
                    &launch_route,
                    compact_width,
                    Style::default().fg(c.text),
                ),
                compact_kv(
                    c,
                    "ACTIVE",
                    &active_route,
                    compact_width,
                    Style::default().fg(c.text),
                ),
                compact_kv(
                    c,
                    "Models",
                    &format!(
                        "{}/{}/{} free",
                        app.models.models.len(),
                        inventory.len(),
                        free_models
                    ),
                    compact_width,
                    Style::default().fg(c.text),
                ),
                compact_kv(
                    c,
                    "Providers",
                    &format!("{} reg / {} attention", provider_count, attention_providers),
                    compact_width,
                    Style::default().fg(c.text),
                ),
                compact_kv(
                    c,
                    "Policy",
                    &catalog_mode,
                    compact_width,
                    Style::default().fg(c.text),
                ),
                compact_kv(
                    c,
                    "Context",
                    &format_tokens(&app.current_context()),
                    compact_width,
                    Style::default().fg(c.text),
                ),
                compact_kv(
                    c,
                    "Root",
                    &workspace_name(app),
                    compact_width,
                    Style::default().fg(c.text),
                ),
                compact_kv(
                    c,
                    "Feedback",
                    &feedback,
                    compact_width,
                    Style::default().fg(c.text),
                ),
            ],
        );
        action_bar(frame, app, rows[1], &actions);
        return;
    }

    let actions = [
        ("Refresh", UiAction::Refresh),
        ("Claude normal", UiAction::LaunchClaude(false)),
        ("Claude danger", UiAction::LaunchClaude(true)),
    ];
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(6),
            Constraint::Length(6),
            Constraint::Min(5),
            Constraint::Length(action_bar_height(area.width, &actions)),
        ])
        .split(area);

    let top = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(rows[0]);
    dashboard_card(
        frame,
        c,
        top[0],
        "SERVER",
        vec![
            styled_kv(c, "Status", &status, status_style),
            kv(c, "API", "loopback Admin"),
            kv(
                c,
                "Failures",
                &format!("{} provider(s)", app.models.failed_providers.len()),
            ),
            kv(c, "Feedback", &trim_to(&feedback, 42)),
        ],
    );
    dashboard_card(
        frame,
        c,
        top[1],
        "LAUNCH ROUTE",
        vec![
            kv(c, "MODEL", &launch_route),
            kv(c, "ACTIVE", &active_route),
            kv(c, "Context", &format_tokens(&app.current_context())),
            kv(c, "Repo", &app.launch_repo_name()),
        ],
    );

    let middle = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(rows[1]);
    dashboard_card(
        frame,
        c,
        middle[0],
        "MODELS",
        vec![
            kv(c, "Active", &app.models.models.len().to_string()),
            kv(c, "Catalog", &inventory.len().to_string()),
            styled_kv(
                c,
                "FREE",
                &free_models.to_string(),
                Style::default().fg(c.good),
            ),
            kv(c, "View", app.model_scope_label()),
        ],
    );
    dashboard_card(
        frame,
        c,
        middle[1],
        "PROVIDERS",
        vec![
            kv(c, "Registered", &provider_count.to_string()),
            styled_kv(
                c,
                "Ready",
                &ready_providers.to_string(),
                Style::default().fg(c.good),
            ),
            styled_kv(
                c,
                "Attention",
                &attention_providers.to_string(),
                if attention_providers == 0 {
                    Style::default().fg(c.good)
                } else {
                    Style::default().fg(c.warn)
                },
            ),
            kv(c, "Failed", &app.models.failed_providers.len().to_string()),
        ],
    );

    let lower = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(rows[2]);
    let mut policy_lines = vec![
        kv(c, "Catalog mode", &catalog_mode),
        kv(
            c,
            "Allowlist",
            &format!("{} exact model(s)", allowlist_count),
        ),
        kv(c, "Model view", app.model_scope_label()),
        kv(c, "Provider", &app.model_provider_label()),
    ];
    if allowlist_models.is_empty() {
        policy_lines.push(kv(c, "Enabled", "none explicitly listed"));
    } else {
        policy_lines.push(Line::from(Span::styled(
            "Enabled exact routes",
            Style::default().fg(c.muted).add_modifier(Modifier::BOLD),
        )));
        for model in allowlist_models.iter().take(12) {
            policy_lines.push(Line::from(vec![
                Span::styled("  • ", Style::default().fg(c.accent)),
                Span::styled(trim_to(model, 52), Style::default().fg(c.text)),
            ]));
        }
        if allowlist_models.len() > 12 {
            policy_lines.push(Line::from(Span::styled(
                format!("  … plus {} more", allowlist_models.len() - 12),
                Style::default().fg(c.muted),
            )));
        }
    }
    dashboard_card(frame, c, lower[0], "POLICY", policy_lines);

    let mut workspace_lines = vec![
        kv(c, "Root", &workspace),
        kv(c, "Git", &git),
        kv(c, "Changes", &app.git_changes.len().to_string()),
        kv(c, "Pending", &pending),
        kv(c, "Feedback", &trim_to(&feedback, 42)),
    ];
    if attention_labels.is_empty() {
        workspace_lines.push(kv(c, "Health", "all registered providers ready"));
    } else {
        workspace_lines.push(kv(
            c,
            "Attention",
            &format!("{} provider(s)", attention_labels.len()),
        ));
        for label in attention_labels.iter().take(12) {
            workspace_lines.push(Line::from(vec![
                Span::styled("  • ", Style::default().fg(c.warn)),
                Span::styled(trim_to(label, 52), Style::default().fg(c.text)),
            ]));
        }
        if attention_labels.len() > 12 {
            workspace_lines.push(Line::from(Span::styled(
                format!("  … plus {} more", attention_labels.len() - 12),
                Style::default().fg(c.muted),
            )));
        }
    }
    dashboard_card(frame, c, lower[1], "WORKSPACE + HEALTH", workspace_lines);
    action_bar(frame, app, rows[3], &actions);
}

fn dashboard_card(
    frame: &mut Frame,
    c: Colors,
    area: Rect,
    title: &str,
    lines: Vec<Line<'static>>,
) {
    let block = section_block(c, title);
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if inner.width > 0 && inner.height > 0 {
        frame.render_widget(
            Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
            inner,
        );
    }
}

fn dashboard_provider_counts(app: &App) -> (usize, usize, usize) {
    let mut statuses = HashMap::new();
    for provider in app
        .config
        .provider_status
        .iter()
        .chain(app.models.provider_status.iter())
    {
        if !provider.provider_id.is_empty() {
            statuses.insert(
                provider.provider_id.to_ascii_lowercase(),
                provider.status.trim().to_ascii_lowercase(),
            );
        }
    }
    for provider in &app.custom_providers {
        if provider.enabled && !provider.provider_id.is_empty() {
            statuses
                .entry(provider.provider_id.to_ascii_lowercase())
                .or_insert_with(|| "configured".to_string());
        }
    }

    let ready = statuses
        .values()
        .filter(|status| dashboard_provider_is_ready(status))
        .count();
    let attention = statuses.len().saturating_sub(ready);
    (statuses.len(), ready, attention)
}

fn dashboard_attention_labels(app: &App) -> Vec<String> {
    let mut providers = HashMap::new();
    for provider in app
        .config
        .provider_status
        .iter()
        .chain(app.models.provider_status.iter())
    {
        if provider.provider_id.is_empty() || dashboard_provider_is_ready(&provider.status) {
            continue;
        }
        let name = if provider.display_name.is_empty() {
            provider.provider_id.clone()
        } else {
            provider.display_name.clone()
        };
        let state = if provider.label.is_empty() {
            provider.status.clone()
        } else {
            provider.label.clone()
        };
        providers.insert(
            provider.provider_id.to_ascii_lowercase(),
            format!("{name} · {state}"),
        );
    }
    let mut labels = providers.into_values().collect::<Vec<_>>();
    labels.sort_by_key(|label| label.to_ascii_lowercase());
    labels
}

fn dashboard_provider_is_ready(status: &str) -> bool {
    matches!(
        status.trim().to_ascii_lowercase().as_str(),
        "configured" | "reachable" | "connected" | "ready" | "available"
    )
}

fn dashboard_pending_label(status: &Value) -> String {
    let count = match status.get("pending_fields") {
        Some(Value::Array(values)) => values.len(),
        Some(Value::Object(values)) => values.len(),
        Some(Value::String(value)) if !value.trim().is_empty() => 1,
        _ => 0,
    };
    if count == 0 {
        "none".to_string()
    } else {
        format!("{count} field(s)")
    }
}

fn dashboard_feedback(app: &App) -> String {
    if let Some(error) = &app.error {
        format!("error: {}", trim_to(error, 52))
    } else if let Some(notice) = &app.notice {
        format!("ok: {}", trim_to(notice, 52))
    } else {
        "none".to_string()
    }
}

fn render_providers(frame: &mut Frame, app: &mut App, area: Rect) {
    let providers = app.config.provider_status.clone();
    let selected = providers.get(app.provider_selected).cloned();
    let mut actions = vec![
        ("Test", UiAction::TestProvider),
        ("New custom", UiAction::NewCustomProvider),
    ];
    if selected
        .as_ref()
        .map(|provider| provider.custom)
        .unwrap_or(false)
    {
        actions.push(("Edit custom", UiAction::EditCustomProvider));
        actions.push(("Delete", UiAction::DeleteCustomProvider));
    }
    if selected
        .as_ref()
        .is_some_and(|provider| provider.kind == "connected_account")
    {
        actions.push(("Sign in", UiAction::LoginProvider));
        actions.push(("Disconnect", UiAction::DisconnectProvider));
    } else if selected.as_ref().is_some_and(|provider| !provider.custom) {
        actions.insert(0, ("Configure", UiAction::ConfigureProvider));
    }
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(10),
            Constraint::Length(action_bar_height(area.width, &actions)),
        ])
        .split(area);
    let panes = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(45), Constraint::Percentage(55)])
        .split(rows[0]);

    render_provider_list(frame, app, panes[0], &providers);
    render_provider_detail(frame, app.colors, selected.as_ref(), panes[1]);
    action_bar(frame, app, rows[1], &actions);
}

fn render_provider_list(
    frame: &mut Frame,
    app: &mut App,
    area: Rect,
    providers: &[ProviderStatus],
) {
    let c = app.colors;
    let range = if providers.is_empty() {
        "0/0".to_string()
    } else {
        format!(
            "{}/{}",
            app.provider_selected.saturating_add(1),
            providers.len()
        )
    };
    let block_title = format!("Providers · {range}");
    let block = section_block(c, &block_title);
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if providers.is_empty() {
        frame.render_widget(
            Paragraph::new("No providers advertised by fcc-server")
                .style(Style::default().fg(c.muted)),
            inner,
        );
        return;
    }
    let height = inner.height as usize;
    let offset = list_offset(app.provider_selected, providers.len(), height);
    for (visible, provider) in providers.iter().skip(offset).take(height).enumerate() {
        let index = offset + visible;
        let row = Rect {
            x: inner.x,
            y: inner.y + visible as u16,
            width: inner.width,
            height: 1,
        };
        let selected = index == app.provider_selected;
        let focused = selected && app.focus == Focus::Editor;
        let status_color = provider_color(c, &provider.status);
        let label = if provider.display_name.is_empty() {
            &provider.provider_id
        } else {
            &provider.display_name
        };
        let line = Line::from(vec![
            Span::styled(
                if focused {
                    "▌ "
                } else if selected {
                    "· "
                } else {
                    "  "
                },
                Style::default().fg(c.accent),
            ),
            Span::styled(
                trim_to(label, 24),
                if focused {
                    Style::default().fg(c.text).add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(c.text)
                },
            ),
            Span::raw("  "),
            Span::styled(
                trim_to(&provider.label, 18),
                Style::default().fg(status_color),
            ),
        ]);
        let style = if focused {
            Style::default().bg(c.accent_dim)
        } else if selected {
            Style::default().bg(c.panel2)
        } else {
            Style::default().bg(c.bg)
        };
        frame.render_widget(Paragraph::new(line).style(style), row);
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::SelectProvider(index),
        });
    }
}

fn render_provider_detail(
    frame: &mut Frame,
    c: Colors,
    provider: Option<&ProviderStatus>,
    area: Rect,
) {
    let block = section_block(c, "Inspector");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let Some(provider) = provider else {
        frame.render_widget(
            Paragraph::new("Select a provider").style(Style::default().fg(c.muted)),
            inner,
        );
        return;
    };
    let mut lines = vec![
        Line::from(Span::styled(
            if provider.display_name.is_empty() {
                provider.provider_id.clone()
            } else {
                provider.display_name.clone()
            },
            Style::default().fg(c.text).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        kv(c, "Provider ID", &provider.provider_id),
        kv(c, "Kind", &provider.kind),
        Line::from(vec![
            Span::styled("Status          ", Style::default().fg(c.muted)),
            Span::styled(
                if provider.label.is_empty() {
                    provider.status.clone()
                } else {
                    provider.label.clone()
                },
                Style::default().fg(provider_color(c, &provider.status)),
            ),
        ]),
    ];
    if !provider.base_url.is_empty() {
        lines.push(kv(c, "Base URL", &provider.base_url));
    }
    if !provider.configuration.is_empty() {
        lines.push(kv(c, "Required config", &provider.configuration));
    }
    if provider.custom {
        lines.push(kv(
            c,
            "API key",
            if provider.api_key_configured == Some(true) {
                "configured"
            } else {
                "not configured"
            },
        ));
        lines.push(kv(
            c,
            "Proxy",
            if provider.proxy_configured == Some(true) {
                "configured"
            } else {
                "not configured"
            },
        ));
        if !provider.model_ids.is_empty() {
            lines.push(kv(c, "Models", &provider.model_ids.join(", ")));
        }
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled("Secrets are never read back into this UI. Enter replaces a configured key; leaving the secret editor blank preserves it.", Style::default().fg(c.muted))));
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
}

/// Local GitHub checkouts for the next Claude launch. One tap (click or
/// Enter) points the next launch at a checkout; `O` opens an arbitrary path
/// and `R` rescans. Only checkouts with a GitHub remote are listed, matching
/// the classic picker contract.
fn render_repos(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    let actions = [
        ("Use for launch", UiAction::UseSelectedRepo),
        ("Open path", UiAction::OpenRepoPath),
        ("Refresh", UiAction::RescanRepos),
    ];
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(6),
            Constraint::Length(action_bar_height(area.width, &actions)),
        ])
        .split(area);
    let range = if app.repos.is_empty() {
        "0/0".to_string()
    } else {
        format!(
            "{}/{}",
            app.repo_selected.saturating_add(1),
            app.repos.len()
        )
    };
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(vec![
                Span::raw(" "),
                Span::styled(
                    "REPOS",
                    Style::default().fg(c.muted).add_modifier(Modifier::BOLD),
                ),
                Span::raw("  "),
                Span::styled(
                    format!(
                        "{} found · {} · launch → {}",
                        app.repos.len(),
                        app.repo_scope_label(),
                        app.launch_repo_name()
                    ),
                    Style::default().fg(c.muted),
                ),
            ]),
            Line::from(Span::styled(
                " Enter/click uses for next launch · O opens a path · R rescans",
                Style::default().fg(c.text),
            )),
        ])
        .style(Style::default().bg(c.panel2))
        .block(bottom_border(c)),
        rows[0],
    );
    let block_title = format!("Repositories · {range}");
    let block = section_block(c, &block_title);
    let inner = block.inner(rows[1]);
    frame.render_widget(block, rows[1]);
    if app.repos.is_empty() {
        let message = if app.background_busy() {
            "Scanning local checkouts…"
        } else if !app.repos_scanned {
            "Preparing repository scan…"
        } else {
            "No GitHub checkouts under the working directory, ~/src, ~/Projects, or ~/Documents. O opens a path · R rescans."
        };
        frame.render_widget(
            Paragraph::new(message)
                .wrap(Wrap { trim: true })
                .style(Style::default().fg(c.muted)),
            inner,
        );
    } else {
        let offset = list_offset(app.repo_selected, app.repos.len(), inner.height as usize);
        for (visible, repo) in app
            .repos
            .iter()
            .skip(offset)
            .take(inner.height as usize)
            .enumerate()
        {
            let index = offset + visible;
            let row = Rect {
                x: inner.x,
                y: inner.y + visible as u16,
                width: inner.width,
                height: 1,
            };
            let selected = index == app.repo_selected;
            let focused = selected && app.focus == Focus::Editor;
            let style = if focused {
                Style::default()
                    .bg(c.accent_dim)
                    .fg(c.text)
                    .add_modifier(Modifier::BOLD)
            } else if selected {
                Style::default().bg(c.panel2).fg(c.text)
            } else {
                Style::default().bg(c.bg).fg(c.text)
            };
            // `●` is the checkout the next Claude launch runs in; `▌`/`·`
            // is the keyboard cursor. They are independent on purpose.
            let marker = if app
                .launch_repo
                .as_ref()
                .is_some_and(|path| *path == repo.path)
            {
                "● "
            } else if focused {
                "▌ "
            } else if selected {
                "· "
            } else {
                "  "
            };
            let text = format!(
                "{marker}{}  {}  {}",
                repo.identity(),
                repo.branch,
                repo.display_path()
            );
            frame.render_widget(
                Paragraph::new(trim_to(&text, inner.width as usize)).style(style),
                row,
            );
            app.hitboxes.push(Hitbox {
                rect: row,
                action: UiAction::UseRepo(index),
            });
        }
    }
    action_bar(frame, app, rows[2], &actions);
}

fn render_models(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    app.normalize_model_filters();
    let models = app.filtered_models();
    let free_action = if app.model_price_filter == crate::app::ModelPriceFilter::FreeOnly {
        "Free: ON"
    } else {
        "Free: OFF"
    };
    // MODEL assignment lives on Enter and the palette; the bar stays at
    // five one-tap actions so it fits one row on narrow terminals too.
    let actions = [
        ("Search", UiAction::SearchModels),
        ("Provider", UiAction::ChooseModelProvider),
        (free_action, UiAction::CycleModelPrice),
        ("Disable all", UiAction::DisableAllModels),
        ("Refresh", UiAction::Refresh),
    ];
    // One header block (counts + active filters + one-line how-to), then one
    // full-width list. The inspector half, the second filter bar, and the
    // catalog/active view button were chrome around a one-boolean choice;
    // the exact route rides in the row itself and `V` still flips the view.
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(8),
            Constraint::Length(action_bar_height(area.width, &actions)),
        ])
        .split(area);
    let free_count = models
        .iter()
        .filter(|model| app.model_price_state(model) == crate::app::ModelPriceState::Free)
        .count();
    let catalog_count = app.model_inventory().len();
    let failures = app.models.failed_providers.len();
    let mut counts = format!(
        "{} shown · {} on · {} catalog · {} free (free first)",
        models.len(),
        app.models.models.len(),
        catalog_count,
        free_count,
    );
    if failures > 0 {
        counts.push_str(&format!(" · {failures} failed"));
    }
    let free_word = if app.model_price_filter == crate::app::ModelPriceFilter::FreeOnly {
        "Free: ON"
    } else {
        "Free: OFF"
    };
    // Single-line filter state plus the whole interaction model in one breath.
    // "Turn on/off" on purpose: no jargon, and the row tap is the action.
    // Compact terminals get state only; the how-to needs ~100 columns.
    let provider = if app.model_provider_filter == "all" {
        "All".to_string()
    } else {
        app.model_provider_label()
    };
    let filters = if area.width >= 100 {
        format!(
            " Provider: {provider} · {free_word} · View: {} · / search · Space/click on-off · Enter sets MODEL",
            app.model_scope_label(),
        )
    } else {
        format!(
            " Provider: {provider} · {free_word} · View: {}",
            app.model_scope_label(),
        )
    };
    let query = if app.model_query.is_empty() {
        String::new()
    } else {
        format!(" · search: {}", app.model_query)
    };
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(vec![
                Span::raw(" "),
                Span::styled(
                    "MODELS",
                    Style::default().fg(c.muted).add_modifier(Modifier::BOLD),
                ),
                Span::raw("  "),
                Span::styled(counts, Style::default().fg(c.muted)),
            ]),
            Line::from(Span::styled(
                format!("{filters}{query}"),
                Style::default().fg(c.text),
            )),
        ])
        .style(Style::default().bg(c.panel2))
        .block(bottom_border(c)),
        rows[0],
    );
    render_model_list(frame, app, rows[1], &models);
    action_bar(frame, app, rows[2], &actions);
}

fn render_model_list(frame: &mut Frame, app: &mut App, area: Rect, models: &[String]) {
    let c = app.colors;
    let range = if models.is_empty() {
        "0/0".to_string()
    } else {
        format!("{}/{}", app.model_selected.saturating_add(1), models.len())
    };
    let block_title = format!("Models · {range}");
    let block = section_block(c, &block_title);
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if models.is_empty() {
        let provider_has_catalog = app.model_provider_filter != "all"
            && app.model_inventory().iter().any(|model| {
                model
                    .split_once('/')
                    .map(|(provider, _)| provider)
                    .unwrap_or("other")
                    .eq_ignore_ascii_case(&app.model_provider_filter)
            });
        let message = if app.background_busy() {
            "Loading the model catalog for this provider…"
        } else if app.model_show_catalog {
            if app.model_price_filter == crate::app::ModelPriceFilter::FreeOnly
                && provider_has_catalog
            {
                "No free models for this provider. Free: OFF shows its full catalog."
            } else if app.model_provider_filter == "all" {
                "No catalog models match. Adjust search or press R to refresh."
            } else {
                "No catalog rows for this provider. R retries discovery · P shows all providers."
            }
        } else {
            "No active models match. Catalog shows every row."
        };
        frame.render_widget(
            Paragraph::new(message)
                .wrap(Wrap { trim: true })
                .style(Style::default().fg(c.muted)),
            inner,
        );
        return;
    }
    let offset = list_offset(app.model_selected, models.len(), inner.height as usize);
    for (visible, model) in models
        .iter()
        .skip(offset)
        .take(inner.height as usize)
        .enumerate()
    {
        let index = offset + visible;
        let row = Rect {
            x: inner.x,
            y: inner.y + visible as u16,
            width: inner.width,
            height: 1,
        };
        let selected = index == app.model_selected;
        let focused = selected && app.focus == Focus::Editor;
        let label = app.model_label(model);
        let routable = app.model_is_routable(model);
        let style = if focused {
            Style::default()
                .bg(c.accent_dim)
                .fg(c.text)
                .add_modifier(Modifier::BOLD)
        } else if selected {
            Style::default().bg(c.panel2).fg(c.text)
        } else {
            Style::default().bg(c.bg).fg(c.text)
        };
        let prefix = if focused {
            "▌ "
        } else if selected {
            "· "
        } else {
            "  "
        };
        // One boolean per row: the server-backed access state. Tapping the
        // row flips it immediately, so there is no second pending marker.
        // Glyphs and badges share fixed cell widths so every label column
        // starts at the same cell on every row.
        let (glyph, glyph_color) = if app.model_is_default(model) {
            ("● DEFAULT", c.accent)
        } else if routable {
            ("● ON     ", c.good)
        } else {
            ("○ OFF    ", c.muted)
        };
        // The exact route rides in the row: with no inspector pane, the row
        // is the only place the routable ID appears. Skip it when the label
        // already is the route.
        let display = if label == *model {
            label.clone()
        } else {
            format!("{label}  ·  {model}")
        };
        let badge = if app.model_price_state(model) == crate::app::ModelPriceState::Free {
            " FREE "
        } else {
            "      "
        };
        let available = inner.width.saturating_sub(prefix.chars().count() as u16) as usize;
        let suffix = format!("{badge}  {display}");
        let suffix_width = available.saturating_sub(glyph.chars().count());
        frame.render_widget(
            Paragraph::new(Line::from(vec![
                Span::styled(prefix, Style::default().fg(c.accent)),
                Span::styled(glyph, Style::default().fg(glyph_color)),
                Span::styled(trim_to(&suffix, suffix_width), Style::default().fg(c.text)),
            ]))
            .style(style),
            row,
        );
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::ToggleModel(index),
        });
    }
}

fn render_field_page(frame: &mut Frame, app: &mut App, area: Rect, page: Page) {
    let indices = match page {
        Page::Routing => app.routing_field_indices(),
        Page::Local => app.local_field_indices(),
        Page::Settings => app.settings_field_indices(),
        _ => Vec::new(),
    };
    let selected = match page {
        Page::Routing => app.routing_selected,
        Page::Local => app.local_selected,
        Page::Settings => app.setting_selected,
        _ => 0,
    };
    let mut actions = vec![
        ("Edit", UiAction::EditField),
        ("Refresh", UiAction::Refresh),
    ];
    if page == Page::Settings {
        actions.push((
            if app.show_advanced {
                "Hide advanced"
            } else {
                "Show advanced"
            },
            UiAction::ToggleAdvanced,
        ));
    }
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(10),
            Constraint::Length(action_bar_height(area.width, &actions)),
        ])
        .split(area);
    let panes = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(48), Constraint::Percentage(52)])
        .split(rows[0]);
    render_field_list(frame, app, panes[0], page, &indices, selected);
    let field = indices
        .get(selected)
        .and_then(|index| app.config.fields.get(*index))
        .cloned();
    render_field_detail(frame, app.colors, field.as_ref(), panes[1]);
    action_bar(frame, app, rows[1], &actions);
}

fn render_field_list(
    frame: &mut Frame,
    app: &mut App,
    area: Rect,
    page: Page,
    indices: &[usize],
    selected: usize,
) {
    let c = app.colors;
    let range = if indices.is_empty() {
        "0/0".to_string()
    } else {
        format!("{}/{}", selected.saturating_add(1), indices.len())
    };
    let block_title = format!(
        "{} · {range}",
        match page {
            Page::Routing => "Routing policy",
            Page::Local => "Local endpoints",
            Page::Settings => "Configuration",
            _ => "Fields",
        }
    );
    let block = section_block(c, &block_title);
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if indices.is_empty() {
        frame.render_widget(
            Paragraph::new("No fields available").style(Style::default().fg(c.muted)),
            inner,
        );
        return;
    }
    let offset = list_offset(selected, indices.len(), inner.height as usize);
    for (visible, field_index) in indices
        .iter()
        .skip(offset)
        .take(inner.height as usize)
        .enumerate()
    {
        let index = offset + visible;
        let field = &app.config.fields[*field_index];
        let row = Rect {
            x: inner.x,
            y: inner.y + visible as u16,
            width: inner.width,
            height: 1,
        };
        let selected_row = index == selected;
        let focused_row = selected_row && app.focus == Focus::Editor;
        let value = App::display_field_value(field);
        let label_width = (inner.width as usize / 2).max(12);
        let line = format!(
            "{}{:label_width$}  {}",
            if focused_row {
                "▌ "
            } else if selected_row {
                "· "
            } else {
                "  "
            },
            trim_to(&field.label, label_width),
            trim_to(
                &value,
                inner.width.saturating_sub(label_width as u16 + 5) as usize
            )
        );
        let style = if focused_row {
            Style::default()
                .bg(c.accent_dim)
                .fg(c.text)
                .add_modifier(Modifier::BOLD)
        } else if selected_row {
            Style::default().bg(c.panel2).fg(c.text)
        } else {
            Style::default().bg(c.bg).fg(c.text)
        };
        frame.render_widget(Paragraph::new(line).style(style), row);
        let action = match page {
            Page::Routing => UiAction::SelectRouting(index),
            Page::Local => UiAction::SelectLocal(index),
            Page::Settings => UiAction::SelectSetting(index),
            _ => continue,
        };
        app.hitboxes.push(Hitbox { rect: row, action });
    }
}

fn render_field_detail(frame: &mut Frame, c: Colors, field: Option<&ConfigField>, area: Rect) {
    let block = section_block(c, "Inspector");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let Some(field) = field else {
        frame.render_widget(
            Paragraph::new("Select a setting").style(Style::default().fg(c.muted)),
            inner,
        );
        return;
    };
    let mut lines = vec![
        Line::from(Span::styled(
            field.label.clone(),
            Style::default().fg(c.text).add_modifier(Modifier::BOLD),
        )),
        Line::from(Span::styled(
            field.key.clone(),
            Style::default().fg(c.muted),
        )),
        Line::from(""),
        kv(c, "Value", &App::display_field_value(field)),
        kv(c, "Source", &field.source),
        kv(c, "Type", &field.field_type),
        kv(c, "Locked", if field.locked { "Yes" } else { "No" }),
        kv(
            c,
            "Restart",
            if field.restart_required {
                "Required"
            } else {
                "No"
            },
        ),
        kv(
            c,
            "Session boundary",
            if field.session_sensitive { "Yes" } else { "No" },
        ),
        Line::from(""),
        Line::from(Span::styled(
            field.description.clone(),
            Style::default().fg(c.muted),
        )),
    ];
    if field.secret {
        lines.push(Line::from(""));
        lines.push(Line::from(Span::styled(
            "Configured secrets are masked. Enter replaces; X explicitly clears.",
            Style::default().fg(c.warn),
        )));
    }
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
}

fn render_context(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    let actions = [
        ("Edit context", UiAction::EditField),
        ("Refresh", UiAction::Refresh),
    ];
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(12),
            Constraint::Length(action_bar_height(area.width, &actions)),
        ])
        .split(area);
    let field = app.context_field().cloned();
    let current = field
        .as_ref()
        .map(App::display_field_value)
        .unwrap_or_else(|| "256000".to_string());
    let block = section_block(c, "Claude Code context policy");
    let inner = block.inner(rows[0]);
    frame.render_widget(block, rows[0]);
    let lines = vec![
        Line::from(Span::styled("SESSION WINDOW", Style::default().fg(c.muted).add_modifier(Modifier::BOLD))),
        Line::from(Span::styled(format_tokens(&current), Style::default().fg(c.accent).add_modifier(Modifier::BOLD))),
        Line::from(""),
        kv(c, "FCC setting", "FCC_CLAUDE_CONTEXT_TOKENS"),
        kv(c, "Accepted range", &format!("{CONTEXT_MIN} – {CONTEXT_MAX} tokens")),
        Line::from(""),
        Line::from(Span::styled("New FCC-launched Claude sessions receive the selected value as BOTH:", Style::default().fg(c.text))),
        Line::from(Span::styled("CLAUDE_CODE_MAX_CONTEXT_TOKENS", Style::default().fg(c.good))),
        Line::from(Span::styled("CLAUDE_CODE_AUTO_COMPACT_WINDOW", Style::default().fg(c.good))),
        Line::from(""),
        Line::from(Span::styled("Changing this setting does not resize an already-running Claude process. Known model-native ceilings smaller than the configured cap still win.", Style::default().fg(c.muted))),
        Line::from(""),
        Line::from(Span::styled("Default 256K is deliberate. Raise it only when the selected upstream model actually supports the larger window.", Style::default().fg(c.warn))),
    ];
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
    action_bar(frame, app, rows[1], &actions);
}

fn render_usage(frame: &mut Frame, app: &mut App, area: Rect) {
    let actions = [("Refresh", UiAction::Refresh)];
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(8),
            Constraint::Length(action_bar_height(area.width, &actions)),
        ])
        .split(area);
    render_scrollable_output(
        frame,
        app,
        rows[0],
        "30-day metadata-only usage",
        pretty(&app.usage),
    );
    action_bar(frame, app, rows[1], &actions);
}

fn render_diagnostics(frame: &mut Frame, app: &mut App, area: Rect) {
    let actions = [
        ("Run diagnostic", UiAction::RunDiagnostic),
        ("Refresh", UiAction::Refresh),
    ];
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(8),
            Constraint::Length(action_bar_height(area.width, &actions)),
        ])
        .split(area);
    let body = if app.diagnostic.is_null() {
        "Run a synthetic route diagnostic. No prompt content is sent to a provider.".to_string()
    } else {
        pretty(&app.diagnostic)
    };
    render_scrollable_output(frame, app, rows[0], "Route diagnostic", body);
    action_bar(frame, app, rows[1], &actions);
}

fn render_scrollable_output(
    frame: &mut Frame,
    app: &mut App,
    area: Rect,
    title: &str,
    body: String,
) {
    let c = app.colors;
    let block_width = area.width.saturating_sub(2).max(1);
    let total = crate::app::rendered_line_count(&body, block_width);
    let viewport = area.height.saturating_sub(2).max(1) as usize;
    let max_scroll = total.saturating_sub(viewport);
    let scroll = app.content_scroll.min(max_scroll);
    app.content_scroll = scroll;
    let first = if total == 0 { 0 } else { scroll + 1 };
    let last = (scroll + viewport).min(total);
    let block_title = format!("{title} · lines {first}–{last} of {total}");
    frame.render_widget(
        Paragraph::new(body)
            .style(Style::default().fg(c.text).bg(c.bg))
            .wrap(Wrap { trim: false })
            .scroll((scroll.min(u16::MAX as usize) as u16, 0))
            .block(section_block(c, &block_title)),
        area,
    );
}

fn render_panel(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    frame.render_widget(
        Block::default()
            .borders(Borders::TOP)
            .border_style(Style::default().fg(c.border))
            .style(Style::default().bg(c.panel)),
        area,
    );
    let (errors, warnings) = app.problem_counts();
    let header = format!("FCC STATUS · PROVIDER ALERTS ({})", errors + warnings);
    frame.render_widget(
        Paragraph::new(Span::styled(
            trim_to(&header, area.width.saturating_sub(2) as usize),
            Style::default().fg(c.muted).add_modifier(Modifier::BOLD),
        )),
        Rect {
            x: area.x + 1,
            y: area.y,
            width: area.width.saturating_sub(2),
            height: 1,
        },
    );
    let mut lines: Vec<(String, Style)> = Vec::new();
    for name in app.models.failed_providers.iter().take(3) {
        lines.push((
            format!("⚠ provider failed: {name}"),
            Style::default().fg(c.warn),
        ));
    }
    for provider in app
        .config
        .provider_status
        .iter()
        .filter(|provider| {
            matches!(
                provider.status.as_str(),
                "missing_key" | "missing_config" | "missing_url" | "unknown"
            )
        })
        .take(2)
    {
        lines.push((
            format!("⚠ {}: {}", provider.display_name, provider.status),
            Style::default().fg(c.warn),
        ));
    }
    if let Some(error) = &app.error {
        lines.push((error.clone(), Style::default().fg(c.bad)));
    } else if let Some(notice) = &app.notice {
        lines.push((notice.clone(), Style::default().fg(c.good)));
    } else {
        lines.push((app.status_text(), Style::default().fg(c.muted)));
    }
    let mut y = area.y + 1;
    for (text, style) in lines {
        if y >= area.bottom() {
            break;
        }
        frame.render_widget(
            Paragraph::new(trim_to(&text, area.width.saturating_sub(2) as usize)).style(style),
            Rect {
                x: area.x + 1,
                y,
                width: area.width.saturating_sub(2),
                height: 1,
            },
        );
        y += 1;
    }
}

fn render_statusbar(frame: &mut Frame, app: &App, area: Rect) {
    let c = app.colors;
    let bar = Style::default().fg(c.text).bg(c.panel2);
    let (errors, warnings) = app.problem_counts();
    let mut left = String::new();
    if !app.git_branch.is_empty() {
        left.push_str(&format!("⑂ {}  ", app.git_branch));
    }
    left.push_str(&workspace_name(app));
    if errors + warnings > 0 {
        left.push_str(&format!("  ✖{} ⚠{}", errors, warnings));
    } else {
        left.push_str("  ✓");
    }
    let right = if let Some((_, file)) = app.active_file() {
        let position = file.scroll + 1;
        format!(
            "Ln {position}/{}  {}  {}  FCC LOCAL",
            file.lines.len(),
            app.status_model_short(),
            format_tokens(&app.current_context())
        )
    } else {
        format!(
            "{}  {}  {}  FCC LOCAL",
            app.page.label(),
            app.status_model_short(),
            format_tokens(&app.current_context())
        )
    };
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(area);
    frame.render_widget(
        Paragraph::new(trim_to(&left, chunks[0].width as usize)).style(bar),
        chunks[0],
    );
    frame.render_widget(
        Paragraph::new(trim_to(&right, chunks[1].width as usize))
            .alignment(ratatui::layout::Alignment::Right)
            .style(bar),
        chunks[1],
    );
}

fn render_footer(frame: &mut Frame, app: &App, area: Rect) {
    let c = app.colors;
    let message = if let Some(error) = &app.error {
        Span::styled(
            trim_to(error, 72),
            Style::default().fg(c.bad).add_modifier(Modifier::BOLD),
        )
    } else if let Some(notice) = &app.notice {
        Span::styled(trim_to(notice, 72), Style::default().fg(c.good))
    } else {
        Span::styled("LOCAL · LOOPBACK ADMIN API", Style::default().fg(c.muted))
    };
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(45), Constraint::Percentage(55)])
        .split(area);
    frame.render_widget(
        Paragraph::new(Line::from(message)).style(Style::default().bg(c.panel)),
        chunks[0],
    );
    // Keep the footer for transient notices only. Navigation guidance belongs
    // in the actual page controls, not in a permanent decorative legend.
    frame.render_widget(
        Paragraph::new("").style(Style::default().bg(c.panel)),
        chunks[1],
    );
}

fn action_bar(frame: &mut Frame, app: &mut App, area: Rect, actions: &[(&str, UiAction)]) {
    let c = app.colors;
    frame.render_widget(
        Block::default()
            .borders(Borders::TOP)
            .border_style(Style::default().fg(c.border))
            .style(Style::default().bg(c.panel)),
        area,
    );
    if area.width < 3 || area.height < 2 {
        return;
    }
    let left = area.x.saturating_add(1);
    let right = area.right().saturating_sub(1);
    let max_width = right.saturating_sub(left).max(1);
    let mut x = left;
    let mut y = area.y + 1;
    for (label, action) in actions {
        if y >= area.bottom() {
            break;
        }
        let desired = label.chars().count() as u16 + 4;
        let width = desired.min(max_width).max(1);
        if x > left && x.saturating_add(width) > right {
            y = y.saturating_add(1);
            x = left;
            if y >= area.bottom() {
                break;
            }
        }
        let button = Rect {
            x,
            y,
            width,
            height: 1,
        };
        let hovered = app
            .mouse
            .map(|(mx, my)| contains(button, mx, my))
            .unwrap_or(false);
        let style = if hovered {
            Style::default()
                .fg(c.text)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(c.text).bg(c.panel2)
        };
        frame.render_widget(
            Paragraph::new(format!(
                "  {}  ",
                trim_to(label, width.saturating_sub(4) as usize)
            ))
            .style(style),
            button,
        );
        app.hitboxes.push(Hitbox {
            rect: button,
            action: action.clone(),
        });
        x = x.saturating_add(width + 1);
    }
}

fn action_bar_height(width: u16, actions: &[(&str, UiAction)]) -> u16 {
    let usable = width.saturating_sub(2).max(1);
    let mut rows: u16 = if actions.is_empty() { 0 } else { 1 };
    let mut used = 0u16;
    for (label, _) in actions {
        let button_width = (label.chars().count() as u16 + 4).min(usable).max(1);
        if used > 0 && used.saturating_add(button_width) > usable {
            rows = rows.saturating_add(1);
            used = 0;
        }
        used = used.saturating_add(button_width.saturating_add(1));
    }
    // One row is the top border; the remaining rows contain buttons.
    rows.saturating_add(1).max(2)
}

fn render_modal(frame: &mut Frame, app: &mut App, area: Rect) {
    let c = app.colors;
    let Some(modal) = &app.modal else {
        return;
    };
    let rect = centered(
        area,
        76,
        match modal {
            Modal::ProviderEditor { .. } => 24,
            Modal::Palette { .. } => 20,
            Modal::FieldPicker { field_indices, .. } => (field_indices.len() as u16 + 6).min(24),
            Modal::Choice { options, .. } => (options.len() as u16 + 6).min(22),
            _ => 14,
        },
    );
    frame.render_widget(Clear, rect);
    frame.render_widget(Block::default().style(Style::default().bg(c.panel)), rect);
    match modal {
        Modal::EditField { field, input } => {
            render_edit_modal(frame, app.colors, rect, field, input)
        }
        Modal::Choice {
            label,
            options,
            selected,
            ..
        } => render_choice_modal(frame, app.colors, rect, label, options, *selected),
        Modal::FieldPicker {
            title,
            field_indices,
            selected,
        } => render_field_picker(
            frame,
            app.colors,
            app,
            rect,
            title,
            field_indices,
            *selected,
        ),
        Modal::ProviderEditor {
            existing_id,
            draft,
            selected,
            editing,
        } => render_provider_editor(
            frame,
            app.colors,
            rect,
            existing_id.as_deref(),
            draft,
            *selected,
            editing.as_ref(),
        ),
        Modal::SearchModels { input } => render_simple_input(
            frame,
            app.colors,
            rect,
            "Search models",
            input,
            "Enter filters · Esc cancels",
        ),
        Modal::OpenRepo { input } => render_simple_input(
            frame,
            app.colors,
            rect,
            "Open repository",
            input,
            "Enter uses that GitHub checkout for the next launch · Esc cancels",
        ),
        Modal::SearchFiles { input } => render_simple_input(
            frame,
            app.colors,
            rect,
            "Search files",
            input,
            "Enter searches workspace · Esc cancels",
        ),
        Modal::FindInFile { input } => render_simple_input(
            frame,
            app.colors,
            rect,
            "Find in file",
            input,
            "Enter jumps to next match · Esc cancels",
        ),
        Modal::Palette { input, selected } => {
            render_palette(frame, app, rect, &input.value, *selected)
        }
        Modal::Confirm { title, body, .. } => render_message_box(
            frame,
            app.colors,
            rect,
            title,
            &format!("{body}\n\nEnter/Y confirms · Esc/N cancels"),
            c.warn,
        ),
        Modal::Message { title, body } => {
            render_message_box(frame, app.colors, rect, title, body, c.text)
        }
    }
    register_modal_hitboxes(app, rect);
}

fn register_modal_hitboxes(app: &mut App, rect: Rect) {
    let c = app.colors;
    let Some(modal) = app.modal.as_ref() else {
        return;
    };
    match modal {
        Modal::Choice {
            label,
            options,
            selected,
            ..
        } => {
            let block_title = format!("{label}  {}", list_position(*selected, options.len()));
            let block = modal_block(c, &block_title);
            let inner = block.inner(rect);
            let height = inner.height.saturating_sub(2) as usize;
            let offset = list_offset(*selected, options.len(), height);
            for (visible, _) in options.iter().enumerate().skip(offset).take(height) {
                app.hitboxes.push(Hitbox {
                    rect: Rect {
                        x: inner.x,
                        y: inner.y + (visible - offset) as u16,
                        width: inner.width,
                        height: 1,
                    },
                    action: UiAction::ModalActivate(visible),
                });
            }
        }
        Modal::FieldPicker {
            title,
            field_indices,
            selected,
        } => {
            let block_title = format!("{title}  {}", list_position(*selected, field_indices.len()));
            let block = modal_block(c, &block_title);
            let inner = block.inner(rect);
            let height = inner.height.saturating_sub(2) as usize;
            let offset = list_offset(*selected, field_indices.len(), height);
            for (visible, _) in field_indices.iter().enumerate().skip(offset).take(height) {
                app.hitboxes.push(Hitbox {
                    rect: Rect {
                        x: inner.x,
                        y: inner.y + (visible - offset) as u16,
                        width: inner.width,
                        height: 1,
                    },
                    action: UiAction::ModalActivate(visible),
                });
            }
        }
        Modal::ProviderEditor { .. } => {
            let inner = modal_block(c, "Edit custom provider").inner(rect);
            for index in 0..8usize {
                app.hitboxes.push(Hitbox {
                    rect: Rect {
                        x: inner.x,
                        y: inner.y + index as u16,
                        width: inner.width,
                        height: 1,
                    },
                    action: UiAction::ModalSelect(index),
                });
            }
        }
        Modal::Palette {
            input, selected, ..
        } => {
            let inner = modal_block(c, "Command palette").inner(rect);
            let inventory = app.palette_inventory();
            let visible = match_palette(&input.value, &inventory);
            let rows = inner.height.saturating_sub(5) as usize;
            let offset = list_offset(*selected, visible.len(), rows);
            for (row, _) in visible.iter().skip(offset).take(rows).enumerate() {
                app.hitboxes.push(Hitbox {
                    rect: Rect {
                        x: inner.x,
                        y: inner.y + 4 + row as u16,
                        width: inner.width,
                        height: 1,
                    },
                    action: UiAction::ModalActivate(offset + row),
                });
            }
        }
        _ => {}
    }
}

fn render_edit_modal(
    frame: &mut Frame,
    c: Colors,
    rect: Rect,
    field: &ConfigField,
    input: &crate::app::TextInput,
) {
    let block = modal_block(c, &field.label);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    let shown = input_display(input);
    let hint = if input.multiline {
        "Ctrl-Enter saves · Enter newline · Esc cancels"
    } else if field.secret && field.configured {
        "Type a replacement key · blank + Enter preserves · Esc cancels"
    } else {
        "Enter saves · Esc cancels"
    };
    frame.render_widget(
        Paragraph::new(shown)
            .style(Style::default().fg(c.text).bg(c.bg))
            .wrap(Wrap { trim: false })
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(c.accent)),
            ),
        Rect {
            x: inner.x,
            y: inner.y + 1,
            width: inner.width,
            height: inner.height.saturating_sub(4),
        },
    );
    frame.render_widget(
        Paragraph::new(hint).style(Style::default().fg(c.muted)),
        Rect {
            x: inner.x,
            y: inner.bottom().saturating_sub(2),
            width: inner.width,
            height: 2,
        },
    );
}

fn render_simple_input(
    frame: &mut Frame,
    c: Colors,
    rect: Rect,
    title: &str,
    input: &crate::app::TextInput,
    hint: &str,
) {
    let block = modal_block(c, title);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    frame.render_widget(
        Paragraph::new(input_display(input))
            .style(Style::default().fg(c.text).bg(c.bg))
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(c.accent)),
            ),
        Rect {
            x: inner.x,
            y: inner.y + 2,
            width: inner.width,
            height: 3,
        },
    );
    frame.render_widget(
        Paragraph::new(hint).style(Style::default().fg(c.muted)),
        Rect {
            x: inner.x,
            y: inner.y + 6,
            width: inner.width,
            height: 2,
        },
    );
}

fn render_palette(frame: &mut Frame, app: &App, rect: Rect, query: &str, selected: usize) {
    let c = app.colors;
    let block = modal_block(c, "Command palette");
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    if inner.height < 4 || inner.width < 8 {
        return;
    }
    frame.render_widget(
        Paragraph::new(format!("❯ {query}"))
            .style(Style::default().fg(c.text).bg(c.bg))
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(c.accent)),
            ),
        Rect {
            x: inner.x,
            y: inner.y,
            width: inner.width,
            height: 3,
        },
    );
    let inventory = app.palette_inventory();
    let visible = match_palette(query, &inventory);
    let rows = (inner.height.saturating_sub(5)) as usize;
    if visible.is_empty() {
        frame.render_widget(
            Paragraph::new("No matching command").style(Style::default().fg(c.muted)),
            Rect {
                x: inner.x,
                y: inner.y + 4,
                width: inner.width,
                height: 1,
            },
        );
    }
    let offset = if rows == 0 || visible.len() <= rows {
        0
    } else {
        selected
            .min(visible.len() - 1)
            .saturating_sub(rows / 2)
            .min(visible.len().saturating_sub(rows))
    };
    for (row, entry_index) in visible.iter().skip(offset).take(rows).enumerate() {
        let display = offset + row;
        let Some(entry) = inventory.get(*entry_index) else {
            continue;
        };
        let y = inner.y + 4 + row as u16;
        let area = Rect {
            x: inner.x,
            y,
            width: inner.width,
            height: 1,
        };
        let style = if display == selected.min(visible.len().saturating_sub(1)) {
            Style::default()
                .fg(c.text)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(c.text)
        };
        let marker = if display == selected.min(visible.len().saturating_sub(1)) {
            "▌ "
        } else {
            "  "
        };
        let hint_width = (inner.width as usize / 3).max(10);
        let title_width = inner.width.saturating_sub(hint_width as u16 + 4) as usize;
        frame.render_widget(
            Paragraph::new(format!(
                "{}{:title_width$}  {}",
                marker,
                trim_to(&entry.title, title_width),
                trim_to(&entry.hint, hint_width),
                title_width = title_width
            ))
            .style(style),
            area,
        );
    }
    frame.render_widget(
        Paragraph::new("Type to filter · ↑↓ move · Enter runs · Esc closes")
            .style(Style::default().fg(c.muted)),
        Rect {
            x: inner.x,
            y: inner.bottom().saturating_sub(1),
            width: inner.width,
            height: 1,
        },
    );
}

fn render_choice_modal(
    frame: &mut Frame,
    c: Colors,
    rect: Rect,
    title: &str,
    options: &[crate::api::ConfigOption],
    selected: usize,
) {
    let title = format!("{title}  {}", list_position(selected, options.len()));
    let block = modal_block(c, &title);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    let height = inner.height.saturating_sub(2) as usize;
    let offset = list_offset(selected, options.len(), height);
    for (index, option) in options.iter().enumerate().skip(offset).take(height) {
        let visible = index - offset;
        let row = Rect {
            x: inner.x,
            y: inner.y + visible as u16,
            width: inner.width,
            height: 1,
        };
        let style = if index == selected {
            Style::default()
                .fg(c.text)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(c.text)
        };
        frame.render_widget(
            Paragraph::new(format!(
                "{}{}",
                if index == selected { "▌ " } else { "  " },
                option.label
            ))
            .style(style),
            row,
        );
    }
}

fn render_field_picker(
    frame: &mut Frame,
    c: Colors,
    app: &App,
    rect: Rect,
    title: &str,
    indices: &[usize],
    selected: usize,
) {
    let title = format!("{title}  {}", list_position(selected, indices.len()));
    let block = modal_block(c, &title);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    let height = inner.height.saturating_sub(2) as usize;
    let offset = list_offset(selected, indices.len(), height);
    for (visible, index) in indices.iter().enumerate().skip(offset).take(height) {
        let selected_index = offset + visible;
        let Some(field) = app.config.fields.get(*index) else {
            continue;
        };
        let row = Rect {
            x: inner.x,
            y: inner.y + (selected_index - offset) as u16,
            width: inner.width,
            height: 1,
        };
        let style = if selected_index == selected {
            Style::default()
                .fg(c.text)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(c.text)
        };
        frame.render_widget(
            Paragraph::new(format!(
                "{}{:30}  {}",
                if selected_index == selected {
                    "▌ "
                } else {
                    "  "
                },
                trim_to(&field.label, 30),
                trim_to(&App::display_field_value(field), 30)
            ))
            .style(style),
            row,
        );
    }
}

fn render_provider_editor(
    frame: &mut Frame,
    c: Colors,
    rect: Rect,
    existing_id: Option<&str>,
    draft: &crate::app::ProviderDraft,
    selected: usize,
    editing: Option<&crate::app::TextInput>,
) {
    let title = if existing_id.is_some() {
        "Edit custom provider"
    } else {
        "New custom provider"
    };
    let block = modal_block(c, title);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    for index in 0..8usize {
        let row = Rect {
            x: inner.x,
            y: inner.y + index as u16,
            width: inner.width,
            height: 1,
        };
        let style = if index == selected {
            Style::default()
                .fg(c.text)
                .bg(c.accent_dim)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(c.text)
        };
        frame.render_widget(
            Paragraph::new(format!(
                "{}{:18}  {}",
                if index == selected { "▌ " } else { "  " },
                crate::app::ProviderDraft::field_label(index),
                trim_to(&draft.field_value(index), 46)
            ))
            .style(style),
            row,
        );
    }
    let hint_y = inner.y + 10;
    frame.render_widget(
        Paragraph::new("↑↓ field · Enter edit · Space boolean · Ctrl-S save · Esc cancel")
            .style(Style::default().fg(c.muted)),
        Rect {
            x: inner.x,
            y: hint_y,
            width: inner.width,
            height: 2,
        },
    );
    if let Some(input) = editing {
        let shown = input_display(input);
        frame.render_widget(
            Paragraph::new(shown)
                .wrap(Wrap { trim: false })
                .style(Style::default().fg(c.text).bg(c.bg))
                .block(
                    Block::default()
                        .title(" Edit value ")
                        .borders(Borders::ALL)
                        .border_style(Style::default().fg(c.accent)),
                ),
            Rect {
                x: inner.x,
                y: hint_y + 3,
                width: inner.width,
                height: inner.bottom().saturating_sub(hint_y + 3),
            },
        );
    } else if existing_id.is_some() && draft.existing_has_key {
        frame.render_widget(Paragraph::new("API key is configured but never returned by FCC. Leave API key blank to preserve it.").style(Style::default().fg(c.warn)).wrap(Wrap { trim: true }), Rect { x: inner.x, y: hint_y + 3, width: inner.width, height: 3 });
    }
}

fn render_message_box(
    frame: &mut Frame,
    c: Colors,
    rect: Rect,
    title: &str,
    body: &str,
    color: Color,
) {
    let block = modal_block(c, title);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    frame.render_widget(
        Paragraph::new(body.to_string())
            .style(Style::default().fg(color))
            .wrap(Wrap { trim: true }),
        inner,
    );
}

fn section_block(c: Colors, title: &str) -> Block<'_> {
    Block::default()
        .title(Span::styled(
            format!(" {title} "),
            Style::default().fg(c.muted).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(c.border))
        .style(Style::default().bg(c.bg))
}

fn modal_block(c: Colors, title: &str) -> Block<'_> {
    Block::default()
        .title(Span::styled(
            format!(" {title} "),
            Style::default().fg(c.text).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(c.accent))
        .style(Style::default().bg(c.panel))
}

fn bottom_border(c: Colors) -> Block<'static> {
    Block::default()
        .borders(Borders::BOTTOM)
        .border_style(Style::default().fg(c.border))
        .style(Style::default().bg(c.panel))
}

fn kv(c: Colors, label: &str, value: &str) -> Line<'static> {
    styled_kv(c, label, value, Style::default().fg(c.text))
}

fn compact_kv(
    c: Colors,
    label: &str,
    value: &str,
    width: usize,
    value_style: Style,
) -> Line<'static> {
    let prefix = format!("{label}: ");
    let value_width = width.saturating_sub(prefix.chars().count()).max(1);
    Line::from(vec![
        Span::styled(prefix, Style::default().fg(c.muted)),
        Span::styled(trim_to(value, value_width), value_style),
    ])
}

fn styled_kv(c: Colors, label: &str, value: &str, value_style: Style) -> Line<'static> {
    Line::from(vec![
        Span::styled(format!("{label:<16}"), Style::default().fg(c.muted)),
        Span::styled(value.to_string(), value_style),
    ])
}

fn provider_color(c: Colors, status: &str) -> Color {
    match status.trim().to_ascii_lowercase().as_str() {
        "configured" | "reachable" | "connected" => c.good,
        "connecting" => c.warn,
        "missing_key" | "missing_config" | "missing_url" | "unknown" => c.warn,
        "offline" | "invalid_config" | "error" => c.bad,
        "disabled" | "disconnected" => c.muted,
        _ => c.muted,
    }
}

fn centered(area: Rect, width: u16, height: u16) -> Rect {
    let width = width
        .min(area.width.saturating_sub(4))
        .max(20.min(area.width));
    let height = height
        .min(area.height.saturating_sub(2))
        .max(6.min(area.height));
    Rect {
        x: area.x + area.width.saturating_sub(width) / 2,
        y: area.y + area.height.saturating_sub(height) / 2,
        width,
        height,
    }
}

fn list_offset(selected: usize, len: usize, height: usize) -> usize {
    if height == 0 || len <= height {
        return 0;
    }
    selected
        .saturating_sub(height / 2)
        .min(len.saturating_sub(height))
}

fn list_position(selected: usize, len: usize) -> String {
    if len == 0 {
        "0/0".to_string()
    } else {
        format!("{}/{}", selected.min(len - 1) + 1, len)
    }
}

fn contains(rect: Rect, x: u16, y: u16) -> bool {
    x >= rect.x && x < rect.right() && y >= rect.y && y < rect.bottom()
}

fn trim_to(value: &str, max: usize) -> String {
    if max == 0 {
        return String::new();
    }
    if value.chars().count() <= max {
        return value.to_string();
    }
    if max == 1 {
        return "…".to_string();
    }
    format!("{}…", value.chars().take(max - 1).collect::<String>())
}

fn input_display(input: &TextInput) -> String {
    let mut cursor = input.cursor.min(input.value.len());
    while cursor > 0 && !input.value.is_char_boundary(cursor) {
        cursor -= 1;
    }
    let (before, after) = input.value.split_at(cursor);
    if input.secret {
        format!(
            "{}▌{}",
            "•".repeat(before.chars().count()),
            "•".repeat(after.chars().count())
        )
    } else {
        format!("{before}▌{after}")
    }
}

fn format_tokens(value: &str) -> String {
    let normalized = value.replace(',', "");
    match normalized.parse::<u64>() {
        Ok(tokens) if tokens >= 1_000_000 => format!("{:.2}M", tokens as f64 / 1_000_000.0),
        Ok(tokens) if tokens >= 1_000 => format!("{}K", tokens / 1_000),
        Ok(tokens) => tokens.to_string(),
        Err(_) => value.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::{
        ConfigField, ConfigOption, CustomProvider, ModelsResponse, ProviderStatus, MASKED_SECRET,
    };
    use crate::app::{ConfirmAction, ProviderDraft, TextInput, CONTEXT_KEY};
    use crossterm::event::{Event, KeyModifiers, MouseButton, MouseEvent, MouseEventKind};
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;

    #[test]
    fn desktop_geometry_is_cell_exact_at_reference_viewport() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.top.height, 3);
        assert_eq!(app.geometry.sidebar.width, 30);
        assert_eq!(app.geometry.footer.height, 1);
        assert_eq!(app.geometry.tabs.height, 0);
        assert_eq!(app.geometry.gutter.width, 0);
        assert_eq!(app.geometry.main.width, 130);
    }

    #[test]
    fn context_page_keeps_same_desktop_shell() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.page = Page::Context;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.sidebar.width, 30);
        assert_eq!(app.geometry.top.height, 3);
        assert_eq!(app.geometry.footer.height, 1);
    }

    #[test]
    fn every_page_and_modal_renders_at_reference_and_compact_sizes() {
        let mut app = App::fixture();
        app.config.fields = vec![
            ConfigField {
                key: "MODEL".to_string(),
                label: "Default model".to_string(),
                field_type: "text".to_string(),
                value: "open_router/openrouter/free".to_string(),
                configured: true,
                source: "managed_env".to_string(),
                description: "Default route".to_string(),
                ..ConfigField::default()
            },
            ConfigField {
                key: CONTEXT_KEY.to_string(),
                label: "Context window".to_string(),
                field_type: "number".to_string(),
                value: "256000".to_string(),
                configured: true,
                source: "managed_env".to_string(),
                description: "Session context".to_string(),
                ..ConfigField::default()
            },
            ConfigField {
                key: "OPENROUTER_API_KEY".to_string(),
                label: "OpenRouter API key".to_string(),
                field_type: "secret".to_string(),
                value: MASKED_SECRET.to_string(),
                configured: true,
                secret: true,
                source: "managed_env".to_string(),
                description: "Provider credential".to_string(),
                ..ConfigField::default()
            },
        ];
        app.config.provider_status = vec![ProviderStatus {
            provider_id: "open_router".to_string(),
            display_name: "OpenRouter".to_string(),
            kind: "api_key".to_string(),
            status: "configured".to_string(),
            label: "Configured".to_string(),
            configuration: "OPENROUTER_API_KEY".to_string(),
            api_key_configured: Some(true),
            proxy_configured: Some(false),
            ..ProviderStatus::default()
        }];
        app.models = ModelsResponse {
            models: vec!["open_router/openrouter/free".to_string()],
            catalog_models: vec!["open_router/openrouter/free".to_string()],
            model_labels: [(
                "open_router/openrouter/free".to_string(),
                "OpenRouter · Free".to_string(),
            )]
            .into_iter()
            .collect(),
            catalog_model_labels: [(
                "open_router/openrouter/free".to_string(),
                "OpenRouter · Free".to_string(),
            )]
            .into_iter()
            .collect(),
            ..ModelsResponse::default()
        };
        app.custom_providers = vec![CustomProvider {
            provider_id: "lab".to_string(),
            display_name: "Local Lab".to_string(),
            base_url: "http://127.0.0.1:1234/v1".to_string(),
            local: true,
            enabled: true,
            api_key_configured: true,
            proxy_configured: true,
            model_ids: vec!["lab/model".to_string()],
        }];

        for page in Page::ALL {
            app.page = page;
            app.modal = None;
            for (width, height) in [(160, 50), (80, 24)] {
                let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
                terminal.draw(|frame| render(frame, &mut app)).unwrap();
            }
        }

        let field = app.config.fields[2].clone();
        let modals = vec![
            Modal::EditField {
                field: field.clone(),
                input: TextInput::new("replacement".to_string(), false, true),
            },
            Modal::Choice {
                key: "MODEL".to_string(),
                label: "Default model".to_string(),
                options: vec![ConfigOption {
                    value: "open_router/openrouter/free".to_string(),
                    label: "OpenRouter · Free".to_string(),
                }],
                selected: 0,
            },
            Modal::FieldPicker {
                title: "Configure OpenRouter".to_string(),
                field_indices: vec![2],
                selected: 0,
            },
            Modal::ProviderEditor {
                existing_id: Some("lab".to_string()),
                draft: ProviderDraft {
                    id: "lab".to_string(),
                    display_name: "Local Lab".to_string(),
                    base_url: "http://127.0.0.1:1234/v1".to_string(),
                    api_key: String::new(),
                    proxy: String::new(),
                    models: "lab/model".to_string(),
                    local: true,
                    enabled: true,
                    existing_has_key: true,
                    existing_has_proxy: true,
                },
                selected: 3,
                editing: Some(TextInput::new("replacement".to_string(), false, true)),
            },
            Modal::SearchModels {
                input: TextInput::new("free".to_string(), false, false),
            },
            Modal::Palette {
                input: TextInput::new("model".to_string(), false, false),
                selected: 1,
            },
            Modal::Confirm {
                title: "Clear secret".to_string(),
                body: "Clear OpenRouter API key?".to_string(),
                action: ConfirmAction::ClearField("OPENROUTER_API_KEY".to_string()),
            },
            Modal::Message {
                title: "Provider test".to_string(),
                body: "{\"ok\":true}".to_string(),
            },
        ];
        app.page = Page::Providers;
        for modal in modals {
            app.modal = Some(modal);
            for (width, height) in [(160, 50), (80, 24)] {
                let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
                terminal.draw(|frame| render(frame, &mut app)).unwrap();
            }
        }
    }

    fn buffer_text(terminal: &Terminal<TestBackend>) -> String {
        terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol().to_owned())
            .collect()
    }

    #[test]
    fn control_center_chrome_geometry_with_panel_open() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.panel_open = true;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.tabs.height, 0);
        assert_eq!(app.geometry.gutter.width, 0);
        assert_eq!(app.geometry.sidebar.width, 30);
        assert_eq!(app.geometry.editor.width, 130);
        assert_eq!(app.geometry.panel.height, 7);
        assert_eq!(app.geometry.statusbar.height, 1);
        assert_eq!(app.geometry.footer.height, 1);
        assert!(!app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(&hitbox.action, UiAction::ActivateTab(_))));
        let text = buffer_text(&terminal);
        assert!(text.contains("FCC STATUS"));
        assert!(text.contains("FCC LOCAL"));
    }

    #[test]
    fn control_center_shell_has_no_editor_chrome_or_activity_rail() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.activity = Activity::Explorer;
        app.page = Page::Dashboard;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let text = buffer_text(&terminal);
        assert_eq!(app.geometry.tabs.width, 0);
        assert_eq!(app.geometry.gutter.width, 0);
        assert_eq!(app.geometry.main.width, 130);
        assert!(text.contains("CONTROL"));
        assert!(text.contains("CENTER"));
        assert!(text.contains("Dashboard"));
        assert!(text.contains("Providers"));
        assert!(text.contains("Models"));
        assert!(text.contains("Routing"));
        assert!(!text.contains("Explorer"));
        assert!(!text.contains("Source Control"));
        assert!(!text.contains("Search files"));
        assert!(!text.contains("●  ●  ●"));
        assert!(!app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(&hitbox.action, UiAction::Activity(_))));
        assert!(!app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(&hitbox.action, UiAction::ActivateTab(_))));
    }

    #[test]
    fn sidebar_focus_has_a_distinct_selected_surface() {
        let mut terminal = Terminal::new(TestBackend::new(160, 50)).unwrap();
        let mut app = App::fixture();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let row = (app.geometry.sidebar.x + 2, app.geometry.sidebar.y + 4);
        let editor_focused = terminal
            .backend()
            .buffer()
            .cell(row)
            .expect("selected sidebar row exists")
            .style()
            .bg;

        app.focus = Focus::Sidebar;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let sidebar_focused = terminal
            .backend()
            .buffer()
            .cell(row)
            .expect("selected sidebar row exists")
            .style()
            .bg;
        assert_ne!(editor_focused, sidebar_focused);
    }

    #[test]
    fn page_navigation_owns_sidebar_keyboard_focus() {
        use crossterm::event::{Event, KeyCode, KeyEvent, KeyModifiers};

        let mut app = App::fixture();
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('0'),
            KeyModifiers::CONTROL,
        )))
        .unwrap();
        app.move_focused(2);
        assert_eq!(app.page, Page::Repositories);
        assert_eq!(app.sidebar_cursor, 2);
        app.move_focused(1);
        assert_eq!(app.page, Page::Models);
        assert_eq!(app.sidebar_cursor, 3);
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert_eq!(app.focus, Focus::Editor);
        assert_eq!(app.editor_focus, EditorFocus::Page);
    }

    #[test]
    fn dashboard_surface_is_concrete_and_actionable() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.status = serde_json::json!({
            "status": "running",
            "host": "127.0.0.1",
            "port": 8082,
            "model": "bai/active"
        });
        app.config.fields.extend([
            ConfigField {
                key: "MODEL".to_string(),
                value: "cline/z-ai/glm-5.3-flash".to_string(),
                ..ConfigField::default()
            },
            ConfigField {
                key: "MODEL_CATALOG_MODE".to_string(),
                value: "curated".to_string(),
                ..ConfigField::default()
            },
            ConfigField {
                key: "MODEL_CATALOG_ALLOWLIST".to_string(),
                value: "bai/active, cline/z-ai/glm-5.3-flash".to_string(),
                ..ConfigField::default()
            },
        ]);
        app.models.models = vec!["bai/active".to_string()];
        app.models.catalog_models = vec![
            "bai/active".to_string(),
            "cline/z-ai/glm-5.3-flash".to_string(),
        ];
        app.models.catalog_model_evidence.insert(
            "bai/active".to_string(),
            serde_json::json!({"is_free": true}),
        );
        app.config.provider_status = vec![
            ProviderStatus {
                provider_id: "bai".to_string(),
                display_name: "B.AI".to_string(),
                status: "configured".to_string(),
                ..ProviderStatus::default()
            },
            ProviderStatus {
                provider_id: "cline".to_string(),
                display_name: "Cline".to_string(),
                status: "missing_key".to_string(),
                ..ProviderStatus::default()
            },
        ];
        app.git_branch = "feat/dashboard".to_string();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let text = buffer_text(&terminal);
        for title in [
            "SERVER",
            "LAUNCH ROUTE",
            "MODELS",
            "PROVIDERS",
            "POLICY",
            "WORKSPACE",
        ] {
            assert!(text.contains(title), "dashboard missing {title}");
        }
        assert!(text.contains("cline/z-ai/glm-5.3-flash"));
        assert!(text.contains("bai/active"));
        assert!(text.contains("Claude normal"));
        assert!(text.contains("Claude danger"));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| { matches!(&hitbox.action, &UiAction::LaunchClaude(false)) }));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| { matches!(&hitbox.action, &UiAction::LaunchClaude(true)) }));
        assert!(!text.contains("thin client"));
        assert!(!text.contains("canonical loopback Admin API"));
    }

    #[test]
    fn models_surface_exposes_filters_without_routing_or_price_noise() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["bai/free-model".to_string()];
        app.models.catalog_models =
            vec!["bai/free-model".to_string(), "bai/paid-model".to_string()];
        app.models.catalog_model_evidence.insert(
            "bai/free-model".to_string(),
            serde_json::json!({"is_free": true}),
        );
        app.models.catalog_model_evidence.insert(
            "bai/paid-model".to_string(),
            serde_json::json!({"is_free": false}),
        );
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let text = buffer_text(&terminal);
        assert!(text.contains("Provider: All ·"));
        assert!(text.contains("Free: OFF"));
        assert!(text.contains("View: Catalog"));
        assert!(text.contains("Enter sets MODEL"));
        assert!(text.contains("Space/click on-off"));
        assert!(!text.contains("Set MODEL"));
        assert!(text.contains("FREE"));
        // The exact route rides in the row: no inspector pane is needed.
        assert!(text.contains("bai/paid-model"));
        assert!(!text.contains("Model inspector"));
        // Free rows sort before paid rows in the same list.
        let free_pos = text.find("FREE").expect("free badge renders");
        let paid_pos = text.find("bai/paid-model").expect("paid row renders");
        assert!(free_pos < paid_pos);
        assert!(!text.contains("MODEL CATALOG"));
        assert!(!text.contains("Routing shortcuts"));
        assert!(!text.contains("(policy)"));
        assert!(!text.contains("PRICE?"));
        assert!(!text.contains(" PAID"));
        assert!(!text.contains("Toggle selected"));
        assert!(!text.contains("Toggle"));
        assert!(!text.contains("[S]"));
        assert!(!text.contains("? help"));
        assert!(!text.contains("Keyboard shortcuts"));
    }

    #[test]
    fn models_header_counts_agree_with_the_visible_rows() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["bai/free-model".to_string()];
        app.models.catalog_models =
            vec!["bai/free-model".to_string(), "bai/paid-model".to_string()];
        app.models.catalog_model_evidence.insert(
            "bai/free-model".to_string(),
            serde_json::json!({"is_free": true}),
        );
        app.models.catalog_model_evidence.insert(
            "bai/paid-model".to_string(),
            serde_json::json!({"is_free": false}),
        );
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let text = buffer_text(&terminal);
        assert!(text.contains("2 shown · 1 on · 2 catalog · 1 free"));
        assert!(text.contains("Models · 1/2"));
        assert!(text.contains("Space/click on-off"));
    }

    #[test]
    fn compact_models_page_keeps_every_primary_action_reachable() {
        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["bai/free-model".to_string()];
        // Catalog is the default view: both the full inventory and the
        // `V` key that narrows it work without any prior toggle.
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let text = buffer_text(&terminal);
        assert!(text.contains("View:"));
        assert!(text.contains("View: Catalog"));
        app.model_show_catalog = false;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let text = buffer_text(&terminal);
        assert!(text.contains("View: Active only"));
        let actions = app
            .hitboxes
            .iter()
            .filter_map(|hitbox| match &hitbox.action {
                UiAction::SearchModels
                | UiAction::ChooseModelProvider
                | UiAction::CycleModelPrice
                | UiAction::DisableAllModels
                | UiAction::Refresh => Some(&hitbox.action),
                _ => None,
            })
            .count();
        assert_eq!(actions, 5);
    }

    #[test]
    fn repositories_page_uses_a_checkout_with_one_tap() {
        use crate::app::RepoEntry;
        use std::path::PathBuf;

        let mut app = App::fixture();
        app.page = Page::Repositories;
        app.repos = vec![
            RepoEntry {
                name: "alpha".to_string(),
                path: PathBuf::from("/tmp/alpha"),
                branch: "main".to_string(),
                remote: "acme/alpha".to_string(),
            },
            RepoEntry {
                name: "beta".to_string(),
                path: PathBuf::from("/tmp/beta"),
                branch: "dev".to_string(),
                remote: "acme/beta".to_string(),
            },
        ];
        app.repos_scanned = true;
        for (width, height) in [(160, 50), (80, 24)] {
            let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal.draw(|frame| render(frame, &mut app)).unwrap();
            let text = buffer_text(&terminal);
            assert!(
                text.contains("Repositories"),
                "missing title at {width}x{height}"
            );
            assert!(
                text.contains("acme/alpha"),
                "missing row at {width}x{height}"
            );
            assert!(
                text.contains("Use for launch"),
                "missing action at {width}x{height}"
            );
            assert!(
                !text.contains("Model inspector"),
                "no model chrome at {width}x{height}"
            );
        }
        let rect = app
            .hitboxes
            .iter()
            .find_map(|hitbox| match &hitbox.action {
                UiAction::UseRepo(1) => Some(hitbox.rect),
                _ => None,
            })
            .expect("second repo row should have a use hitbox");
        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::NONE,
        }))
        .unwrap();
        assert_eq!(app.launch_repo, Some(PathBuf::from("/tmp/beta")));
        assert_eq!(app.launch_repo_name(), "beta");
    }

    #[test]
    fn provider_rows_select_with_one_tap_without_side_effects() {
        let mut app = App::fixture();
        app.page = Page::Providers;
        app.config.provider_status = vec![ProviderStatus {
            provider_id: "lab".to_string(),
            display_name: "Lab".to_string(),
            kind: "custom".to_string(),
            status: "configured".to_string(),
            label: "Configured".to_string(),
            custom: true,
            ..ProviderStatus::default()
        }];
        app.custom_providers = vec![CustomProvider {
            provider_id: "lab".to_string(),
            display_name: "Lab".to_string(),
            base_url: "https://example.invalid/v1".to_string(),
            enabled: true,
            ..CustomProvider::default()
        }];
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let rect = app
            .hitboxes
            .iter()
            .find_map(|hitbox| match &hitbox.action {
                UiAction::SelectProvider(0) => Some(hitbox.rect),
                _ => None,
            })
            .expect("provider row should have an open hitbox");
        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::NONE,
        }))
        .unwrap();
        assert_eq!(app.provider_selected, 0);
        assert!(app.modal.is_none());
    }

    #[test]
    fn connected_provider_tap_does_not_start_oauth() {
        let mut app = App::fixture();
        app.page = Page::Providers;
        app.config.provider_status = vec![ProviderStatus {
            provider_id: "openai".to_string(),
            display_name: "OpenAI / ChatGPT".to_string(),
            kind: "connected_account".to_string(),
            status: "connected".to_string(),
            label: "Connected".to_string(),
            ..ProviderStatus::default()
        }];
        let mut terminal = Terminal::new(TestBackend::new(120, 32)).unwrap();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let rect = app
            .hitboxes
            .iter()
            .find_map(|hitbox| match &hitbox.action {
                UiAction::SelectProvider(0) => Some(hitbox.rect),
                _ => None,
            })
            .expect("connected provider row should have a select hitbox");

        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::NONE,
        }))
        .unwrap();

        assert!(app.modal.is_none());
        assert!(app.notice.is_none());
        assert_eq!(app.provider_selected, 0);
    }

    #[test]
    fn explicit_file_viewer_has_no_tab_strip() {
        let dir = std::env::temp_dir().join(format!("fcc-ui-viewer-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("notes.md"), "hello viewer\nsecond line\n").unwrap();
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.set_workspace(dir.clone());
        app.run_search("hello");
        app.open_search_hit(0);
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let text = buffer_text(&terminal);
        assert!(text.contains("notes.md"));
        assert!(text.contains('1'));
        assert!(text.contains("hello viewer"));
        assert!(text.contains("Ln 1/2"));
        assert!(!text.contains(" x "));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn compact_viewport_renders_control_center_with_panel() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.panel_open = true;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.footer.height, 1);
        assert_eq!(app.geometry.statusbar.height, 1);
        assert_eq!(app.geometry.gutter.width, 0);
    }

    #[test]
    fn compact_viewport_keeps_the_finite_page_inventory_visible() {
        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        let mut app = App::fixture();
        app.focus = Focus::Sidebar;
        app.sidebar_cursor = Page::ALL.len() - 1;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let text = buffer_text(&terminal);
        for page in Page::ALL {
            assert!(text.contains(page.label()), "missing page {}", page.label());
        }
        assert!(text.contains("Diagnostics"));
    }

    #[test]
    fn very_small_viewport_still_renders_without_panicking() {
        let mut app = App::fixture();
        for page in Page::ALL {
            app.page = page;
            let mut terminal = Terminal::new(TestBackend::new(40, 12)).unwrap();
            terminal.draw(|frame| render(frame, &mut app)).unwrap();
        }
    }

    #[test]
    fn long_output_renders_a_bounded_position_indicator() {
        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        let mut app = App::fixture();
        app.page = Page::Usage;
        app.usage = serde_json::json!({
            "entries": (0..30).map(|index| serde_json::json!({"index": index})).collect::<Vec<_>>()
        });
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let first = buffer_text(&terminal);
        assert!(first.contains("lines 1–"));
        app.content_scroll = 10;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let later = buffer_text(&terminal);
        assert!(later.contains("lines 11–"));
    }

    #[test]
    fn modal_list_rows_accept_mouse_selection_without_clicking_through() {
        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        let mut app = App::fixture();
        app.page = Page::Models;
        app.modal = Some(Modal::Choice {
            key: "__FCC_MODEL_PROVIDER__".to_string(),
            label: "Choose setting".to_string(),
            options: vec![
                ConfigOption {
                    value: "one".to_string(),
                    label: "One".to_string(),
                },
                ConfigOption {
                    value: "two".to_string(),
                    label: "Two".to_string(),
                },
            ],
            selected: 0,
        });
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let rect = app
            .hitboxes
            .iter()
            .find_map(|hitbox| match &hitbox.action {
                UiAction::ModalActivate(1) => Some(hitbox.rect),
                _ => None,
            })
            .expect("choice row should have a modal hitbox");
        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::NONE,
        }))
        .unwrap();
        assert!(app.modal.is_none());
        assert_eq!(app.page, Page::Models);
        assert_eq!(app.model_provider_filter, "two");
    }

    #[test]
    fn highlight_line_marks_case_insensitive_matches_without_panics() {
        let base = Style::default();
        let hi = Style::default().add_modifier(Modifier::BOLD);
        let spans = highlight_line("héllo WÖRLD world", "wör", base, hi);
        let joined: String = spans.iter().map(|span| span.content.as_ref()).collect();
        assert_eq!(joined, "héllo WÖRLD world");
        assert_eq!(spans.iter().filter(|span| span.style == hi).count(), 1);
        let plain = highlight_line("nothing here", "", base, hi);
        assert_eq!(plain.len(), 1);
    }

    #[test]
    fn palette_keeps_cell_exact_chrome_at_reference_viewport() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.modal = Some(Modal::Palette {
            input: TextInput::new("provider".to_string(), false, false),
            selected: 0,
        });
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.top.height, 3);
        assert_eq!(app.geometry.sidebar.width, 30);
        assert_eq!(app.geometry.footer.height, 1);
        assert_eq!(app.geometry.gutter.width, 0);
        assert_eq!(app.geometry.main.width, 130);
    }
}
