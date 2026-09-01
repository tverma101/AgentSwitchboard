mod api;
mod app;
mod ui;

use anyhow::{bail, Context, Result};
use api::AdminClient;
use app::{App, ExternalAction};
use crossterm::event::{self, DisableMouseCapture, EnableMouseCapture};
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;
use std::env;
use std::io::{self, Stdout};
use std::process::Command;
use std::time::Duration;

struct Args {
    base_url: String,
    notice: Option<String>,
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
    let api = AdminClient::new(&args.base_url)?;
    let mut app = App::load(api, args.notice).context("could not load FCC Admin state")?;
    let mut terminal = setup_terminal()?;
    let result = run_loop(&mut terminal, &mut app);
    let restore_result = restore_terminal(&mut terminal);
    result.and(restore_result)
}

fn parse_args() -> Result<Args> {
    let mut base_url = "http://127.0.0.1:8082".to_string();
    let mut notice = None;
    let mut args = env::args().skip(1);
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--base-url" => {
                base_url = args.next().context("--base-url requires a value")?;
            }
            "--notice" => {
                notice = Some(args.next().context("--notice requires a value")?);
            }
            "--help" | "-h" => {
                println!(
                    "AgentSwitchboard native control center\n\nUsage: fcc-control-center [--base-url URL] [--notice TEXT]\n\nThe Admin URL must be loopback. The UI never reads provider secrets back from fcc-server."
                );
                std::process::exit(0);
            }
            unknown => bail!("unknown argument: {unknown}"),
        }
    }
    Ok(Args { base_url, notice })
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
    loop {
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
    let result = Command::new(command).status();
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
