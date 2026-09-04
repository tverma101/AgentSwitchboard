mod api;
mod app;
mod theme;
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
    workspace: Option<String>,
    open: Vec<String>,
    line: Option<usize>,
    launch_args: Vec<String>,
    launch_cwd: Option<String>,
    launch_danger: bool,
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
    // Ask the enclosing terminal for its palette (donor: terminal/osc.ts) so
    // the "Terminal Code" theme matches the user's terminal. Silent terminals
    // settle to the built-in fallback palette instead of blocking startup.
    let palette = theme::with_fallbacks(theme::query_terminal());
    let mut app = App::load(api, args.notice.clone()).context("could not load FCC Admin state")?;
    app.colors = theme::Colors::generate(&palette);
    if let Some(workspace) = args.workspace.as_deref() {
        app.set_workspace(std::path::PathBuf::from(workspace));
    }
    for path in &args.open {
        app.open_file(std::path::PathBuf::from(path), args.line);
    }
    let mut terminal = setup_terminal()?;
    let result = run_loop(&mut terminal, &mut app, &args);
    let restore_result = restore_terminal(&mut terminal);
    result.and(restore_result)
}

fn parse_args() -> Result<Args> {
    let mut base_url = "http://127.0.0.1:8082".to_string();
    let mut notice = None;
    let mut workspace = None;
    let mut open: Vec<String> = Vec::new();
    let mut line = None;
    let mut launch_args: Vec<String> = Vec::new();
    let mut launch_cwd = None;
    let mut launch_danger = false;
    let mut args = env::args().skip(1);
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--base-url" => {
                base_url = args.next().context("--base-url requires a value")?;
            }
            "--notice" => {
                notice = Some(args.next().context("--notice requires a value")?);
            }
            "--workspace" => {
                workspace = Some(args.next().context("--workspace requires a value")?);
            }
            "--open" => {
                open.push(args.next().context("--open requires a value")?);
            }
            "--line" => {
                let raw = args.next().context("--line requires a value")?;
                line = Some(raw.parse().context("--line must be a number")?);
            }
            "--launch-arg" => {
                launch_args.push(args.next().context("--launch-arg requires a value")?);
            }
            "--launch-cwd" => {
                launch_cwd = Some(args.next().context("--launch-cwd requires a value")?);
            }
            "--launch-danger" => launch_danger = true,
            "--help" | "-h" => {
                println!(
                    "AgentSwitchboard native control center\n\nUsage: fcc-control-center [--base-url URL] [--notice TEXT] [--workspace DIR] [--open FILE]... [--line N]\n\nThe Admin URL must be loopback. The UI never reads provider secrets back from fcc-server."
                );
                std::process::exit(0);
            }
            unknown => bail!("unknown argument: {unknown}"),
        }
    }
    Ok(Args {
        base_url,
        notice,
        workspace,
        open,
        line,
        launch_args,
        launch_cwd,
        launch_danger,
    })
}

fn setup_terminal() -> Result<NativeTerminal> {
    enable_raw_mode().context("could not enable terminal raw mode")?;
    let mut stdout = io::stdout();
    if let Err(error) = execute!(stdout, EnterAlternateScreen, EnableMouseCapture) {
        let _ = disable_raw_mode();
        return Err(error).context("could not enter alternate terminal screen");
    }
    let backend = CrosstermBackend::new(stdout);
    match Terminal::new(backend) {
        Ok(terminal) => Ok(terminal),
        Err(error) => {
            let mut stdout = io::stdout();
            let _ = execute!(stdout, DisableMouseCapture, LeaveAlternateScreen);
            let _ = disable_raw_mode();
            Err(error).context("could not create terminal backend")
        }
    }
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
    if let Err(error) = execute!(
        terminal.backend_mut(),
        EnterAlternateScreen,
        EnableMouseCapture
    ) {
        let _ = disable_raw_mode();
        return Err(error).context("could not resume control center");
    }
    Ok(())
}

fn run_loop(terminal: &mut NativeTerminal, app: &mut App, args: &Args) -> Result<()> {
    loop {
        app.poll_background();
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
                    launch_claude(terminal, app, args, danger)?;
                }
                ExternalAction::EditExternal { path } => {
                    launch_external_editor(terminal, app, &path)?;
                }
            }
        }
    }
}

fn launch_external_editor(
    terminal: &mut NativeTerminal,
    app: &mut App,
    path: &std::path::Path,
) -> Result<()> {
    let editor = std::env::var("EDITOR").unwrap_or_else(|_| "vi".to_string());
    suspend_terminal(terminal)?;
    let result = Command::new(&editor).arg(path).status();
    let resume = resume_terminal(terminal);
    match result {
        Ok(status) if status.success() => {
            app.set_notice(format!("{} exited normally", editor));
            app.refresh_all();
        }
        Ok(status) => app.set_error(format!("{editor} exited with status {status}")),
        Err(error) => app.set_error(format!("Could not launch {editor}: {error}")),
    }
    resume
}

fn launch_claude(
    terminal: &mut NativeTerminal,
    app: &mut App,
    args: &Args,
    danger: bool,
) -> Result<()> {
    let command = if danger { "fccdanger" } else { "fcc-claude" };
    let mut launch_args = args.launch_args.clone();
    if danger {
        if !launch_args
            .iter()
            .any(|argument| argument == "--dangerously-skip-permissions")
        {
            launch_args.insert(0, "--dangerously-skip-permissions".to_string());
        }
    } else if args.launch_danger {
        // A direct `fccdanger` invocation is held as pending context until the
        // user chooses a launch button. Choosing Normal must be a real safety
        // override, not a label over the original dangerous flag.
        launch_args.retain(|argument| argument != "--dangerously-skip-permissions");
    }
    let mut child = Command::new(command);
    child.args(&launch_args);
    // A checkout picked on the Repositories page wins over the folder the
    // control center started in.
    let cwd = app
        .launch_cwd()
        .or_else(|| args.launch_cwd.as_deref().map(std::path::PathBuf::from));
    if let Some(cwd) = cwd.as_deref() {
        child.current_dir(cwd);
    }
    suspend_terminal(terminal)?;
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
