use crate::api::{ConfigField, ProviderStatus};
use crate::app::{
    match_palette, pretty, App, ChromeGeometry, ConnectionState, Hitbox, Modal, Page, UiAction,
};
use crate::models::{PriceFilter, PriceState, MODEL_KEY};
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

fn short_instance_id(value: &str) -> &str {
    value.get(..8).unwrap_or(value)
}

fn format_uptime(seconds: f64) -> String {
    let total = seconds.max(0.0) as u64;
    let days = total / 86_400;
    let hours = (total % 86_400) / 3_600;
    let minutes = (total % 3_600) / 60;
    let seconds = total % 60;
    if days > 0 {
        format!("{days}d {hours}h")
    } else if hours > 0 {
        format!("{hours}h {minutes}m")
    } else if minutes > 0 {
        format!("{minutes}m {seconds}s")
    } else {
        format!("{seconds}s")
    }
}

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
            Constraint::Percentage(32),
            Constraint::Percentage(26),
            Constraint::Percentage(42),
        ])
        .split(area);
    frame.render_widget(
        Paragraph::new("AgentSwitchboard")
            .style(
                Style::default()
                    .fg(TEXT)
                    .bg(PANEL)
                    .add_modifier(Modifier::BOLD),
            )
            .block(bottom_border()),
        chunks[0],
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
        chunks[1],
    );
    let state_color = match app.connection_state {
        ConnectionState::Running => GOOD,
        ConnectionState::Starting | ConnectionState::Degraded => WARN,
        ConnectionState::Offline | ConnectionState::Unknown => BAD,
    };
    let state = Span::styled(
        format!(
            "{} {}",
            app.connection_state.label(),
            app.server_identity.mode
        ),
        Style::default().fg(state_color),
    );
    frame.render_widget(
        Paragraph::new(Line::from(vec![
            state,
            Span::raw("  "),
            Span::styled(app.status_text(), Style::default().fg(MUTED)),
        ]))
        .alignment(ratatui::layout::Alignment::Right)
        .style(Style::default().bg(PANEL))
        .block(bottom_border()),
        chunks[2],
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

    let row_height = if inner.height < 25 { 1 } else { 2 };
    let mut y = inner.y + 4;
    for page in Page::ALL {
        if y >= inner.bottom() {
            break;
        }
        let row = Rect {
            x: inner.x + 1,
            y,
            width: inner.width.saturating_sub(2),
            height: row_height.min(inner.bottom().saturating_sub(y)),
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
        y += row_height;
    }
}

fn render_page(frame: &mut Frame, app: &mut App, area: Rect) {
    match app.page {
        Page::Dashboard => render_dashboard(frame, app, area),
        Page::Repositories => render_repositories(frame, app, area),
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

fn render_repositories(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(10), Constraint::Length(5)])
        .split(area);
    let panes = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(55), Constraint::Percentage(45)])
        .split(rows[0]);
    render_repository_list(frame, app, panes[0]);
    render_repository_detail(frame, app, panes[1]);
    let actions = if app.is_bootstrap() {
        if app.bootstrap_launch_after_repository() {
            vec![
                (
                    app.bootstrap_repository_action_label(),
                    UiAction::UseRepository,
                ),
                ("Models", UiAction::Navigate(Page::Models)),
            ]
        } else {
            vec![
                ("Use selected", UiAction::UseRepository),
                ("Start server", UiAction::StartServer),
            ]
        }
    } else {
        vec![
            ("Use selected", UiAction::UseRepository),
            ("Refresh", UiAction::RefreshRepositories),
            ("Launch Claude", UiAction::LaunchClaude(false)),
            ("Danger launch", UiAction::LaunchClaude(true)),
        ]
    };
    action_bar(frame, app, rows[1], &actions);
}

fn render_repository_list(frame: &mut Frame, app: &mut App, area: Rect) {
    let block = section_block("Repositories");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if app.repositories.is_empty() {
        frame.render_widget(
            Paragraph::new(
                "No local GitHub checkouts found. Press Refresh to rescan.\n\n".to_string()
                    + "Linked worktrees, non-GitHub folders, and stale cache paths are omitted.",
            )
            .style(Style::default().fg(MUTED))
            .wrap(Wrap { trim: true }),
            inner,
        );
        return;
    }
    let offset = list_offset(
        app.repository_selected,
        app.repositories.len(),
        inner.height as usize,
    );
    for (visible, repository) in app
        .repositories
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
        let selected = index == app.repository_selected;
        let persisted = app
            .selected_repo_path
            .as_deref()
            .map(|path| path == repository.path)
            .unwrap_or(false);
        let marker = if selected {
            "▌ "
        } else if persisted {
            "✓ "
        } else {
            "  "
        };
        let label = format!(
            "{marker}{}  {}",
            trim_to(&repository.identity, 26),
            trim_to(&repository.name, 18),
        );
        let style = if selected {
            Style::default()
                .bg(ACCENT_DIM)
                .fg(TEXT)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().bg(BG).fg(TEXT)
        };
        frame.render_widget(Paragraph::new(label).style(style), row);
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::SelectRepository(index),
        });
    }
}

fn render_repository_detail(frame: &mut Frame, app: &App, area: Rect) {
    let block = section_block("Repository inspector");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let Some(repository) = app.selected_repository() else {
        frame.render_widget(
            Paragraph::new("Select a repository or press Refresh")
                .style(Style::default().fg(MUTED)),
            inner,
        );
        return;
    };
    let selected = app
        .selected_repo_path
        .as_deref()
        .map(|path| path == repository.path)
        .unwrap_or(false);
    let lines = vec![
        Line::from(Span::styled(
            repository.identity.clone(),
            Style::default().fg(TEXT).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        kv("GitHub / remote", &repository.remote),
        kv("Local folder", &repository.name),
        kv("Branch", &repository.branch),
        kv("Path", &repository.display_path),
        kv(
            "Selection",
            if selected {
                "next Claude launch"
            } else {
                "not selected"
            },
        ),
        Line::from(""),
        Line::from(Span::styled(
            "Use selected persists this checkout. Launch Claude starts in its folder.",
            Style::default().fg(MUTED),
        )),
        Line::from(Span::styled(
            "Danger launch uses fccdanger (--dangerously-skip-permissions).",
            Style::default().fg(WARN),
        )),
    ];
    frame.render_widget(
        Paragraph::new(Text::from(lines)).wrap(Wrap { trim: true }),
        inner,
    );
}

fn render_dashboard(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(8),
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
                Span::styled("Model     ", Style::default().fg(MUTED)),
                Span::styled(model, Style::default().fg(TEXT)),
            ]),
            Line::from(vec![
                Span::styled("Endpoint  ", Style::default().fg(MUTED)),
                Span::styled(
                    if app.server_identity.health_url.is_empty() {
                        "not advertised".to_string()
                    } else {
                        app.server_identity.health_url.clone()
                    },
                    Style::default().fg(TEXT),
                ),
            ]),
            Line::from(vec![
                Span::styled("Process   ", Style::default().fg(MUTED)),
                Span::styled(
                    format!(
                        "pid {} · instance {} · uptime {}",
                        app.server_identity.pid,
                        short_instance_id(&app.server_identity.instance_id),
                        format_uptime(app.server_identity.uptime_seconds),
                    ),
                    Style::default().fg(TEXT),
                ),
            ]),
            Line::from(vec![
                Span::styled("Checked   ", Style::default().fg(MUTED)),
                Span::styled(
                    app.last_check_label(),
                    Style::default().fg(if app.connection_state == ConnectionState::Running {
                        GOOD
                    } else {
                        WARN
                    }),
                ),
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
    let snapshot = app.catalog_snapshot();
    let opening = if app.is_bootstrap() && app.bootstrap_launch_after_repository() {
        "Choose the exact model, then select a repository to start FCC and Claude."
    } else if app.is_bootstrap() {
        "Prelaunch control: the server is stopped until you save choices and press Start server."
    } else {
        "The Rust control center is a thin client of fcc-server."
    };
    let body = Text::from(vec![
        Line::from(Span::styled(opening, Style::default().fg(TEXT))),
        Line::from(""),
        Line::from(vec![Span::styled("Context policy  ", Style::default().fg(MUTED)), Span::styled("FCC intervention disabled", Style::default().fg(WARN).add_modifier(Modifier::BOLD))]),
        Line::from(vec![Span::styled("Catalog         ", Style::default().fg(MUTED)), Span::styled(format!("{} route rows · Claude {} IDs · {} providers", snapshot.records.len(), snapshot.claude_registry_count(), snapshot.provider_options().len()), Style::default().fg(TEXT))]),
        Line::from(vec![Span::styled("Pending changes  ", Style::default().fg(MUTED)), Span::styled(compact_json(&pending), Style::default().fg(WARN))]),
        Line::from(vec![
            Span::styled("State detail    ", Style::default().fg(MUTED)),
            Span::styled(
                app.last_connection_error
                    .as_deref()
                    .unwrap_or("health check is passing"),
                Style::default().fg(if app.connection_state == ConnectionState::Running {
                    MUTED
                } else {
                    BAD
                }),
            ),
        ]),
        Line::from(""),
        Line::from(Span::styled("Click the sidebar to open a workspace. Models shows registered-provider routes: filter, inspect, enable, and choose one exact active model.", Style::default().fg(MUTED))),
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
            if app.is_bootstrap() && app.bootstrap_launch_after_repository() {
                ("Repositories", UiAction::Navigate(Page::Repositories))
            } else if app.is_bootstrap() {
                ("Start server", UiAction::StartServer)
            } else {
                ("Launch Claude", UiAction::LaunchClaude(false))
            },
            if !app.is_bootstrap() {
                ("Danger launch", UiAction::LaunchClaude(true))
            } else if app.bootstrap_launch_after_repository() {
                ("Models", UiAction::Navigate(Page::Models))
            } else {
                ("Save models", UiAction::SaveModels)
            },
        ],
    );
}

fn render_providers(frame: &mut Frame, app: &mut App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(9), Constraint::Length(5)])
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
            Constraint::Length(4),
            Constraint::Min(9),
            Constraint::Length(5),
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
    let catalog_label = if app.browser.show_catalog {
        "Active only"
    } else {
        "Show catalog"
    };
    let access_label = app
        .selected_model()
        .map(|model| {
            if app.browser.is_enabled(&model) {
                "Disable selected"
            } else {
                "Enable selected"
            }
        })
        .unwrap_or("Enable selected");
    let final_action = if app.is_bootstrap() && app.bootstrap_launch_after_repository() {
        ("Repositories", UiAction::Navigate(Page::Repositories))
    } else if app.is_bootstrap() {
        ("Start server", UiAction::StartServer)
    } else {
        ("Refresh", UiAction::Refresh)
    };
    let actions = vec![
        ("Use selected", UiAction::AssignModel(MODEL_KEY.to_string())),
        ("Context", UiAction::ConfigureContext),
        (access_label, UiAction::ToggleModelAccess),
        ("Disable all", UiAction::DisableAllModels),
        ("Save", UiAction::SaveModels),
        ("Undo", UiAction::DiscardModels),
        (catalog_label, UiAction::ToggleCatalogVisibility),
        final_action,
    ];
    action_bar(frame, app, rows[2], &actions);
}

fn render_model_toolbar(frame: &mut Frame, app: &mut App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(2), Constraint::Length(2)])
        .split(area);
    let snapshot = app.catalog_snapshot();
    let query = if app.browser.query.is_empty() {
        if app.browser.search_focused {
            "▌".to_string()
        } else {
            "Search model or provider…  (/)".to_string()
        }
    } else if app.browser.search_focused {
        format!("{}▌", app.browser.query)
    } else {
        format!("Filter: {}", app.browser.query)
    };
    let search_style = if app.browser.search_focused {
        Style::default().fg(TEXT).bg(ACCENT_DIM)
    } else {
        Style::default().fg(TEXT).bg(PANEL_2)
    };
    let active_model = if app.browser.pending_model().trim().is_empty() {
        "not set".to_string()
    } else {
        app.browser.pending_model().to_string()
    };
    let selected_model = app.selected_model().unwrap_or_else(|| "none".to_string());
    let provider_options = snapshot.provider_filter_options();
    frame.render_widget(
        Paragraph::new(Text::from(vec![
            Line::from(vec![
                Span::styled(
                    "MODEL CATALOG  ",
                    Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
                ),
                Span::styled(query, search_style),
            ]),
            Line::from(vec![
                Span::styled("ACTIVE  ", Style::default().fg(MUTED)),
                Span::styled(trim_to(&active_model, 28), Style::default().fg(TEXT)),
                Span::styled("  ·  SELECTED  ", Style::default().fg(MUTED)),
                Span::styled(trim_to(&selected_model, 28), Style::default().fg(ACCENT)),
            ]),
        ]))
        .style(Style::default().bg(PANEL_2)),
        chunks[0],
    );
    app.hitboxes.push(Hitbox {
        rect: chunks[0],
        action: UiAction::SearchModels,
    });

    let mut x = chunks[1].x + 1;
    let chip_y = chunks[1].y;
    let provider_label = match &app.browser.provider_filter {
        Some(provider) => provider_options
            .iter()
            .find(|option| option.id.eq_ignore_ascii_case(provider))
            .map(|option| format!("Provider: {}", option.label))
            .unwrap_or_else(|| format!("Provider: {provider}")),
        None => "Providers: registered".to_string(),
    };
    let free_label = if app.browser.price_filter == PriceFilter::Free {
        "Free only ✓".to_string()
    } else {
        "Free only".to_string()
    };
    let chips: Vec<(String, UiAction, bool)> = vec![
        (
            provider_label,
            UiAction::OpenProviderFilter,
            app.browser.provider_filter.is_some(),
        ),
        (
            free_label,
            UiAction::ToggleFreeFilter,
            app.browser.price_filter == PriceFilter::Free,
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
        let provider_label = app.browser.provider_filter.as_ref().and_then(|provider| {
            snapshot
                .provider_options()
                .into_iter()
                .find(|(id, _)| id.eq_ignore_ascii_case(provider))
                .map(|(_, label)| label)
        });
        let provider_records = app.browser.provider_filter.as_ref().map_or_else(
            || {
                snapshot
                    .records
                    .iter()
                    .filter(|record| snapshot.provider_is_registered(&record.provider_id))
                    .count()
            },
            |provider| {
                snapshot
                    .records
                    .iter()
                    .filter(|record| {
                        record.provider_id.eq_ignore_ascii_case(provider)
                            && snapshot.provider_is_registered(&record.provider_id)
                    })
                    .count()
            },
        );
        let search = app.browser.query.trim();
        let message = if snapshot.records.is_empty() {
            "No models discovered. Press Refresh to query configured providers.".to_string()
        } else if !search.is_empty() {
            let scope = provider_label
                .as_deref()
                .map(|label| format!(" for {label}"))
                .unwrap_or_default();
            format!(
                "No models match ‘{}’{}. Clear search or choose another provider.",
                trim_to(search, 40),
                scope
            )
        } else if app.browser.price_filter == PriceFilter::Free {
            let scope = provider_label
                .as_deref()
                .map(|label| format!(" for {label}"))
                .unwrap_or_default();
            format!(
                "No models{scope} have explicit FREE evidence. Clear Free only or choose a provider with FREE models."
            )
        } else if let Some(label) = provider_label {
            if provider_records == 0 {
                format!(
                    "No cached models for {label}. Press Refresh after configuring this provider."
                )
            } else if !app.browser.show_catalog {
                format!(
                    "No active models for {label}. Choose Show catalog to inspect blocked rows."
                )
            } else {
                format!("No models match the current filters for {label}.")
            }
        } else if !app.browser.show_catalog {
            "No active models match these filters. Choose Show catalog or clear the current filters."
                .to_string()
        } else {
            "No models match these filters. Clear the current filters.".to_string()
        };
        frame.render_widget(
            Paragraph::new(message)
                .wrap(Wrap { trim: true })
                .style(Style::default().fg(MUTED)),
            inner,
        );
        return;
    }
    let snapshot = app.catalog_snapshot();
    let mut display: Vec<(Option<String>, Option<usize>)> = Vec::new();
    let mut last_provider = String::new();
    let grouped = true;
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
        let is_active_model = app.browser.is_active_model(model);
        let marker = format!(
            "{} {}",
            if is_active_model { "→" } else { " " },
            if enabled { "✓" } else { "○" },
        );
        let price_badge = match price {
            PriceState::Free => " [FREE]",
            PriceState::Paid => " [PAID]",
            PriceState::Unknown => "",
        };
        let exact_ref = record
            .map(|item| item.model_ref.as_str())
            .unwrap_or(model.as_str());
        let row_label = if label == exact_ref {
            format!("{label}{price_badge}")
        } else {
            format!("{label}{price_badge}  ·  {exact_ref}")
        };
        let style = if selected {
            Style::default()
                .bg(ACCENT_DIM)
                .fg(TEXT)
                .add_modifier(Modifier::BOLD)
        } else if is_active_model {
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
            Paragraph::new(format!("{} {}", prefix, trim_to(&row_label, available))).style(style),
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
    let enabled = app.browser.is_enabled(model);
    let is_active_model = app.browser.is_active_model(model);
    let unavailable = app.browser.active_model_unavailable(&snapshot) && is_active_model;
    let price = record.map(|item| item.price).unwrap_or(PriceState::Unknown);
    let status = if unavailable {
        "→ Active model unavailable"
    } else if is_active_model && enabled {
        "→ Active model · ✓ Enabled"
    } else if is_active_model {
        "→ Active model"
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
    ];
    if let Some(record) = record {
        lines.push(kv("Provider", &record.provider_label));
    }
    lines.extend([
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
    ]);
    if price == PriceState::Paid {
        lines.push(kv("Cost", "PAID"));
    }
    lines.push(Line::from(""));
    if is_active_model && enabled {
        lines.push(Line::from(Span::styled(
            "This exact route is active. Use another row before disabling it.",
            Style::default().fg(MUTED),
        )));
    } else if is_active_model {
        lines.push(Line::from(Span::styled(
            "This exact route remains active even when access is cleared.",
            Style::default().fg(MUTED),
        )));
    } else if enabled {
        lines.push(Line::from(Span::styled(
            "Access is enabled. Use selected makes this the active route.",
            Style::default().fg(MUTED),
        )));
    } else {
        lines.push(Line::from(Span::styled(
            "Access is disabled. Enable selected before using this route.",
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
        .constraints([
            Constraint::Min(if page == Page::Routing { 9 } else { 10 }),
            Constraint::Length(if page == Page::Routing { 5 } else { 4 }),
        ])
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
    let routing_target = if page == Page::Routing {
        Some(
            app.selected_model()
                .unwrap_or_else(|| "none — choose a model on Models tab".to_string()),
        )
    } else {
        None
    };
    render_field_detail(frame, field.as_ref(), panes[1], routing_target.as_deref());
    let mut actions = Vec::new();
    if page == Page::Routing {
        actions.extend([
            ("Active model", UiAction::AssignRoute(MODEL_KEY.to_string())),
            ("Fable", UiAction::AssignRoute("MODEL_FABLE".to_string())),
            ("Opus", UiAction::AssignRoute("MODEL_OPUS".to_string())),
            ("Sonnet", UiAction::AssignRoute("MODEL_SONNET".to_string())),
            ("Haiku", UiAction::AssignRoute("MODEL_HAIKU".to_string())),
            ("Models tab", UiAction::Navigate(Page::Models)),
        ]);
    }
    actions.extend([
        ("Edit", UiAction::EditField),
        ("Refresh", UiAction::Refresh),
    ]);
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
        Page::Settings => "App settings",
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

fn render_field_detail(
    frame: &mut Frame,
    field: Option<&ConfigField>,
    area: Rect,
    routing_target: Option<&str>,
) {
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
    ];
    if let Some(target) = routing_target {
        lines.push(kv("Selected model", target));
        lines.push(Line::from(Span::styled(
            "Routing buttons assign this selected Models-tab row.",
            Style::default().fg(MUTED),
        )));
        lines.push(Line::from(""));
    }
    lines.extend([
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
    ]);
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
    let block = section_block("Claude Code context window");
    let inner = block.inner(rows[0]);
    frame.render_widget(block, rows[0]);
    let model = app.selected_model().unwrap_or_else(|| "none".to_string());
    let configured = app
        .config
        .fields
        .iter()
        .find(|field| field.key == "MODEL_CONTEXT_WINDOWS")
        .map(|field| field.value.as_str())
        .unwrap_or("{}");
    let current = serde_json::from_str::<serde_json::Value>(configured)
        .ok()
        .and_then(|value| value.get(&model).and_then(serde_json::Value::as_u64))
        .map(|value| format!("{value} tokens"))
        .unwrap_or_else(|| "client default (no override)".to_string());
    let lines = vec![
        Line::from(Span::styled("SELECT A MODEL", Style::default().fg(MUTED).add_modifier(Modifier::BOLD))),
        Line::from(Span::styled(trim_to(&model, inner.width as usize), Style::default().fg(ACCENT))),
        Line::from(""),
        kv("Configured window", &current),
        Line::from(""),
        Line::from(Span::styled("Up/Down selects the exact provider/model reference. Enter or E opens presets, Custom accepts 32K–1M tokens, and Clear removes only this model's override. Saved values set Claude Code's context and auto-compact window; native ultracode remains client-owned.", Style::default().fg(TEXT))),
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
            ("Configure selected", UiAction::ConfigureContext),
            ("Models", UiAction::Navigate(Page::Models)),
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
            trim_to(error, area.width.saturating_sub(2) as usize),
            Style::default().fg(BAD).add_modifier(Modifier::BOLD),
        )
    } else if let Some(notice) = &app.notice {
        Span::styled(
            trim_to(notice, area.width.saturating_sub(2) as usize),
            Style::default().fg(GOOD),
        )
    } else {
        Span::styled(
            "^K Palette · R Refresh · C Claude · ? Help · Q Quit",
            Style::default().fg(MUTED),
        )
    };
    frame.render_widget(
        Paragraph::new(Line::from(message))
            .style(Style::default().bg(PANEL))
            .block(top_border()),
        area,
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
    let button_height = if actions.len() > 6 { 1 } else { 2 };
    let mut x = area.x + 1;
    let mut y = area.y + 1;
    for (label, action) in actions {
        let desired_width = label.chars().count() as u16 + 4;
        if x > area.x + 1 && x.saturating_add(desired_width) > area.right() {
            x = area.x + 1;
            y = y.saturating_add(button_height);
        }
        if y >= area.bottom() || x >= area.right() {
            break;
        }
        let width = desired_width.min(area.right().saturating_sub(x));
        if width < 5 {
            break;
        }
        let button = Rect {
            x,
            y,
            width,
            height: button_height.min(area.bottom().saturating_sub(y)),
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

fn render_modal(frame: &mut Frame, app: &mut App, area: Rect) {
    let Some(modal) = app.modal.clone() else {
        return;
    };
    let rect = centered(
        area,
        76,
        match &modal {
            Modal::ProviderEditor { .. } => 24,
            Modal::ProviderPicker { options, .. } => (options.len() as u16 + 4).min(24),
            Modal::Palette { .. } => 20,
            Modal::FieldPicker { field_indices, .. } => (field_indices.len() as u16 + 6).min(24),
            Modal::Choice { options, .. } | Modal::ContextChoice { options, .. } => {
                (options.len() as u16 + 6).min(22)
            }
            _ => 14,
        },
    );
    frame.render_widget(Clear, rect);
    frame.render_widget(Block::default().style(Style::default().bg(PANEL)), rect);
    match &modal {
        Modal::ContextInput { model_ref, input } => {
            render_context_input_modal(frame, rect, model_ref, input)
        }
        Modal::ContextChoice {
            model_ref,
            options,
            selected,
        } => render_choice_modal(frame, rect, model_ref, options, *selected),
        Modal::EditField { field, input } => render_edit_modal(frame, rect, field, input),
        Modal::Choice {
            label,
            options,
            selected,
            ..
        } => render_choice_modal(frame, rect, label, options, *selected),
        Modal::FieldPicker {
            title,
            field_indices,
            selected,
        } => render_field_picker(frame, app, rect, title, field_indices, *selected),
        Modal::ProviderEditor {
            existing_id,
            draft,
            selected,
            editing,
        } => render_provider_editor(
            frame,
            rect,
            existing_id.as_deref(),
            draft,
            *selected,
            editing.as_ref(),
        ),
        Modal::ProviderPicker { options, selected } => {
            render_provider_picker(frame, app, rect, options, *selected)
        }
        Modal::Palette { input, selected } => {
            render_palette(frame, app, rect, &input.value, *selected)
        }
        Modal::Confirm { title, body, .. } => render_message_box(
            frame,
            rect,
            title,
            &format!("{body}\n\nEnter/Y confirms · Esc/N cancels"),
            WARN,
        ),
        Modal::Message { title, body } => render_message_box(frame, rect, title, body, TEXT),
    }
}

fn render_palette(frame: &mut Frame, app: &mut App, rect: Rect, query: &str, selected: usize) {
    let block = modal_block("Command palette");
    let inner = block.inner(rect);
    frame.render_widget(block, rect);

    let query_row = Rect {
        x: inner.x,
        y: inner.y,
        width: inner.width,
        height: 1,
    };
    frame.render_widget(
        Paragraph::new(format!("> {query}")).style(Style::default().fg(TEXT).bg(BG)),
        query_row,
    );

    let inventory = app.palette_inventory();
    let visible = match_palette(query, &inventory);
    let list_height = inner.height.saturating_sub(3) as usize;
    let offset = list_offset(selected, visible.len(), list_height);
    for (row_index, entry_index) in visible.iter().skip(offset).take(list_height).enumerate() {
        let display_index = offset + row_index;
        let entry = &inventory[*entry_index];
        let row = Rect {
            x: inner.x,
            y: inner.y + 2 + row_index as u16,
            width: inner.width,
            height: 1,
        };
        let style = if display_index == selected {
            Style::default()
                .fg(TEXT)
                .bg(ACCENT_DIM)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(TEXT).bg(PANEL)
        };
        let label = format!(
            "{}{}  ·  {}",
            if display_index == selected {
                "▌ "
            } else {
                "  "
            },
            entry.title,
            entry.hint
        );
        frame.render_widget(
            Paragraph::new(trim_to(&label, inner.width as usize)).style(style),
            row,
        );
    }

    let hint = if visible.is_empty() {
        "No matching commands · Esc closes"
    } else {
        "Type to filter · ↑↓/Ctrl-P/Ctrl-N move · Enter runs · Esc closes"
    };
    frame.render_widget(
        Paragraph::new(hint).style(Style::default().fg(MUTED)),
        Rect {
            x: inner.x,
            y: inner.bottom().saturating_sub(1),
            width: inner.width,
            height: 1,
        },
    );
}

fn render_provider_picker(
    frame: &mut Frame,
    app: &mut App,
    rect: Rect,
    options: &[crate::models::ProviderFilterOption],
    selected: usize,
) {
    let block = modal_block("Registered providers");
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    let height = inner.height as usize;
    let offset = list_offset(selected, options.len(), height);
    for (visible, option) in options.iter().skip(offset).take(height).enumerate() {
        let index = offset + visible;
        let row = Rect {
            x: inner.x,
            y: inner.y + visible as u16,
            width: inner.width,
            height: 1,
        };
        let free = if option.free_count == 0 {
            "no explicit FREE".to_string()
        } else {
            format!("{} FREE", option.free_count)
        };
        let label = format!(
            "{}{}  ·  {} models  ·  {}  ·  {}",
            if index == selected { "▌ " } else { "  " },
            option.label,
            option.model_count,
            free,
            option.status
        );
        let style = if index == selected {
            Style::default()
                .fg(TEXT)
                .bg(ACCENT_DIM)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(TEXT).bg(PANEL)
        };
        frame.render_widget(
            Paragraph::new(trim_to(&label, inner.width as usize)).style(style),
            row,
        );
        app.hitboxes.push(Hitbox {
            rect: row,
            action: UiAction::SelectProviderFilter(index),
        });
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

fn render_context_input_modal(
    frame: &mut Frame,
    rect: Rect,
    model_ref: &str,
    input: &crate::app::TextInput,
) {
    let block = modal_block("Custom context tokens");
    let inner = block.inner(rect);
    frame.render_widget(block, rect);
    frame.render_widget(
        Paragraph::new(input.value.clone())
            .style(Style::default().fg(TEXT).bg(BG))
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(ACCENT)),
            ),
        Rect {
            x: inner.x,
            y: inner.y + 1,
            width: inner.width,
            height: 3,
        },
    );
    frame.render_widget(
        Paragraph::new(format!(
            "{}\n32K–1M · Enter saves · Esc cancels",
            trim_to(model_ref, inner.width as usize)
        ))
        .style(Style::default().fg(MUTED)),
        Rect {
            x: inner.x,
            y: inner.bottom().saturating_sub(3),
            width: inner.width,
            height: 3,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::{
        AdminClient, BootstrapState, ConfigField, ConfigOption, CustomProvider, ModelsResponse,
        ProviderStatus, Repository, MASKED_SECRET,
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
                label: "Active model".to_string(),
                field_type: "text".to_string(),
                value: "open_router/openrouter/free".to_string(),
                configured: true,
                source: "managed_env".to_string(),
                description: "Active route".to_string(),
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
                label: "Active model".to_string(),
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
            Modal::ProviderPicker {
                options: vec![
                    crate::models::ProviderFilterOption {
                        id: String::new(),
                        label: "Registered providers".to_string(),
                        status: "active".to_string(),
                        model_count: 1,
                        free_count: 1,
                    },
                    crate::models::ProviderFilterOption {
                        id: "open_router".to_string(),
                        label: "OpenRouter".to_string(),
                        status: "configured".to_string(),
                        model_count: 1,
                        free_count: 1,
                    },
                ],
                selected: 0,
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
            .any(|hitbox| matches!(hitbox.action, UiAction::ToggleFreeFilter)));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::SelectModel(0))));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::AssignModel(_))));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::DisableAllModels)));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::ToggleCatalogVisibility)));
        assert!(!app.hitboxes.iter().any(|hitbox| {
            matches!(
                hitbox.action,
                UiAction::AssignModel(ref key) if key != MODEL_KEY
            )
        }));
    }

    #[test]
    fn compact_models_page_keeps_bulk_disable_action_visible_and_routes_are_separate() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/one".to_string(), "provider/two".to_string()];
        app.models.catalog_models = app.models.models.clone();
        app.sync_model_browser();

        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();

        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::DisableAllModels)));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::ToggleCatalogVisibility)));
        assert!(!app.hitboxes.iter().any(|hitbox| {
            matches!(
                hitbox.action,
                UiAction::AssignModel(ref key) if key != MODEL_KEY
            )
        }));
        assert!(!app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::AssignRoute(_))));

        app.page = Page::Routing;
        app.hitboxes.clear();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        for key in [
            "MODEL",
            "MODEL_FABLE",
            "MODEL_OPUS",
            "MODEL_SONNET",
            "MODEL_HAIKU",
        ] {
            assert!(app.hitboxes.iter().any(|hitbox| {
                matches!(
                    &hitbox.action,
                    UiAction::AssignRoute(route) if route == key
                )
            }));
        }
    }

    #[test]
    fn dashboard_renders_operational_server_metadata_and_failure_detail() {
        let mut app = App::fixture();
        app.server_identity.health_url = "http://127.0.0.1:8083/health".to_string();
        app.server_identity.instance_id = "0123456789abcdef".to_string();
        app.server_identity.pid = 12345;
        app.server_identity.uptime_seconds = 3661.0;
        app.connection_state = ConnectionState::Offline;
        app.last_connection_error = Some("connection refused".to_string());

        let mut terminal = Terminal::new(TestBackend::new(160, 50)).unwrap();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        let rendered = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();

        assert!(rendered.contains("Endpoint"));
        assert!(rendered.contains("127.0.0.1:8083/health"));
        assert!(rendered.contains("pid 12345"));
        assert!(rendered.contains("instance 01234567"));
        assert!(rendered.contains("uptime 1h 1m"));
        assert!(rendered.contains("OFFLINE"));
        assert!(rendered.contains("connection refused"));
    }

    #[test]
    fn compact_models_page_has_no_overlapping_controls_or_default_metadata() {
        let mut app = App::from_bootstrap(
            AdminClient::new("http://127.0.0.1:8082").unwrap(),
            BootstrapState::default(),
            None,
            std::env::temp_dir().join("fcc-control-center-ui-test-result.json"),
        );
        app.page = Page::Models;
        app.models.models = vec!["provider/one".to_string(), "provider/two".to_string()];
        app.models.catalog_models = app.models.models.clone();
        app.sync_model_browser();

        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();

        assert!(app
            .hitboxes
            .iter()
            .all(|hitbox| hitbox.rect.bottom() <= app.geometry.footer.y));
        assert!(app
            .hitboxes
            .iter()
            .all(|hitbox| hitbox.rect.right() <= terminal.backend().buffer().area.right()));
        assert!(app.hitboxes.iter().any(
            |hitbox| matches!(hitbox.action, UiAction::AssignModel(ref key) if key == MODEL_KEY)
        ));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::StartServer)));

        let rendered = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(rendered.contains("Use selected"));
        assert!(!rendered.contains("DEFAULT"));
        assert!(!rendered.contains("Capabilities"));
    }

    #[test]
    fn repositories_page_exposes_real_selection_and_launch_actions() {
        let mut app = App::fixture();
        app.page = Page::Repositories;
        app.repositories = vec![Repository {
            name: "switchboard".to_string(),
            path: "/Users/tejas/Projects/AgentSwitchboard".to_string(),
            branch: "main".to_string(),
            remote: "tverma101/AgentSwitchboard".to_string(),
            display_path: "~/Projects/AgentSwitchboard".to_string(),
            identity: "tverma101/AgentSwitchboard".to_string(),
        }];
        app.selected_repo_path = Some(app.repositories[0].path.clone());

        let mut terminal = Terminal::new(TestBackend::new(160, 50)).unwrap();
        terminal.draw(|frame| render(frame, &mut app)).unwrap();

        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::SelectRepository(0))));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::UseRepository)));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::RefreshRepositories)));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::LaunchClaude(false))));
        assert!(app
            .hitboxes
            .iter()
            .any(|hitbox| matches!(hitbox.action, UiAction::LaunchClaude(true))));
    }

    #[test]
    fn palette_keeps_reference_chrome_geometry() {
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut app = App::fixture();
        app.modal = Some(Modal::Palette {
            input: crate::app::TextInput::new("provider".to_string(), false, false),
            selected: 0,
        });
        terminal.draw(|frame| render(frame, &mut app)).unwrap();
        assert_eq!(app.geometry.top.height, 3);
        assert_eq!(app.geometry.sidebar.width, 28);
        assert_eq!(app.geometry.footer.height, 2);
        assert_eq!(app.geometry.main.width, 132);
    }
}
