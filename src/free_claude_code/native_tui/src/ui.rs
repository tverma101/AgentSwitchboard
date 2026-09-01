use crate::api::{ConfigField, ProviderStatus};
use crate::app::{
    pretty, App, ChromeGeometry, Hitbox, Modal, Page, UiAction, CONTEXT_MAX, CONTEXT_MIN,
};
use crate::models::{
    capability_summary, pricing_signal, AccessFilter, ModelSort, PriceFilter, PriceState, MODEL_KEY,
};
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;
use serde_json::Value;

const BG: Color = Color::Rgb(15, 17, 21);
const PANEL: Color = Color::Rgb(22, 25, 31);
const PANEL_2: Color = Color::Rgb(28, 32, 40);
const BORDER: Color = Color::Rgb(53, 59, 72);
const TEXT: Color = Color::Rgb(224, 228, 236);
const MUTED: Color = Color::Rgb(137, 145, 160);
const ACCENT: Color = Color::Rgb(103, 132, 255);
const ACCENT_DIM: Color = Color::Rgb(35, 45, 78);
const GOOD: Color = Color::Rgb(97, 203, 137);
const WARN: Color = Color::Rgb(241, 190, 75);
const BAD: Color = Color::Rgb(239, 101, 101);

pub fn render(frame: &mut Frame, app: &mut App) {
    app.hitboxes.clear();
    let area = frame.area();
    frame.render_widget(Block::default().style(Style::default().bg(BG)), area);

    let vertical = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(12),
            Constraint::Length(2),
        ])
        .split(area);
    let body = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Length(28), Constraint::Min(48)])
        .split(vertical[1]);

    app.geometry = ChromeGeometry {
        top: vertical[0],
        sidebar: body[0],
        main: body[1],
        footer: vertical[2],
    };

    render_topbar(frame, app, vertical[0]);
    render_sidebar(frame, app, body[0]);
    render_page(frame, app, body[1]);
    render_footer(frame, app, vertical[2]);
    render_modal(frame, app, area);
}

fn render_topbar(frame: &mut Frame, app: &App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Length(14),
            Constraint::Length(24),
            Constraint::Min(20),
            Constraint::Length(34),
        ])
        .split(area);
    frame.render_widget(
        Paragraph::new(Line::from(vec![
            Span::styled("●", Style::default().fg(Color::Rgb(255, 95, 87))),
            Span::raw("  "),
            Span::styled("●", Style::default().fg(Color::Rgb(254, 188, 46))),
            Span::raw("  "),
            Span::styled("●", Style::default().fg(Color::Rgb(40, 200, 64))),
        ]))
        .style(Style::default().bg(PANEL))
        .block(bottom_border()),
        chunks[0],
    );
    frame.render_widget(
        Paragraph::new("AgentSwitchboard")
            .style(
                Style::default()
                    .fg(TEXT)
                    .bg(PANEL)
                    .add_modifier(Modifier::BOLD),
            )
            .block(bottom_border()),
        chunks[1],
    );
    frame.render_widget(
        Paragraph::new(app.page.label())
            .alignment(ratatui::layout::Alignment::Center)
            .style(
                Style::default()
                    .fg(TEXT)
                    .bg(PANEL)
                    .add_modifier(Modifier::BOLD),
            )
            .block(bottom_border()),
        chunks[2],
    );
    let state = if app.error.is_some() {
        Span::styled("● ERROR", Style::default().fg(BAD))
    } else {
        Span::styled("● FCC LOCAL", Style::default().fg(GOOD))
    };
    frame.render_widget(
        Paragraph::new(Line::from(vec![
            state,
            Span::raw("  "),
            Span::styled(app.status_text(), Style::default().fg(MUTED)),
        ]))
        .alignment(ratatui::layout::Alignment::Right)
        .style(Style::default().bg(PANEL))
        .block(bottom_border()),
        chunks[3],
    );
}

fn render_sidebar(frame: &mut Frame, app: &mut App, area: Rect) {
    let block = Block::default()
        .borders(Borders::RIGHT)
        .border_style(Style::default().fg(BORDER))
        .style(Style::default().bg(PANEL));
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
            Span::styled("CONTROL", Style::default().fg(MUTED)),
            Span::raw("  "),
            Span::styled(
                "CENTER",
                Style::default().fg(TEXT).add_modifier(Modifier::BOLD),
            ),
        ])),
        title,
    );

    let mut y = inner.y + 4;
    for page in Page::ALL {
        if y >= inner.bottom().saturating_sub(7) {
            break;
        }
        let row = Rect {
            x: inner.x + 1,
            y,
            width: inner.width.saturating_sub(2),
            height: 2,
        };
        let selected = app.page == page;
        let hovered = app.mouse.map(|(x, y)| contains(row, x, y)).unwrap_or(false);
        let style = if selected {
            Style::default()
                .fg(TEXT)
                .bg(ACCENT_DIM)
                .add_modifier(Modifier::BOLD)
        } else if hovered {
            Style::default().fg(TEXT).bg(PANEL_2)
        } else {
            Style::default().fg(MUTED).bg(PANEL)
        };
        let marker = if selected { "▌ " } else { "  " };
        frame.render_widget(
            Paragraph::new(format!("{marker}{}", page.label())).style(style),
            row,
        );
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::Navigate(page),
        });
        y += 2;
    }

    let context = Rect {
        x: inner.x + 2,
        y: inner.bottom().saturating_sub(6),
        width: inner.width.saturating_sub(4),
        height: 5,
    };
    let model_line = if app.browser.default_unavailable(&app.catalog_snapshot()) {
        format!(
            "unavailable · {}",
            trim_to(app.browser.pending_default(), 18)
        )
    } else {
        trim_to(&app.status_model(), 22)
    };
    frame.render_widget(
        Paragraph::new(Text::from(vec![
            Line::from(Span::styled("ACTIVE MODEL", Style::default().fg(MUTED))),
            Line::from(Span::styled(
                model_line,
                Style::default().fg(
                    if app.browser.default_unavailable(&app.catalog_snapshot()) {
                        WARN
                    } else {
                        TEXT
                    },
                ),
            )),
            Line::from(""),
            Line::from(vec![
                Span::styled("CONTEXT  ", Style::default().fg(MUTED)),
                Span::styled(
                    format_tokens(&app.current_context()),
                    Style::default().fg(ACCENT),
                ),
            ]),
        ])),
        context,
    );
}

fn render_page(frame: &mut Frame, app: &mut App, area: Rect) {
    match app.page {
        Page::Dashboard => render_dashboard(frame, app, area),
        Page::Providers => render_providers(frame, app, area),
        Page::Models => render_models(frame, app, area),
        Page::Routing => render_field_page(frame, app, area, Page::Routing),
        Page::Context => render_context(frame, app, area),
        Page::Local => render_local(frame, app, area),
        Page::Settings => render_field_page(frame, app, area, Page::Settings),
        Page::Usage => render_usage(frame, app, area),
        Page::Diagnostics => render_diagnostics(frame, app, area),
    }
}

fn render_dashboard(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(5),
            Constraint::Min(8),
            Constraint::Length(4),
        ])
        .split(area);
    let status = app.status_text();
    let model = app.status_model();
    frame.render_widget(
        Paragraph::new(Text::from(vec![
            Line::from(Span::styled(
                "LOCAL CONTROL PLANE",
                Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
            )),
            Line::from(vec![
                Span::styled("Server  ", Style::default().fg(MUTED)),
                Span::styled(status, Style::default().fg(GOOD)),
            ]),
            Line::from(vec![
                Span::styled("Model   ", Style::default().fg(MUTED)),
                Span::styled(model, Style::default().fg(TEXT)),
            ]),
        ]))
        .style(Style::default().bg(BG))
        .block(section_block("Overview")),
        rows[0],
    );

    let pending = app
        .status
        .get("pending_fields")
        .cloned()
        .unwrap_or(Value::Null);
    let body = Text::from(vec![
        Line::from(Span::styled("The Rust control center is a thin client of fcc-server.", Style::default().fg(TEXT))),
        Line::from(""),
        Line::from(vec![Span::styled("Context window  ", Style::default().fg(MUTED)), Span::styled(format_tokens(&app.current_context()), Style::default().fg(ACCENT).add_modifier(Modifier::BOLD))]),
        Line::from(vec![Span::styled("Catalog         ", Style::default().fg(MUTED)), Span::styled(format!("{} models · {} routable · {} providers", app.model_inventory().len(), app.models.models.len(), app.config.provider_status.len()), Style::default().fg(TEXT))]),
        Line::from(vec![Span::styled("Pending changes  ", Style::default().fg(MUTED)), Span::styled(compact_json(&pending), Style::default().fg(WARN))]),
        Line::from(""),
        Line::from(Span::styled("Click the sidebar to open a workspace. Models is a live catalog browser: search, filter, inspect, enable, and assign defaults without leaving this terminal.", Style::default().fg(MUTED))),
    ]);
    frame.render_widget(
        Paragraph::new(body)
            .wrap(Wrap { trim: true })
            .block(section_block("Runtime")),
        rows[1],
    );
    action_bar(
        frame,
        app,
        rows[2],
        &[
            ("Refresh", UiAction::Refresh),
            ("Launch Claude", UiAction::LaunchClaude(false)),
        ],
    );
}

fn render_providers(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(10), Constraint::Length(4)])
        .split(area);
    let panes = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(45), Constraint::Percentage(55)])
        .split(rows[0]);

    let providers = app.config.provider_status.clone();
    render_provider_list(frame, app, panes[0], &providers);
    let selected = providers.get(app.provider_selected).cloned();
    render_provider_detail(frame, selected.as_ref(), panes[1]);

    let mut actions = vec![
        ("Configure", UiAction::ConfigureProvider),
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
        .map(|provider| provider.kind == "connected_account")
        .unwrap_or(false)
    {
        actions.push(("Sign in", UiAction::LoginProvider));
        actions.push(("Disconnect", UiAction::DisconnectProvider));
    }
    action_bar(frame, app, rows[1], &actions);
}

fn render_provider_list(
    frame: &mut Frame,
    app: &mut App,
    area: Rect,
    providers: &[ProviderStatus],
) {
    let block = section_block("Providers");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if providers.is_empty() {
        frame.render_widget(
            Paragraph::new("No providers advertised by fcc-server")
                .style(Style::default().fg(MUTED)),
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
        let status_color = provider_color(&provider.status);
        let label = if provider.display_name.is_empty() {
            &provider.provider_id
        } else {
            &provider.display_name
        };
        let line = Line::from(vec![
            Span::styled(
                if selected { "▌ " } else { "  " },
                Style::default().fg(ACCENT),
            ),
            Span::styled(
                trim_to(label, 24),
                if selected {
                    Style::default().fg(TEXT).add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(TEXT)
                },
            ),
            Span::raw("  "),
            Span::styled(
                trim_to(&provider.label, 18),
                Style::default().fg(status_color),
            ),
        ]);
        let style = if selected {
            Style::default().bg(ACCENT_DIM)
        } else {
            Style::default().bg(BG)
        };
        frame.render_widget(Paragraph::new(line).style(style), row);
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::SelectProvider(index),
        });
    }
}

fn render_provider_detail(frame: &mut Frame, provider: Option<&ProviderStatus>, area: Rect) {
    let block = section_block("Inspector");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let Some(provider) = provider else {
        frame.render_widget(
            Paragraph::new("Select a provider").style(Style::default().fg(MUTED)),
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
            Style::default().fg(TEXT).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        kv("Provider ID", &provider.provider_id),
        kv("Kind", &provider.kind),
        Line::from(vec![
            Span::styled("Status          ", Style::default().fg(MUTED)),
            Span::styled(
                if provider.label.is_empty() {
                    provider.status.clone()
                } else {
                    provider.label.clone()
                },
                Style::default().fg(provider_color(&provider.status)),
            ),
        ]),
    ];
    if !provider.base_url.is_empty() {
        lines.push(kv("Base URL", &provider.base_url));
    }
    if !provider.configuration.is_empty() {
        lines.push(kv("Required config", &provider.configuration));
    }
    if provider.custom {
        lines.push(kv(
            "API key",
            if provider.api_key_configured == Some(true) {
                "configured"
            } else {
                "not configured"
            },
        ));
        lines.push(kv(
            "Proxy",
            if provider.proxy_configured == Some(true) {
                "configured"
            } else {
                "not configured"
            },
        ));
        if !provider.model_ids.is_empty() {
            lines.push(kv("Models", &provider.model_ids.join(", ")));
        }
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled("Secrets are never read back into this UI. Enter replaces a configured key; leaving the secret editor blank preserves it.", Style::default().fg(MUTED))));
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
}

fn render_models(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(5),
            Constraint::Min(10),
            Constraint::Length(4),
        ])
        .split(area);
    render_model_toolbar(frame, app, rows[0]);
    let panes = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(52), Constraint::Percentage(48)])
        .split(rows[1]);
    let models = app.filtered_models();
    render_model_list(frame, app, panes[0], &models);
    render_model_detail(frame, app, panes[1], models.get(app.browser.selected));
    let enable_label = app
        .selected_model()
        .map(|model| {
            if app.browser.is_enabled(&model) {
                "Disable"
            } else {
                "Enable"
            }
        })
        .unwrap_or("Enable");
    let mut actions = vec![
        ("Default", UiAction::AssignModel(MODEL_KEY.to_string())),
        (enable_label, UiAction::ToggleModelAccess),
        ("Fable", UiAction::AssignModel("MODEL_FABLE".to_string())),
        ("Opus", UiAction::AssignModel("MODEL_OPUS".to_string())),
        ("Sonnet", UiAction::AssignModel("MODEL_SONNET".to_string())),
        ("Haiku", UiAction::AssignModel("MODEL_HAIKU".to_string())),
        ("Refresh", UiAction::Refresh),
    ];
    if app.browser.dirty() {
        actions.insert(0, ("Save", UiAction::SaveModels));
        actions.insert(1, ("Discard", UiAction::DiscardModels));
    }
    action_bar(frame, app, rows[2], &actions);
}

fn render_model_toolbar(frame: &mut Frame, app: &mut App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Length(2)])
        .split(area);
    let snapshot = app.catalog_snapshot();
    let query = if app.browser.query.is_empty() {
        if app.browser.search_focused {
            "▌".to_string()
        } else {
            "Search provider, model, alias, capability, free/paid…  (/)".to_string()
        }
    } else if app.browser.search_focused {
        format!("{}▌", app.browser.query)
    } else {
        format!("Filter: {}", app.browser.query)
    };
    let unavailable =
        if app.browser.default_unavailable(&snapshot) || snapshot.default_unavailable() {
            "  ·  default unavailable"
        } else {
            ""
        };
    let search_style = if app.browser.search_focused {
        Style::default().fg(TEXT).bg(ACCENT_DIM)
    } else {
        Style::default().fg(TEXT).bg(PANEL_2)
    };
    frame.render_widget(
        Paragraph::new(Line::from(vec![
            Span::styled(
                "MODEL CATALOG",
                Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
            ),
            Span::raw("  "),
            Span::styled(query, search_style),
            Span::raw("  "),
            Span::styled(
                format!(
                    "{} shown · {} catalog · {} enabled · {} unsaved{unavailable}",
                    app.filtered_models().len(),
                    snapshot.records.len(),
                    snapshot
                        .records
                        .iter()
                        .filter(|record| app.browser.is_enabled(&record.model_ref))
                        .count(),
                    app.browser.changes_count()
                ),
                Style::default().fg(if unavailable.is_empty() { MUTED } else { WARN }),
            ),
        ]))
        .style(Style::default().bg(PANEL_2))
        .block(bottom_border()),
        chunks[0],
    );
    app.hitboxes.push(Hitbox {
        rect: chunks[0],
        action: UiAction::SearchModels,
    });

    let mut x = chunks[1].x + 1;
    let chip_y = chunks[1].y;
    let chips: Vec<(String, UiAction, bool)> = vec![
        (
            app.browser.price_filter.label().to_string(),
            UiAction::SetPriceFilter(app.browser.price_filter.next()),
            app.browser.price_filter != PriceFilter::All,
        ),
        (
            app.browser.access_filter.label().to_string(),
            UiAction::SetAccessFilter(app.browser.access_filter.next()),
            app.browser.access_filter != AccessFilter::All,
        ),
        (
            app.browser.provider_filter_label(&snapshot),
            UiAction::CycleProviderFilter,
            app.browser.provider_filter.is_some(),
        ),
        (
            app.browser.sort.label().to_string(),
            UiAction::CycleSort,
            app.browser.sort != ModelSort::Provider,
        ),
    ];
    for (label, action, active) in chips {
        let width = (label.chars().count() as u16 + 4).min(chunks[1].right().saturating_sub(x));
        if width < 5 {
            break;
        }
        let chip = Rect {
            x,
            y: chip_y,
            width,
            height: chunks[1].height,
        };
        let hovered = app
            .mouse
            .map(|(mx, my)| contains(chip, mx, my))
            .unwrap_or(false);
        let style = if hovered || active {
            Style::default().fg(TEXT).bg(ACCENT_DIM)
        } else {
            Style::default().fg(MUTED).bg(PANEL)
        };
        frame.render_widget(Paragraph::new(format!(" {label} ")).style(style), chip);
        app.hitboxes.push(Hitbox { rect: chip, action });
        x = x.saturating_add(width + 1);
    }
}

fn render_model_list(frame: &mut Frame, app: &mut App, area: Rect, models: &[String]) {
    let block = section_block("Models");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if models.is_empty() {
        let snapshot = app.catalog_snapshot();
        let message = if snapshot.records.is_empty() {
            "No models discovered. Press Refresh to query configured providers."
        } else {
            "No models match these filters. Clear search or broaden the chips."
        };
        frame.render_widget(
            Paragraph::new(message).style(Style::default().fg(MUTED)),
            inner,
        );
        return;
    }
    let snapshot = app.catalog_snapshot();
    let mut display: Vec<(Option<String>, Option<usize>)> = Vec::new();
    let mut last_provider = String::new();
    let grouped = app.browser.sort == ModelSort::Provider;
    for (index, model) in models.iter().enumerate() {
        if grouped {
            let provider = snapshot
                .record(model)
                .map(|record| record.provider_label.clone())
                .unwrap_or_else(|| model.clone());
            if provider != last_provider {
                display.push((Some(provider.clone()), None));
                last_provider = provider;
            }
        }
        display.push((None, Some(index)));
    }
    let selected_display = display
        .iter()
        .position(|(_, model_index)| *model_index == Some(app.browser.selected))
        .unwrap_or(0);
    let offset = list_offset(selected_display, display.len(), inner.height as usize);
    for (visible, (header, model_index)) in display
        .iter()
        .skip(offset)
        .take(inner.height as usize)
        .enumerate()
    {
        let row = Rect {
            x: inner.x,
            y: inner.y + visible as u16,
            width: inner.width,
            height: 1,
        };
        if let Some(header) = header {
            frame.render_widget(
                Paragraph::new(format!(" {header}")).style(
                    Style::default()
                        .fg(ACCENT)
                        .bg(PANEL)
                        .add_modifier(Modifier::BOLD),
                ),
                row,
            );
            continue;
        }
        let Some(index) = *model_index else {
            continue;
        };
        let model = &models[index];
        let selected = index == app.browser.selected;
        let record = snapshot.record(model);
        let label = record
            .map(|item| item.label.as_str())
            .unwrap_or(model.as_str());
        let price = record.map(|item| item.price).unwrap_or(PriceState::Unknown);
        let enabled = app.browser.is_enabled(model);
        let is_default = app.browser.is_default(model);
        let marker = format!(
            "{} {} {:<6}",
            if is_default { "★" } else { " " },
            if enabled { "✓" } else { "○" },
            price.label()
        );
        let style = if selected {
            Style::default()
                .bg(ACCENT_DIM)
                .fg(TEXT)
                .add_modifier(Modifier::BOLD)
        } else if is_default {
            Style::default().bg(BG).fg(GOOD)
        } else if enabled {
            Style::default().bg(BG).fg(TEXT)
        } else {
            Style::default().bg(BG).fg(MUTED)
        };
        let prefix = format!("{} {}", if selected { "▌" } else { " " }, marker);
        let available = inner
            .width
            .saturating_sub(prefix.chars().count() as u16 + 1) as usize;
        frame.render_widget(
            Paragraph::new(format!("{} {}", prefix, trim_to(label, available))).style(style),
            row,
        );
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::SelectModel(index),
        });
    }
}

fn render_model_detail(frame: &mut Frame, app: &App, area: Rect, model: Option<&String>) {
    let block = section_block("Model inspector");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let Some(model) = model else {
        frame.render_widget(
            Paragraph::new("Select a model").style(Style::default().fg(MUTED)),
            inner,
        );
        return;
    };
    let snapshot = app.catalog_snapshot();
    let record = snapshot.record(model);
    let label = record
        .map(|item| item.label.clone())
        .unwrap_or_else(|| model.clone());
    let evidence = record
        .map(|item| item.evidence.clone())
        .unwrap_or(Value::Null);
    let aliases = snapshot.aliases_for(model);
    let assigned = snapshot.assigned_keys(model);
    let enabled = app.browser.is_enabled(model);
    let is_default = app.browser.is_default(model);
    let unavailable = app.browser.default_unavailable(&snapshot) && is_default;
    let status = if unavailable {
        "★ Default unavailable"
    } else if is_default && enabled {
        "★ Default · ✓ Enabled"
    } else if is_default {
        "★ Default"
    } else if enabled {
        "✓ Enabled"
    } else {
        "○ Cataloged · blocked"
    };
    let mut lines = vec![
        Line::from(Span::styled(
            label,
            Style::default().fg(TEXT).add_modifier(Modifier::BOLD),
        )),
        Line::from(Span::styled(model.to_string(), Style::default().fg(MUTED))),
        Line::from(""),
        kv("Status", status),
        kv(
            "Availability",
            if app.model_is_routable(model) {
                "routable"
            } else {
                "cataloged; blocked until enabled"
            },
        ),
        kv(
            "Price",
            record.map(|item| item.price.label()).unwrap_or("PRICE?"),
        ),
        kv("Pricing", &pricing_signal(&evidence)),
    ];
    if !aliases.is_empty() {
        lines.push(kv("Alias", &aliases.join(", ")));
    }
    if !assigned.is_empty() {
        lines.push(kv("Assigned", &assigned.join(" · ")));
    }
    if let Some(record) = record {
        lines.push(kv("Provider", &record.provider_label));
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Capabilities",
        Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
    )));
    for (label, value) in capability_summary(&evidence) {
        lines.push(kv(&label, &value));
    }
    lines.push(Line::from(""));
    if is_default && enabled {
        lines.push(Line::from(Span::styled(
            "Disable hands default status to another enabled model on Save.",
            Style::default().fg(MUTED),
        )));
    } else if enabled {
        lines.push(Line::from(Span::styled(
            "Disable removes this model from the curated catalog on Save.",
            Style::default().fg(MUTED),
        )));
    } else {
        lines.push(Line::from(Span::styled(
            "Enable adds this model to the curated catalog on Save. Making it default also enables it.",
            Style::default().fg(MUTED),
        )));
    }
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
}

fn render_field_page(frame: &mut Frame, app: &mut App, area: Rect, page: Page) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(10), Constraint::Length(4)])
        .split(area);
    let panes = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(48), Constraint::Percentage(52)])
        .split(rows[0]);
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
    render_field_list(frame, app, panes[0], page, &indices, selected);
    let field = indices
        .get(selected)
        .and_then(|index| app.config.fields.get(*index))
        .cloned();
    render_field_detail(frame, field.as_ref(), panes[1]);
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
    let block = section_block(match page {
        Page::Routing => "Routing policy",
        Page::Local => "Local endpoints",
        Page::Settings => "Configuration",
        _ => "Fields",
    });
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if indices.is_empty() {
        frame.render_widget(
            Paragraph::new("No fields available").style(Style::default().fg(MUTED)),
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
        let value = App::display_field_value(field);
        let label_width = (inner.width as usize / 2).max(12);
        let line = format!(
            "{}{:label_width$}  {}",
            if selected_row { "▌ " } else { "  " },
            trim_to(&field.label, label_width),
            trim_to(
                &value,
                inner.width.saturating_sub(label_width as u16 + 5) as usize
            )
        );
        let style = if selected_row {
            Style::default()
                .bg(ACCENT_DIM)
                .fg(TEXT)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().bg(BG).fg(TEXT)
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

fn render_field_detail(frame: &mut Frame, field: Option<&ConfigField>, area: Rect) {
    let block = section_block("Inspector");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let Some(field) = field else {
        frame.render_widget(
            Paragraph::new("Select a setting").style(Style::default().fg(MUTED)),
            inner,
        );
        return;
    };
    let mut lines = vec![
        Line::from(Span::styled(
            field.label.clone(),
            Style::default().fg(TEXT).add_modifier(Modifier::BOLD),
        )),
        Line::from(Span::styled(field.key.clone(), Style::default().fg(MUTED))),
        Line::from(""),
        kv("Value", &App::display_field_value(field)),
        kv("Source", &field.source),
        kv("Type", &field.field_type),
        kv("Locked", if field.locked { "Yes" } else { "No" }),
        kv(
            "Restart",
            if field.restart_required {
                "Required"
            } else {
                "No"
            },
        ),
        kv(
            "Session boundary",
            if field.session_sensitive { "Yes" } else { "No" },
        ),
        Line::from(""),
        Line::from(Span::styled(
            field.description.clone(),
            Style::default().fg(MUTED),
        )),
    ];
    if field.secret {
        lines.push(Line::from(""));
        lines.push(Line::from(Span::styled(
            "Configured secrets are masked. Enter replaces; X explicitly clears.",
            Style::default().fg(WARN),
        )));
    }
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
}

fn render_context(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(12), Constraint::Length(4)])
        .split(area);
    let field = app.context_field().cloned();
    let current = field
        .as_ref()
        .map(App::display_field_value)
        .unwrap_or_else(|| "256000".to_string());
    let block = section_block("Claude Code context policy");
    let inner = block.inner(rows[0]);
    frame.render_widget(block, rows[0]);
    let lines = vec![
        Line::from(Span::styled("SESSION WINDOW", Style::default().fg(MUTED).add_modifier(Modifier::BOLD))),
        Line::from(Span::styled(format_tokens(&current), Style::default().fg(ACCENT).add_modifier(Modifier::BOLD))),
        Line::from(""),
        kv("FCC setting", "FCC_CLAUDE_CONTEXT_TOKENS"),
        kv("Accepted range", &format!("{CONTEXT_MIN} – {CONTEXT_MAX} tokens")),
        Line::from(""),
        Line::from(Span::styled("New FCC-launched Claude sessions receive the selected value as BOTH:", Style::default().fg(TEXT))),
        Line::from(Span::styled("CLAUDE_CODE_MAX_CONTEXT_TOKENS", Style::default().fg(GOOD))),
        Line::from(Span::styled("CLAUDE_CODE_AUTO_COMPACT_WINDOW", Style::default().fg(GOOD))),
        Line::from(""),
        Line::from(Span::styled("Changing this setting does not resize an already-running Claude process. Known model-native ceilings smaller than the configured cap still win.", Style::default().fg(MUTED))),
        Line::from(""),
        Line::from(Span::styled("Default 256K is deliberate. Raise it only when the selected upstream model actually supports the larger window.", Style::default().fg(WARN))),
    ];
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
    action_bar(
        frame,
        app,
        rows[1],
        &[
            ("Edit context", UiAction::EditField),
            ("Refresh", UiAction::Refresh),
        ],
    );
}

fn render_local(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(10), Constraint::Length(4)])
        .split(area);
    let panes = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(46), Constraint::Percentage(54)])
        .split(rows[0]);
    render_local_status_list(frame, app, panes[0]);
    render_local_detail(frame, app, panes[1]);
    action_bar(
        frame,
        app,
        rows[1],
        &[
            ("Edit endpoint", UiAction::EditField),
            ("Refresh", UiAction::Refresh),
        ],
    );
}

fn render_local_status_list(frame: &mut Frame, app: &mut App, area: Rect) {
    let block = section_block("Local endpoints");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let indices = app.local_field_indices();
    if indices.is_empty() && app.local_status.is_empty() {
        frame.render_widget(
            Paragraph::new("No local provider fields advertised").style(Style::default().fg(MUTED)),
            inner,
        );
        return;
    }
    let offset = list_offset(
        app.local_selected,
        indices.len().max(1),
        inner.height as usize,
    );
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
        let selected = index == app.local_selected;
        let status = local_status_for(app, &field.key);
        let line = format!(
            "{}{:18}  {}",
            if selected { "▌ " } else { "  " },
            trim_to(&field.label, 18),
            status
        );
        let style = if selected {
            Style::default()
                .bg(ACCENT_DIM)
                .fg(TEXT)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().bg(BG).fg(TEXT)
        };
        frame.render_widget(Paragraph::new(line).style(style), row);
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::SelectLocal(index),
        });
    }
}

fn render_local_detail(frame: &mut Frame, app: &App, area: Rect) {
    let indices = app.local_field_indices();
    let field = indices
        .get(app.local_selected)
        .and_then(|index| app.config.fields.get(*index));
    let block = section_block("Reachability");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let Some(field) = field else {
        frame.render_widget(
            Paragraph::new("Select a local endpoint").style(Style::default().fg(MUTED)),
            inner,
        );
        return;
    };
    let status = app
        .local_status
        .iter()
        .find(|provider| local_field_matches_provider(&field.key, &provider.provider_id));
    let mut lines = vec![
        Line::from(Span::styled(
            field.label.clone(),
            Style::default().fg(TEXT).add_modifier(Modifier::BOLD),
        )),
        Line::from(Span::styled(field.key.clone(), Style::default().fg(MUTED))),
        Line::from(""),
        kv("Value", &App::display_field_value(field)),
    ];
    if let Some(status) = status {
        lines.push(kv(
            "Probe",
            if status.label.is_empty() {
                &status.status
            } else {
                &status.label
            },
        ));
        if !status.base_url.is_empty() {
            lines.push(kv("Probed URL", &status.base_url));
        }
        lines.push(Line::from(Span::styled(
            "Reachability uses /admin/api/providers/local-status. This UI never probes hosts itself.",
            Style::default().fg(MUTED),
        )));
    } else {
        lines.push(Line::from(Span::styled(
            "Press Refresh to probe LM Studio, llama.cpp, and Ollama through the Admin API.",
            Style::default().fg(MUTED),
        )));
    }
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
}

fn local_status_for(app: &App, field_key: &str) -> String {
    if let Some(provider) = app
        .local_status
        .iter()
        .find(|provider| local_field_matches_provider(field_key, &provider.provider_id))
    {
        if provider.label.is_empty() {
            return provider.status.clone();
        }
        return provider.label.clone();
    }
    app.config
        .fields
        .iter()
        .find(|field| field.key == field_key)
        .map(App::display_field_value)
        .unwrap_or_else(|| "—".to_string())
}

fn local_field_matches_provider(field_key: &str, provider_id: &str) -> bool {
    matches!(
        (field_key, provider_id),
        ("LM_STUDIO_BASE_URL", "lmstudio")
            | ("LLAMACPP_BASE_URL", "llamacpp")
            | ("OLLAMA_BASE_URL" | "OLLAMA_API_KEY", "ollama")
    )
}

fn render_usage(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(7),
            Constraint::Min(8),
            Constraint::Length(4),
        ])
        .split(area);
    let totals = app.usage.get("totals").cloned().unwrap_or(Value::Null);
    let range = app
        .usage
        .get("range_days")
        .map(compact_json)
        .unwrap_or_else(|| "30".to_string());
    frame.render_widget(
        Paragraph::new(Text::from(vec![
            Line::from(Span::styled(
                format!("{range}-day metadata-only usage"),
                Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
            )),
            Line::from(vec![
                Span::styled("Requests  ", Style::default().fg(MUTED)),
                Span::styled(json_number(&totals, "requests"), Style::default().fg(TEXT)),
                Span::raw("    "),
                Span::styled("Input  ", Style::default().fg(MUTED)),
                Span::styled(
                    json_number(&totals, "input_tokens"),
                    Style::default().fg(TEXT),
                ),
                Span::raw("    "),
                Span::styled("Output  ", Style::default().fg(MUTED)),
                Span::styled(
                    json_number(&totals, "output_tokens"),
                    Style::default().fg(ACCENT),
                ),
            ]),
            Line::from(Span::styled(
                "Prompt and response content are never shown here.",
                Style::default().fg(MUTED),
            )),
        ]))
        .block(section_block("Totals")),
        rows[0],
    );
    let model_rows = app
        .usage
        .get("models")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut lines = Vec::new();
    if model_rows.is_empty() {
        lines.push(Line::from(Span::styled(
            "No usage events in this window.",
            Style::default().fg(MUTED),
        )));
    } else {
        for row in model_rows.iter().take(16) {
            let model = row
                .get("model")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            let label = app
                .usage
                .get("model_labels")
                .and_then(Value::as_object)
                .and_then(|labels| labels.get(model))
                .and_then(Value::as_str)
                .unwrap_or(model);
            lines.push(Line::from(vec![
                Span::styled(
                    format!("{:<28}", trim_to(label, 28)),
                    Style::default().fg(TEXT),
                ),
                Span::styled(
                    format!(
                        "  in {}  out {}",
                        json_number(row, "input_tokens"),
                        json_number(row, "output_tokens")
                    ),
                    Style::default().fg(MUTED),
                ),
            ]));
        }
    }
    frame.render_widget(
        Paragraph::new(Text::from(lines)).block(section_block("By model")),
        rows[1],
    );
    action_bar(frame, app, rows[2], &[("Refresh", UiAction::Refresh)]);
}

fn render_diagnostics(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(8), Constraint::Length(4)])
        .split(area);
    let lines = if app.diagnostic.is_null() {
        vec![Line::from(Span::styled(
            "Run a synthetic route diagnostic. No prompt content is sent to a provider.",
            Style::default().fg(MUTED),
        ))]
    } else {
        diagnostic_lines(&app.diagnostic)
    };
    frame.render_widget(
        Paragraph::new(Text::from(lines))
            .wrap(Wrap { trim: true })
            .block(section_block("Route diagnostic")),
        rows[0],
    );
    action_bar(
        frame,
        app,
        rows[1],
        &[
            ("Run diagnostic", UiAction::RunDiagnostic),
            ("Refresh", UiAction::Refresh),
        ],
    );
}

fn diagnostic_lines(value: &Value) -> Vec<Line<'static>> {
    let controller = value.get("controller").cloned().unwrap_or(Value::Null);
    let policy = value.get("policy").cloned().unwrap_or(Value::Null);
    let mut lines = vec![
        kv(
            "Requested",
            controller
                .get("requested_model")
                .and_then(Value::as_str)
                .unwrap_or("—"),
        ),
        kv(
            "Provider",
            controller
                .get("provider")
                .and_then(Value::as_str)
                .unwrap_or("—"),
        ),
        kv(
            "Model ref",
            controller
                .get("model_ref")
                .and_then(Value::as_str)
                .unwrap_or("—"),
        ),
        kv(
            "Route source",
            controller
                .get("route_source")
                .and_then(Value::as_str)
                .unwrap_or("—"),
        ),
        kv(
            "Network",
            value
                .get("network")
                .and_then(Value::as_str)
                .unwrap_or("none"),
        ),
        kv(
            "Policy",
            policy.get("mode").and_then(Value::as_str).unwrap_or("—"),
        ),
    ];
    if let Some(error) = value
        .pointer("/policy/error")
        .and_then(Value::as_str)
        .or_else(|| value.pointer("/decision/error").and_then(Value::as_str))
    {
        lines.push(kv("Error", error));
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Capability evidence",
        Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
    )));
    if let Some(rows) = value.get("capability_evidence").and_then(Value::as_array) {
        for row in rows.iter().take(8) {
            let name = row
                .get("capability")
                .or_else(|| row.get("name"))
                .and_then(Value::as_str)
                .unwrap_or("capability");
            let state = row
                .get("state")
                .or_else(|| row.get("status"))
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            lines.push(kv(name, state));
        }
    } else {
        lines.push(Line::from(Span::styled(
            trim_to(&pretty(value), 400),
            Style::default().fg(MUTED),
        )));
    }
    lines
}

fn json_number(value: &Value, key: &str) -> String {
    match value.get(key) {
        Some(Value::Number(number)) => number.to_string(),
        Some(Value::String(text)) => text.clone(),
        _ => "0".to_string(),
    }
}

fn render_footer(frame: &mut Frame, app: &App, area: Rect) {
    let message = if let Some(error) = &app.error {
        Span::styled(
            trim_to(error, 72),
            Style::default().fg(BAD).add_modifier(Modifier::BOLD),
        )
    } else if let Some(notice) = &app.notice {
        Span::styled(trim_to(notice, 72), Style::default().fg(GOOD))
    } else {
        Span::styled("LOCAL · LOOPBACK ADMIN API", Style::default().fg(MUTED))
    };
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(45), Constraint::Percentage(55)])
        .split(area);
    frame.render_widget(
        Paragraph::new(Line::from(message))
            .style(Style::default().bg(PANEL))
            .block(top_border()),
        chunks[0],
    );
    frame.render_widget(
        Paragraph::new(
            "Mouse · ↑↓ Navigate · / Search · Enter Open · R Refresh · C Claude · ? Help · Q Quit",
        )
        .alignment(ratatui::layout::Alignment::Right)
        .style(Style::default().fg(MUTED).bg(PANEL))
        .block(top_border()),
        chunks[1],
    );
}

fn action_bar(frame: &mut Frame, app: &mut App, area: Rect, actions: &[(&str, UiAction)]) {
    frame.render_widget(
        Block::default()
            .borders(Borders::TOP)
            .border_style(Style::default().fg(BORDER))
            .style(Style::default().bg(PANEL)),
        area,
    );
    let mut x = area.x + 1;
    for (label, action) in actions {
        let width = (label.chars().count() as u16 + 4).min(area.right().saturating_sub(x));
        if width < 5 || x >= area.right() {
            break;
        }
        let button = Rect {
            x,
            y: area.y + 1,
            width,
            height: 2.min(area.height.saturating_sub(1)),
        };
        let hovered = app
            .mouse
            .map(|(mx, my)| contains(button, mx, my))
            .unwrap_or(false);
        let style = if hovered {
            Style::default()
                .fg(TEXT)
                .bg(ACCENT_DIM)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(TEXT).bg(PANEL_2)
        };
        frame.render_widget(Paragraph::new(format!("  {label}  ")).style(style), button);
        app.hitboxes.push(Hitbox {
            rect: button,
            action: action.clone(),
        });
        x = x.saturating_add(width + 1);
    }
}

fn render_modal(frame: &mut Frame, app: &App, area: Rect) {
    let Some(modal) = &app.modal else {
        return;
    };
    let rect = centered(
        area,
        76,
        match modal {
            Modal::ProviderEditor { .. } => 24,
            Modal::Help => 22,
            Modal::FieldPicker { field_indices, .. } => (field_indices.len() as u16 + 6).min(24),
            Modal::Choice { options, .. } => (options.len() as u16 + 6).min(22),
            _ => 14,
        },
    );
    frame.render_widget(Clear, rect);
    frame.render_widget(Block::default().style(Style::default().bg(PANEL)), rect);
    match modal {
        Modal::EditField { field, input } => render_edit_modal(frame, rect, field, input),
        Modal::Choice { label, options, selected, .. } => render_choice_modal(frame, rect, label, options, *selected),
        Modal::FieldPicker { title, field_indices, selected } => render_field_picker(frame, app, rect, title, field_indices, *selected),
        Modal::ProviderEditor { existing_id, draft, selected, editing } => render_provider_editor(frame, rect, existing_id.as_deref(), draft, *selected, editing.as_ref()),
        Modal::Confirm { title, body, .. } => render_message_box(frame, rect, title, &format!("{body}\n\nEnter/Y confirms · Esc/N cancels"), WARN),
        Modal::Message { title, body } => render_message_box(frame, rect, title, body, TEXT),
        Modal::Help => render_message_box(frame, rect, "Keyboard + mouse", "Click sidebar rows, list rows, filter chips, and action buttons.\n\nGlobal: Tab/Shift-Tab pages · R refresh · C launch Claude · ! danger launcher · Q quit\nProviders: Enter configure · T test · N new custom · E edit custom · X delete · L browser login · Shift-L device login · Shift-D disconnect\nModels: / live search · click chips to filter · D default (enables) · E enable/disable · F/O/S/H assign tiers · Ctrl-S save · U discard · P price · V visibility · G sort · Shift-P provider\nSettings: Enter edit · A advanced · X clear selected secret\nMultiline editor: Ctrl-Enter saves · Esc cancels\nCustom provider editor: ↑↓ field · Enter edit · Space toggle booleans · Ctrl-S save", TEXT),
    }
}

fn render_edit_modal(
    frame: &mut Frame,
    rect: Rect,
    field: &ConfigField,
    input: &crate::app::TextInput,
) {
    let block = modal_block(&field.label);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    let shown = if input.secret {
        "•".repeat(input.value.chars().count())
    } else {
        input.value.clone()
    };
    let hint = if input.multiline {
        "Ctrl-Enter saves · Enter newline · Esc cancels"
    } else if field.secret && field.configured {
        "Type a replacement key · blank + Enter preserves · Esc cancels"
    } else {
        "Enter saves · Esc cancels"
    };
    frame.render_widget(
        Paragraph::new(shown)
            .style(Style::default().fg(TEXT).bg(BG))
            .wrap(Wrap { trim: false })
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(ACCENT)),
            ),
        Rect {
            x: inner.x,
            y: inner.y + 1,
            width: inner.width,
            height: inner.height.saturating_sub(4),
        },
    );
    frame.render_widget(
        Paragraph::new(hint).style(Style::default().fg(MUTED)),
        Rect {
            x: inner.x,
            y: inner.bottom().saturating_sub(2),
            width: inner.width,
            height: 2,
        },
    );
}

fn render_choice_modal(
    frame: &mut Frame,
    rect: Rect,
    title: &str,
    options: &[crate::api::ConfigOption],
    selected: usize,
) {
    let block = modal_block(title);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    for (index, option) in options
        .iter()
        .enumerate()
        .take(inner.height.saturating_sub(2) as usize)
    {
        let row = Rect {
            x: inner.x,
            y: inner.y + index as u16,
            width: inner.width,
            height: 1,
        };
        let style = if index == selected {
            Style::default()
                .fg(TEXT)
                .bg(ACCENT_DIM)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(TEXT)
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
    app: &App,
    rect: Rect,
    title: &str,
    indices: &[usize],
    selected: usize,
) {
    let block = modal_block(title);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    for (visible, index) in indices
        .iter()
        .enumerate()
        .take(inner.height.saturating_sub(2) as usize)
    {
        let Some(field) = app.config.fields.get(*index) else {
            continue;
        };
        let row = Rect {
            x: inner.x,
            y: inner.y + visible as u16,
            width: inner.width,
            height: 1,
        };
        let style = if visible == selected {
            Style::default()
                .fg(TEXT)
                .bg(ACCENT_DIM)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(TEXT)
        };
        frame.render_widget(
            Paragraph::new(format!(
                "{}{:30}  {}",
                if visible == selected { "▌ " } else { "  " },
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
    let block = modal_block(title);
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
                .fg(TEXT)
                .bg(ACCENT_DIM)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(TEXT)
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
            .style(Style::default().fg(MUTED)),
        Rect {
            x: inner.x,
            y: hint_y,
            width: inner.width,
            height: 2,
        },
    );
    if let Some(input) = editing {
        let shown = if input.secret {
            "•".repeat(input.value.chars().count())
        } else {
            input.value.clone()
        };
        frame.render_widget(
            Paragraph::new(shown)
                .wrap(Wrap { trim: false })
                .style(Style::default().fg(TEXT).bg(BG))
                .block(
                    Block::default()
                        .title(" Edit value ")
                        .borders(Borders::ALL)
                        .border_style(Style::default().fg(ACCENT)),
                ),
            Rect {
                x: inner.x,
                y: hint_y + 3,
                width: inner.width,
                height: inner.bottom().saturating_sub(hint_y + 3),
            },
        );
    } else if existing_id.is_some() && draft.existing_has_key {
        frame.render_widget(Paragraph::new("API key is configured but never returned by FCC. Leave API key blank to preserve it.").style(Style::default().fg(WARN)).wrap(Wrap { trim: true }), Rect { x: inner.x, y: hint_y + 3, width: inner.width, height: 3 });
    }
}

fn render_message_box(frame: &mut Frame, rect: Rect, title: &str, body: &str, color: Color) {
    let block = modal_block(title);
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    frame.render_widget(
        Paragraph::new(body.to_string())
            .style(Style::default().fg(color))
            .wrap(Wrap { trim: true }),
        inner,
    );
}

fn section_block(title: &str) -> Block<'_> {
    Block::default()
        .title(Span::styled(
            format!(" {title} "),
            Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(BORDER))
        .style(Style::default().bg(BG))
}

fn modal_block(title: &str) -> Block<'_> {
    Block::default()
        .title(Span::styled(
            format!(" {title} "),
            Style::default().fg(TEXT).add_modifier(Modifier::BOLD),
        ))
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(ACCENT))
        .style(Style::default().bg(PANEL))
}

fn bottom_border() -> Block<'static> {
    Block::default()
        .borders(Borders::BOTTOM)
        .border_style(Style::default().fg(BORDER))
        .style(Style::default().bg(PANEL))
}

fn top_border() -> Block<'static> {
    Block::default()
        .borders(Borders::TOP)
        .border_style(Style::default().fg(BORDER))
        .style(Style::default().bg(PANEL))
}

fn kv(label: &str, value: &str) -> Line<'static> {
    Line::from(vec![
        Span::styled(format!("{label:<16}"), Style::default().fg(MUTED)),
        Span::styled(value.to_string(), Style::default().fg(TEXT)),
    ])
}

fn provider_color(status: &str) -> Color {
    match status {
        "configured" | "reachable" | "connected" => GOOD,
        "missing_key" | "missing_config" | "missing_url" | "unknown" => WARN,
        "offline" | "invalid_config" => BAD,
        "disabled" | "disconnected" => MUTED,
        _ => MUTED,
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

fn compact_json(value: &Value) -> String {
    match value {
        Value::Null => "—".to_string(),
        Value::String(value) => value.clone(),
        _ => serde_json::to_string(value).unwrap_or_else(|_| "—".to_string()),
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
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;

    #[test]
    fn desktop_geometry_is_cell_exact_at_reference_viewport() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.top.height, 3);
        assert_eq!(app.geometry.sidebar.width, 28);
        assert_eq!(app.geometry.footer.height, 2);
        assert_eq!(app.geometry.main.width, 132);
    }

    #[test]
    fn context_page_keeps_same_desktop_shell() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.page = Page::Context;
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.sidebar.width, 28);
        assert_eq!(app.geometry.top.height, 3);
        assert_eq!(app.geometry.footer.height, 2);
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
            ConfigField {
                key: "LM_STUDIO_BASE_URL".to_string(),
                label: "LM Studio URL".to_string(),
                field_type: "text".to_string(),
                value: "http://127.0.0.1:1234/v1".to_string(),
                configured: true,
                ..ConfigField::default()
            },
            ConfigField {
                key: "MODEL_CATALOG_MODE".to_string(),
                value: "curated".to_string(),
                ..ConfigField::default()
            },
            ConfigField {
                key: "MODEL_CATALOG_ALLOWLIST".to_string(),
                value: "open_router/openrouter/free".to_string(),
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
        app.local_status = vec![ProviderStatus {
            provider_id: "lmstudio".to_string(),
            status: "reachable".to_string(),
            label: "Reachable".to_string(),
            base_url: "http://127.0.0.1:1234/v1".to_string(),
            ..ProviderStatus::default()
        }];
        app.usage = serde_json::json!({
            "range_days": 30,
            "totals": {"requests": 2, "input_tokens": 11, "output_tokens": 4},
            "models": [{"model": "open_router/openrouter/free", "input_tokens": 11, "output_tokens": 4}],
            "model_labels": {"open_router/openrouter/free": "OpenRouter · Free"}
        });
        app.diagnostic = serde_json::json!({
            "network": "none",
            "controller": {
                "requested_model": "open_router/openrouter/free",
                "provider": "open_router",
                "model_ref": "open_router/openrouter/free",
                "route_source": "MODEL"
            },
            "policy": {"mode": "strict"},
            "capability_evidence": [{"capability": "native_tools", "state": "supported"}]
        });
        app.sync_model_browser();

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
            Modal::Confirm {
                title: "Clear secret".to_string(),
                body: "Clear OpenRouter API key?".to_string(),
                action: ConfirmAction::ClearField("OPENROUTER_API_KEY".to_string()),
            },
            Modal::Message {
                title: "Provider test".to_string(),
                body: "{\"ok\":true}".to_string(),
            },
            Modal::Help,
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

    #[test]
    fn models_page_pins_search_filters_and_list_detail_hitboxes() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.config.fields.push(ConfigField {
            key: "MODEL".to_string(),
            value: "open_router/openrouter/free".to_string(),
            ..ConfigField::default()
        });
        app.models = ModelsResponse {
            models: vec!["open_router/openrouter/free".to_string()],
            catalog_models: vec![
                "open_router/openrouter/free".to_string(),
                "open_router/openrouter/paid".to_string(),
            ],
            catalog_model_labels: [
                (
                    "open_router/openrouter/free".to_string(),
                    "Free row".to_string(),
                ),
                (
                    "open_router/openrouter/paid".to_string(),
                    "Paid row".to_string(),
                ),
            ]
            .into_iter()
            .collect(),
            catalog_model_evidence: [(
                "open_router/openrouter/free".to_string(),
                serde_json::json!({"is_free": true}),
            )]
            .into_iter()
            .collect(),
            ..ModelsResponse::default()
        };
        app.sync_model_browser();
        let mut terminal = Terminal::new(TestBackend::new(160, 50)).unwrap();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.top.height, 3);
        assert_eq!(app.geometry.sidebar.width, 28);
        assert_eq!(app.geometry.main.width, 132);
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::SearchModels)));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::SetPriceFilter(_))));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::SelectModel(0))));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::AssignModel(_))));
    }
}
