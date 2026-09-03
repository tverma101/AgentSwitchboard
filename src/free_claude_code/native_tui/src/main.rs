mod api;
mod app;
mod models;
mod ui;

use anyhow::{bail, Context, Result};
use api::{AdminClient, BootstrapState};
use app::{App, ExternalAction};
use crossterm::event::{self, DisableMouseCapture, EnableMouseCapture};
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;
use std::env;
use std::fs;
use std::io::{self, Stdout};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

struct Args {
    base_url: String,
    expected_mode: String,
    notice: Option<String>,
    bootstrap_state: Option<PathBuf>,
    bootstrap_result: Option<PathBuf>,
}

type NativeTerminal = Terminal<CrosstermBackend<Stdout>>;

fn main() {
    if let Err(error) = real_main() {
        eprintln!("fcc-control-center: {error:#}");
        std::process::exit(1);
    }
}

fn real_main() -> Result<()> {
    let args = parse_args()?;
    let api = AdminClient::new(&args.base_url)?.with_expected_mode(args.expected_mode);
    let mut app = match (args.bootstrap_state, args.bootstrap_result) {
        (Some(state_path), Some(result_path)) => {
            let state: BootstrapState = serde_json::from_str(
                &fs::read_to_string(&state_path)
                    .with_context(|| format!("could not read bootstrap state: {state_path:?}"))?,
            )
            .with_context(|| format!("could not decode bootstrap state: {state_path:?}"))?;
            App::from_bootstrap(api, state, args.notice, result_path)
        }
        (None, None) => App::load(api, args.notice).context("could not load FCC Admin state")?,
        _ => bail!("--bootstrap-state and --bootstrap-result must be used together"),
    };
    let mut terminal = setup_terminal()?;
    let result = run_loop(&mut terminal, &mut app);
    let restore_result = restore_terminal(&mut terminal);
    let write_result = app.write_bootstrap_result();
    result.and(restore_result).and(write_result)
}

fn parse_args() -> Result<Args> {
    let mut base_url = "http://127.0.0.1:8082".to_string();
    let mut expected_mode = "standard".to_string();
    let mut notice = None;
    let mut bootstrap_state = None;
    let mut bootstrap_result = None;
    let mut args = env::args().skip(1);
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--base-url" => {
                base_url = args.next().context("--base-url requires a value")?;
            }
            "--expected-mode" => {
                expected_mode = args.next().context("--expected-mode requires a value")?;
            }
            "--notice" => {
                notice = Some(args.next().context("--notice requires a value")?);
            }
            "--bootstrap-state" => {
                bootstrap_state = Some(PathBuf::from(
                    args.next().context("--bootstrap-state requires a value")?,
                ));
            }
            "--bootstrap-result" => {
                bootstrap_result = Some(PathBuf::from(
                    args.next().context("--bootstrap-result requires a value")?,
                ));
            }
            "--help" | "-h" => {
                println!(
                    "AgentSwitchboard native control center\n\nUsage: fcc-control-center [--base-url URL] [--expected-mode MODE] [--notice TEXT] [--bootstrap-state PATH --bootstrap-result PATH]\n\nThe Admin URL must be loopback. Bootstrap mode lets fcc-server prepare the catalog before opening HTTP. Secrets are never included in the bootstrap snapshot."
                );
                std::process::exit(0);
            }
            unknown => bail!("unknown argument: {unknown}"),
        }
    }
    Ok(Args {
        base_url,
        expected_mode,
        notice,
        bootstrap_state,
        bootstrap_result,
    })
}

fn setup_terminal() -> Result<NativeTerminal> {
    enable_raw_mode().context("could not enable terminal raw mode")?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)
        .context("could not enter alternate terminal screen")?;
    let backend = CrosstermBackend::new(stdout);
    Terminal::new(backend).context("could not create terminal backend")
}

fn restore_terminal(terminal: &mut NativeTerminal) -> Result<()> {
    disable_raw_mode().context("could not disable terminal raw mode")?;
    execute!(
        terminal.backend_mut(),
        DisableMouseCapture,
        LeaveAlternateScreen
    )
    .context("could not leave alternate terminal screen")?;
    terminal
        .show_cursor()
        .context("could not restore terminal cursor")?;
    Ok(())
}

fn suspend_terminal(terminal: &mut NativeTerminal) -> Result<()> {
    disable_raw_mode().context("could not suspend terminal raw mode")?;
    execute!(
        terminal.backend_mut(),
        DisableMouseCapture,
        LeaveAlternateScreen
    )
    .context("could not suspend control center")?;
    terminal.show_cursor().context("could not restore cursor")?;
    Ok(())
}

fn resume_terminal(terminal: &mut NativeTerminal) -> Result<()> {
    enable_raw_mode().context("could not resume terminal raw mode")?;
    execute!(
        terminal.backend_mut(),
        EnterAlternateScreen,
        EnableMouseCapture
    )
    .context("could not resume control center")?;
    Ok(())
}

fn run_loop(terminal: &mut NativeTerminal, app: &mut App) -> Result<()> {
    let mut next_health_check = Instant::now();
    loop {
        if !app.is_bootstrap() && Instant::now() >= next_health_check {
            app.refresh_health();
            next_health_check = Instant::now() + Duration::from_secs(2);
        }
        terminal
            .draw(|frame| ui::render(frame, app))
            .context("terminal draw failed")?;
        if app.should_quit {
            return Ok(());
        }
        if !event::poll(Duration::from_millis(200)).context("terminal event poll failed")? {
            continue;
        }
        let event = event::read().context("terminal event read failed")?;
        if let Some(action) = app.handle_event(event)? {
            match action {
                ExternalAction::LaunchClaude { danger } => {
                    launch_claude(terminal, app, danger)?;
                }
            }
        }
    }
}

fn launch_claude(terminal: &mut NativeTerminal, app: &mut App, danger: bool) -> Result<()> {
    let command = if danger { "fccdanger" } else { "fcc-claude" };
    suspend_terminal(terminal)?;
    let mut child = Command::new(command);
    if let Some(path) = app.launch_repository_path() {
        child.current_dir(Path::new(path));
    }
    let result = child.status();
    let resume = resume_terminal(terminal);
    match result {
        Ok(status) if status.success() => {
            app.set_notice(format!("{command} exited normally"));
            app.refresh_all();
        }
        Ok(status) => app.set_error(format!("{command} exited with status {status}")),
        Err(error) => app.set_error(format!("Could not launch {command}: {error}")),
    }
    resume
}
