use crate::api::{
    AdminClient, BootstrapState, ConfigField, ConfigOption, ConfigResponse, CustomProvider,
    CustomProviderPayload, ModelsResponse, ProviderStatus, RepositoriesResponse, Repository,
    ServerIdentity, MASKED_SECRET,
};
use crate::models::{
    verify_catalog_readback, CatalogSnapshot, ModelBrowser, ProviderFilterOption, MODEL_KEY,
};
use anyhow::Result;
use crossterm::event::{
    Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent, MouseEventKind,
};
use ratatui::layout::Rect;
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

#[cfg(unix)]
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

pub const CONTEXT_KEY: &str = "FCC_CLAUDE_CONTEXT_TOKENS";
const ROUTING_KEYS: &[&str] = &[
    "MODEL",
    "FCC_SUBAGENT_MODEL_INHERIT",
    "MODEL_FABLE",
    "MODEL_OPUS",
    "MODEL_SONNET",
    "MODEL_HAIKU",
    "MODEL_CATALOG_MODE",
    "MODEL_CATALOG_ALLOWLIST",
    "MODEL_ALIASES",
    "FCC_CAPABILITY_ROUTING_MODE",
    "FCC_ALLOWED_HELPERS",
    "FCC_PAID_FALLBACK",
    "REASONING_POLICY",
    "REASONING_FABLE",
    "REASONING_OPUS",
    "REASONING_SONNET",
    "REASONING_HAIKU",
];
const LOCAL_KEYS: &[&str] = &[
    "LM_STUDIO_BASE_URL",
    "LLAMACPP_BASE_URL",
    "OLLAMA_BASE_URL",
    "OLLAMA_API_KEY",
];
const CUSTOM_PROVIDERS_KEY: &str = "CUSTOM_PROVIDERS_JSON";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Dashboard,
    Repositories,
    Providers,
    Models,
    Routing,
    Context,
    Local,
    Settings,
    Usage,
    Diagnostics,
}

impl Page {
    pub const ALL: [Self; 10] = [
        Self::Dashboard,
        Self::Repositories,
        Self::Providers,
        Self::Models,
        Self::Routing,
        Self::Context,
        Self::Local,
        Self::Settings,
        Self::Usage,
        Self::Diagnostics,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Dashboard => "Dashboard",
            Self::Repositories => "Repositories",
            Self::Providers => "Providers",
            Self::Models => "Models",
            Self::Routing => "Routing",
            Self::Context => "Context Window",
            Self::Local => "Local Setup",
            Self::Settings => "App Settings",
            Self::Usage => "Usage",
            Self::Diagnostics => "Diagnostics",
        }
    }

    fn index(self) -> usize {
        Self::ALL.iter().position(|item| *item == self).unwrap_or(0)
    }
}

#[derive(Debug, Clone)]
pub enum UiAction {
    Navigate(Page),
    SelectRepository(usize),
    SelectProvider(usize),
    SelectModel(usize),
    SelectRouting(usize),
    SelectLocal(usize),
    SelectSetting(usize),
    Refresh,
    UseRepository,
    RefreshRepositories,
    ConfigureProvider,
    TestProvider,
    NewCustomProvider,
    EditCustomProvider,
    DeleteCustomProvider,
    LoginProvider,
    DisconnectProvider,
    EditField,
    ToggleAdvanced,
    AssignModel(String),
    SearchModels,
    OpenProviderFilter,
    SelectProviderFilter(usize),
    ToggleFreeFilter,
    ToggleCatalogVisibility,
    ToggleModelAccess,
    DisableAllModels,
    SaveModels,
    DiscardModels,
    StartServer,
    AssignRoute(String),
    RunDiagnostic,
    LaunchClaude(bool),
}

#[derive(Debug, Clone)]
pub struct Hitbox {
    pub rect: Rect,
    pub action: UiAction,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Copy, Default)]
pub struct ChromeGeometry {
    pub top: Rect,
    pub sidebar: Rect,
    pub main: Rect,
    pub footer: Rect,
}

#[derive(Debug)]
pub enum ExternalAction {
    LaunchClaude { danger: bool },
}

#[derive(Debug, Clone)]
pub struct TextInput {
    pub value: String,
    pub cursor: usize,
    pub multiline: bool,
    pub secret: bool,
}

impl TextInput {
    pub fn new(value: String, multiline: bool, secret: bool) -> Self {
        let cursor = value.len();
        Self {
            value,
            cursor,
            multiline,
            secret,
        }
    }

    fn insert_char(&mut self, value: char) {
        self.value.insert(self.cursor, value);
        self.cursor += value.len_utf8();
    }

    fn backspace(&mut self) {
        if self.cursor == 0 {
            return;
        }
        let previous = previous_boundary(&self.value, self.cursor);
        self.value.replace_range(previous..self.cursor, "");
        self.cursor = previous;
    }

    fn delete(&mut self) {
        if self.cursor >= self.value.len() {
            return;
        }
        let next = next_boundary(&self.value, self.cursor);
        self.value.replace_range(self.cursor..next, "");
    }

    fn move_left(&mut self) {
        self.cursor = previous_boundary(&self.value, self.cursor);
    }

    fn move_right(&mut self) {
        self.cursor = next_boundary(&self.value, self.cursor);
    }
}

fn previous_boundary(value: &str, cursor: usize) -> usize {
    value[..cursor]
        .char_indices()
        .next_back()
        .map(|(index, _)| index)
        .unwrap_or(0)
}

fn next_boundary(value: &str, cursor: usize) -> usize {
    if cursor >= value.len() {
        return value.len();
    }
    value[cursor..]
        .char_indices()
        .nth(1)
        .map(|(index, _)| cursor + index)
        .unwrap_or(value.len())
}

#[derive(Debug, Clone)]
pub struct ProviderDraft {
    pub id: String,
    pub display_name: String,
    pub base_url: String,
    pub api_key: String,
    pub proxy: String,
    pub models: String,
    pub local: bool,
    pub enabled: bool,
    pub existing_has_key: bool,
    pub existing_has_proxy: bool,
}

impl ProviderDraft {
    fn empty() -> Self {
        Self {
            id: String::new(),
            display_name: String::new(),
            base_url: String::new(),
            api_key: String::new(),
            proxy: String::new(),
            models: String::new(),
            local: false,
            enabled: true,
            existing_has_key: false,
            existing_has_proxy: false,
        }
    }

    fn from_existing(provider: &CustomProvider) -> Self {
        Self {
            id: provider.provider_id.clone(),
            display_name: provider.display_name.clone(),
            base_url: provider.base_url.clone(),
            api_key: String::new(),
            proxy: String::new(),
            models: provider.model_ids.join(", "),
            local: provider.local,
            enabled: provider.enabled,
            existing_has_key: provider.api_key_configured,
            existing_has_proxy: provider.proxy_configured,
        }
    }

    pub fn field_label(index: usize) -> &'static str {
        match index {
            0 => "Provider ID",
            1 => "Display name",
            2 => "Base URL",
            3 => "API key",
            4 => "Proxy",
            5 => "Models",
            6 => "Local endpoint",
            7 => "Enabled",
            _ => "",
        }
    }

    pub fn field_value(&self, index: usize) -> String {
        match index {
            0 => self.id.clone(),
            1 => self.display_name.clone(),
            2 => self.base_url.clone(),
            3 => {
                if self.api_key.is_empty() && self.existing_has_key {
                    "configured — blank preserves".to_string()
                } else if self.api_key.is_empty() {
                    "not set".to_string()
                } else {
                    "••••••••".to_string()
                }
            }
            4 => {
                if self.proxy.is_empty() && self.existing_has_proxy {
                    "configured — blank preserves".to_string()
                } else {
                    self.proxy.clone()
                }
            }
            5 => self.models.clone(),
            6 => if self.local { "Yes" } else { "No" }.to_string(),
            7 => if self.enabled { "Yes" } else { "No" }.to_string(),
            _ => String::new(),
        }
    }

    fn edit_value(&self, index: usize) -> Option<(String, bool, bool)> {
        match index {
            0 => Some((self.id.clone(), false, false)),
            1 => Some((self.display_name.clone(), false, false)),
            2 => Some((self.base_url.clone(), false, false)),
            3 => Some((String::new(), false, true)),
            4 => Some((self.proxy.clone(), false, true)),
            5 => Some((self.models.clone(), true, false)),
            _ => None,
        }
    }

    fn set_value(&mut self, index: usize, value: String) {
        match index {
            0 => self.id = value,
            1 => self.display_name = value,
            2 => self.base_url = value,
            3 => self.api_key = value,
            4 => self.proxy = value,
            5 => self.models = value,
            _ => {}
        }
    }

    pub fn payload(&self, editing_existing: bool) -> CustomProviderPayload {
        let models = self
            .models
            .split([',', '\n'])
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
            .collect::<Vec<_>>();
        CustomProviderPayload {
            id: if editing_existing {
                None
            } else {
                Some(self.id.trim().to_string())
            },
            display_name: Some(self.display_name.trim().to_string()),
            base_url: Some(self.base_url.trim().to_string()),
            api_key: if editing_existing && self.api_key.trim().is_empty() {
                None
            } else {
                Some(self.api_key.trim().to_string())
            },
            proxy: if editing_existing && self.proxy.trim().is_empty() && self.existing_has_proxy {
                None
            } else {
                Some(self.proxy.trim().to_string())
            },
            local: Some(self.local),
            models: Some(models),
            enabled: Some(self.enabled),
        }
    }
}

#[derive(Debug, Clone)]
pub enum ConfirmAction {
    ClearField(String),
    DeleteCustom(String),
    DisconnectProvider(String),
}

#[derive(Debug, Clone)]
pub enum Modal {
    EditField {
        field: ConfigField,
        input: TextInput,
    },
    Choice {
        key: String,
        label: String,
        options: Vec<ConfigOption>,
        selected: usize,
    },
    FieldPicker {
        title: String,
        field_indices: Vec<usize>,
        selected: usize,
    },
    ProviderEditor {
        existing_id: Option<String>,
        draft: ProviderDraft,
        selected: usize,
        editing: Option<TextInput>,
    },
    Confirm {
        title: String,
        body: String,
        action: ConfirmAction,
    },
    Message {
        title: String,
        body: String,
    },
    ProviderPicker {
        options: Vec<ProviderFilterOption>,
        selected: usize,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionState {
    Starting,
    Running,
    Degraded,
    Offline,
    Unknown,
}

impl ConnectionState {
    pub fn label(self) -> &'static str {
        match self {
            Self::Starting => "STARTING",
            Self::Running => "RUNNING",
            Self::Degraded => "DEGRADED",
            Self::Offline => "OFFLINE",
            Self::Unknown => "UNKNOWN",
        }
    }
}

pub struct App {
    pub api: AdminClient,
    pub page: Page,
    pub config: ConfigResponse,
    pub status: Value,
    pub server_identity: ServerIdentity,
    pub connection_state: ConnectionState,
    pub last_check_epoch: Option<u64>,
    pub last_connection_error: Option<String>,
    pub models: ModelsResponse,
    pub custom_providers: Vec<CustomProvider>,
    pub local_status: Vec<ProviderStatus>,
    pub usage: Value,
    pub diagnostic: Value,
    pub repositories: Vec<Repository>,
    pub repository_selected: usize,
    pub selected_repo_path: Option<String>,
    pub provider_selected: usize,
    pub routing_selected: usize,
    pub local_selected: usize,
    pub setting_selected: usize,
    pub browser: ModelBrowser,
    pub show_advanced: bool,
    pub modal: Option<Modal>,
    pub notice: Option<String>,
    pub error: Option<String>,
    pub should_quit: bool,
    pub hitboxes: Vec<Hitbox>,
    pub geometry: ChromeGeometry,
    pub mouse: Option<(u16, u16)>,
    bootstrap_mode: bool,
    staged_values: HashMap<String, Value>,
    bootstrap_result_path: Option<PathBuf>,
    bootstrap_launch_after_repository: bool,
    bootstrap_launch_danger: bool,
    pub start_server_requested: bool,
}

impl App {
    pub fn load(api: AdminClient, notice: Option<String>) -> Result<Self> {
        let config = api.config()?;
        let mut load_error: Option<String> = None;
        let status = match api.status() {
            Ok(value) => value,
            Err(error) => {
                load_error = Some(error.to_string());
                Value::Null
            }
        };
        let models = match api.models() {
            Ok(value) => value,
            Err(error) => {
                load_error.get_or_insert_with(|| error.to_string());
                ModelsResponse::default()
            }
        };
        let custom_providers = match api.custom_providers() {
            Ok(value) => value.providers,
            Err(error) => {
                load_error.get_or_insert_with(|| error.to_string());
                Vec::new()
            }
        };
        let local_status = match api.local_provider_status() {
            Ok(value) => value.providers,
            Err(error) => {
                load_error.get_or_insert_with(|| error.to_string());
                Vec::new()
            }
        };
        let usage = match api.usage(30) {
            Ok(value) => value,
            Err(error) => {
                load_error.get_or_insert_with(|| error.to_string());
                Value::Null
            }
        };
        let repositories = match api.repositories(false) {
            Ok(value) => value,
            Err(error) => {
                load_error.get_or_insert_with(|| error.to_string());
                RepositoriesResponse::default()
            }
        };
        let mut app = Self {
            api,
            page: Page::Dashboard,
            config,
            server_identity: identity_from_status(&status),
            connection_state: ConnectionState::Running,
            last_check_epoch: Some(now_epoch()),
            last_connection_error: None,
            status,
            models,
            custom_providers,
            local_status,
            usage,
            diagnostic: Value::Null,
            repositories: Vec::new(),
            repository_selected: 0,
            selected_repo_path: None,
            provider_selected: 0,
            routing_selected: 0,
            local_selected: 0,
            setting_selected: 0,
            browser: ModelBrowser::default(),
            show_advanced: false,
            modal: None,
            notice,
            error: load_error,
            should_quit: false,
            hitboxes: Vec::new(),
            geometry: ChromeGeometry::default(),
            mouse: None,
            bootstrap_mode: false,
            staged_values: HashMap::new(),
            bootstrap_result_path: None,
            bootstrap_launch_after_repository: false,
            bootstrap_launch_danger: false,
            start_server_requested: false,
        };
        app.set_repository_response(repositories);
        app.sync_model_browser();
        Ok(app)
    }

    /// Build the control center from the serverless snapshot prepared by
    /// `fcc-server`. No Admin request is attempted until the parent has
    /// persisted this session and started the server.
    pub fn from_bootstrap(
        api: AdminClient,
        state: BootstrapState,
        notice: Option<String>,
        result_path: PathBuf,
    ) -> Self {
        let launch_after_repository = state.launch_after_repository;
        let launch_danger = state.launch_danger;
        let mut app = Self {
            api,
            page: Page::Dashboard,
            config: state.config,
            server_identity: identity_from_status(&state.status),
            connection_state: ConnectionState::Starting,
            last_check_epoch: None,
            last_connection_error: None,
            status: state.status,
            models: state.models,
            custom_providers: state.custom_providers,
            local_status: state.local_status,
            usage: state.usage,
            diagnostic: state.diagnostic,
            repositories: Vec::new(),
            repository_selected: 0,
            selected_repo_path: None,
            provider_selected: 0,
            routing_selected: 0,
            local_selected: 0,
            setting_selected: 0,
            browser: ModelBrowser::default(),
            show_advanced: false,
            modal: None,
            notice,
            error: None,
            should_quit: false,
            hitboxes: Vec::new(),
            geometry: ChromeGeometry::default(),
            mouse: None,
            bootstrap_mode: true,
            staged_values: HashMap::new(),
            bootstrap_result_path: Some(result_path),
            bootstrap_launch_after_repository: launch_after_repository,
            bootstrap_launch_danger: launch_danger,
            start_server_requested: false,
        };
        app.set_repository_response(state.repositories);
        app.sync_model_browser();
        app.set_notice(if launch_after_repository {
            if launch_danger {
                "Choose a model and repository, then use Launch danger.".to_string()
            } else {
                "Choose a model and repository, then use Launch Claude.".to_string()
            }
        } else {
            "Prelaunch mode: choose models and repository, then press Start server.".to_string()
        });
        app
    }

    pub fn is_bootstrap(&self) -> bool {
        self.bootstrap_mode
    }

    pub fn bootstrap_launch_after_repository(&self) -> bool {
        self.bootstrap_launch_after_repository
    }

    pub fn bootstrap_repository_action_label(&self) -> &'static str {
        if !self.bootstrap_launch_after_repository {
            return "Use selected";
        }
        if self.bootstrap_launch_danger {
            "Launch danger"
        } else {
            "Launch Claude"
        }
    }

    pub fn refresh_health(&mut self) {
        match self.api.health() {
            Ok(identity) if identity.service == "agentswitchboard" && identity.protocol == 1 => {
                self.server_identity = identity.clone();
                self.connection_state =
                    if identity.lifecycle == "running" || identity.status == "healthy" {
                        ConnectionState::Running
                    } else {
                        ConnectionState::Degraded
                    };
                self.last_check_epoch = Some(now_epoch());
                self.last_connection_error = None;
                if let Ok(value) = serde_json::to_value(identity) {
                    if let (Some(status), Some(identity)) =
                        (self.status.as_object_mut(), value.as_object())
                    {
                        status.extend(identity.clone());
                    }
                }
            }
            Ok(identity) => {
                self.connection_state = ConnectionState::Unknown;
                self.last_check_epoch = Some(now_epoch());
                self.last_connection_error = Some(format!(
                    "foreign service at {}:{}",
                    identity.host, identity.port
                ));
            }
            Err(error) => {
                self.connection_state = ConnectionState::Offline;
                self.last_check_epoch = Some(now_epoch());
                self.last_connection_error = Some(error.to_string());
            }
        }
    }

    pub fn refresh_all(&mut self) {
        if self.bootstrap_mode {
            self.set_notice(
                "Live refresh starts after the server launches; this screen uses the prelaunch snapshot."
                    .to_string(),
            );
            return;
        }
        match self.api.config() {
            Ok(value) => self.config = value,
            Err(error) => self.set_error(error.to_string()),
        }
        match self.api.status() {
            Ok(value) => self.status = value,
            Err(error) => self.set_error(error.to_string()),
        }
        match self.api.models() {
            Ok(value) => self.models = value,
            Err(error) => self.set_error(error.to_string()),
        }
        match self.api.custom_providers() {
            Ok(value) => self.custom_providers = value.providers,
            Err(error) => self.set_error(error.to_string()),
        }
        match self.api.local_provider_status() {
            Ok(value) => self.local_status = value.providers,
            Err(error) => self.set_error(error.to_string()),
        }
        match self.api.usage(30) {
            Ok(value) => self.usage = value,
            Err(error) => self.set_error(error.to_string()),
        }
        match self.api.repositories(false) {
            Ok(value) => self.set_repository_response(value),
            Err(error) => self.set_error(error.to_string()),
        }
        self.sync_model_browser();
        self.clamp_selections();
    }

    pub fn handle_event(&mut self, event: Event) -> Result<Option<ExternalAction>> {
        match event {
            Event::Key(key) if key.kind == KeyEventKind::Press => self.handle_key(key),
            Event::Mouse(mouse) => self.handle_mouse(mouse),
            _ => Ok(None),
        }
    }

    fn handle_key(&mut self, key: KeyEvent) -> Result<Option<ExternalAction>> {
        if self.modal.is_some() {
            self.handle_modal_key(key)?;
            return Ok(None);
        }

        if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('c') {
            self.request_quit();
            return Ok(None);
        }
        if self.page == Page::Models
            && key.modifiers.contains(KeyModifiers::CONTROL)
            && key.code == KeyCode::Char('s')
        {
            self.save_model_catalog();
            return Ok(None);
        }
        if self.page == Page::Models && self.browser.search_focused {
            return self.handle_model_search_key(key);
        }

        match key.code {
            KeyCode::Char('q') => self.request_quit(),
            KeyCode::Tab => self.next_page(1),
            KeyCode::BackTab => self.next_page(-1),
            KeyCode::Up | KeyCode::Char('k') => self.move_selection(-1),
            KeyCode::Down | KeyCode::Char('j') => self.move_selection(1),
            KeyCode::Char('r') => self.refresh_current(),
            KeyCode::Char('c') => {
                if self.bootstrap_mode {
                    if self.bootstrap_launch_after_repository && self.page == Page::Repositories {
                        self.use_selected_repository();
                    } else if self.bootstrap_launch_after_repository {
                        self.page = Page::Repositories;
                        self.set_notice(format!(
                            "Choose a repository, then use {}.",
                            self.bootstrap_repository_action_label()
                        ));
                    } else {
                        self.start_server();
                    }
                    return Ok(None);
                }
                if self.page == Page::Repositories {
                    self.use_selected_repository();
                }
                return Ok(Some(ExternalAction::LaunchClaude { danger: false }));
            }
            KeyCode::Enter => self.activate_selection()?,
            KeyCode::Char('e') if self.page == Page::Models => self.toggle_selected_model_access(),
            KeyCode::Char(' ') if self.page == Page::Models => self.toggle_selected_model_access(),
            KeyCode::Char('e') => self.edit_action()?,
            KeyCode::Char('t') if self.page == Page::Providers => self.test_selected_provider(),
            KeyCode::Char('n') if self.page == Page::Providers => self.new_custom_provider(),
            KeyCode::Char('x') if self.page == Page::Providers => self.delete_custom_provider(),
            KeyCode::Char('l') if self.page == Page::Providers => self.login_provider("browser"),
            KeyCode::Char('L') if self.page == Page::Providers => self.login_provider("device"),
            KeyCode::Char('D') if self.page == Page::Providers => self.disconnect_provider(),
            KeyCode::Char('/') if self.page == Page::Models => self.focus_model_search(),
            KeyCode::Char('s') if self.page == Page::Models => self.save_model_catalog(),
            KeyCode::Char('f') if self.page == Page::Models => {
                let message = self.browser.toggle_free_filter();
                self.set_notice(message);
            }
            KeyCode::Char('d') if self.page == Page::Routing => self.assign_selected_route("MODEL"),
            KeyCode::Char('f') if self.page == Page::Routing => {
                self.assign_selected_route("MODEL_FABLE")
            }
            KeyCode::Char('o') if self.page == Page::Routing => {
                self.assign_selected_route("MODEL_OPUS")
            }
            KeyCode::Char('s') if self.page == Page::Routing => {
                self.assign_selected_route("MODEL_SONNET")
            }
            KeyCode::Char('h') if self.page == Page::Routing => {
                self.assign_selected_route("MODEL_HAIKU")
            }
            KeyCode::Char('a') if self.page == Page::Models => self.disable_all_models(),
            KeyCode::Char('i') if self.page == Page::Models => {
                let message = self.browser.toggle_catalog();
                self.set_notice(message);
            }
            KeyCode::Char('P') if self.page == Page::Models => self.open_provider_filter(),
            KeyCode::Char('u') if self.page == Page::Models => self.discard_model_changes(),
            KeyCode::Char('a') if self.page == Page::Settings => {
                self.show_advanced = !self.show_advanced
            }
            KeyCode::Char('x')
                if matches!(
                    self.page,
                    Page::Routing | Page::Context | Page::Local | Page::Settings
                ) =>
            {
                self.clear_selected_secret();
            }
            KeyCode::Char('!') => {
                if self.bootstrap_mode {
                    if self.bootstrap_launch_after_repository && self.page == Page::Repositories {
                        self.use_selected_repository();
                    } else if self.bootstrap_launch_after_repository {
                        self.page = Page::Repositories;
                        self.set_notice(format!(
                            "Choose a repository, then use {}.",
                            self.bootstrap_repository_action_label()
                        ));
                    } else {
                        self.start_server();
                    }
                    return Ok(None);
                }
                if self.page == Page::Repositories {
                    self.use_selected_repository();
                }
                return Ok(Some(ExternalAction::LaunchClaude { danger: true }));
            }
            KeyCode::Char('S') if self.bootstrap_mode => self.start_server(),
            _ => {}
        }
        Ok(None)
    }

    fn handle_model_search_key(&mut self, key: KeyEvent) -> Result<Option<ExternalAction>> {
        match key.code {
            KeyCode::Esc => {
                self.browser.search_focused = false;
            }
            KeyCode::Enter => {
                self.browser.search_focused = false;
            }
            KeyCode::Up => self.move_selection(-1),
            KeyCode::Down => self.move_selection(1),
            KeyCode::Backspace => {
                self.browser.query.pop();
                self.browser.selected = 0;
            }
            KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                self.browser.query.clear();
                self.browser.selected = 0;
            }
            KeyCode::Char(character) if !key.modifiers.contains(KeyModifiers::CONTROL) => {
                self.browser.query.push(character);
                self.browser.selected = 0;
            }
            _ => {}
        }
        Ok(None)
    }

    fn focus_model_search(&mut self) {
        self.browser.search_focused = true;
    }

    fn open_provider_filter(&mut self) {
        let snapshot = self.catalog_snapshot();
        let mut options = Vec::with_capacity(snapshot.provider_filter_options().len() + 1);
        let known_refs = snapshot.known_refs();
        let free_count = snapshot
            .records
            .iter()
            .filter(|record| {
                snapshot.provider_is_registered(&record.provider_id)
                    && record.price == crate::models::PriceState::Free
            })
            .count();
        options.push(ProviderFilterOption {
            id: String::new(),
            label: "Registered providers".to_string(),
            status: "active".to_string(),
            model_count: known_refs.len(),
            free_count,
        });
        options.extend(snapshot.provider_filter_options());
        let selected = self
            .browser
            .provider_filter
            .as_deref()
            .and_then(|provider| {
                options
                    .iter()
                    .position(|option| option.id.eq_ignore_ascii_case(provider))
            })
            .unwrap_or(0);
        self.modal = Some(Modal::ProviderPicker { options, selected });
    }

    fn select_provider_filter(&mut self, index: usize) {
        let Some(Modal::ProviderPicker { options, .. }) = self.modal.take() else {
            return;
        };
        let Some(option) = options.get(index) else {
            self.set_error("Provider filter selection is out of range".to_string());
            return;
        };
        let snapshot = self.catalog_snapshot();
        let provider = (!option.id.is_empty()).then(|| option.id.clone());
        let message = self.browser.set_provider_filter(provider, &snapshot);
        self.set_notice(message);
    }

    fn handle_mouse(&mut self, mouse: MouseEvent) -> Result<Option<ExternalAction>> {
        self.mouse = Some((mouse.column, mouse.row));
        match mouse.kind {
            MouseEventKind::ScrollUp => {
                self.move_selection(-2);
                return Ok(None);
            }
            MouseEventKind::ScrollDown => {
                self.move_selection(2);
                return Ok(None);
            }
            MouseEventKind::Down(MouseButton::Left) => {}
            _ => return Ok(None),
        }
        let action = self
            .hitboxes
            .iter()
            .rev()
            .find(|hitbox| contains(hitbox.rect, mouse.column, mouse.row))
            .map(|hitbox| hitbox.action.clone());
        if let Some(action) = action {
            if let UiAction::SelectModel(index) = action {
                self.browser.selected = index;
                if mouse.modifiers.intersects(
                    KeyModifiers::SHIFT
                        | KeyModifiers::CONTROL
                        | KeyModifiers::ALT
                        | KeyModifiers::SUPER,
                ) {
                    self.toggle_selected_model_access();
                }
                return Ok(None);
            }
            return self.invoke_ui_action(action);
        }
        Ok(None)
    }

    fn invoke_ui_action(&mut self, action: UiAction) -> Result<Option<ExternalAction>> {
        if !matches!(action, UiAction::SearchModels) {
            self.browser.search_focused = false;
        }
        match action {
            UiAction::Navigate(page) => self.page = page,
            UiAction::SelectRepository(index) => self.repository_selected = index,
            UiAction::SelectProvider(index) => self.provider_selected = index,
            UiAction::SelectModel(index) => self.browser.selected = index,
            UiAction::SelectRouting(index) => self.routing_selected = index,
            UiAction::SelectLocal(index) => self.local_selected = index,
            UiAction::SelectSetting(index) => self.setting_selected = index,
            UiAction::Refresh => self.refresh_current(),
            UiAction::UseRepository => self.use_selected_repository(),
            UiAction::RefreshRepositories => self.refresh_repositories(true),
            UiAction::ConfigureProvider => self.configure_selected_provider(),
            UiAction::TestProvider => self.test_selected_provider(),
            UiAction::NewCustomProvider => self.new_custom_provider(),
            UiAction::EditCustomProvider => self.edit_selected_custom_provider(),
            UiAction::DeleteCustomProvider => self.delete_custom_provider(),
            UiAction::LoginProvider => self.login_provider("browser"),
            UiAction::DisconnectProvider => self.disconnect_provider(),
            UiAction::EditField => self.edit_action()?,
            UiAction::ToggleAdvanced => self.show_advanced = !self.show_advanced,
            UiAction::AssignModel(key) => self.use_selected_model(&key),
            UiAction::SearchModels => self.focus_model_search(),
            UiAction::OpenProviderFilter => self.open_provider_filter(),
            UiAction::SelectProviderFilter(index) => self.select_provider_filter(index),
            UiAction::ToggleFreeFilter => {
                let message = self.browser.toggle_free_filter();
                self.set_notice(message);
            }
            UiAction::ToggleCatalogVisibility => {
                let message = self.browser.toggle_catalog();
                self.set_notice(message);
            }
            UiAction::ToggleModelAccess => self.toggle_selected_model_access(),
            UiAction::DisableAllModels => self.disable_all_models(),
            UiAction::SaveModels => self.save_model_catalog(),
            UiAction::DiscardModels => self.discard_model_changes(),
            UiAction::StartServer => self.start_server(),
            UiAction::AssignRoute(key) => self.assign_selected_route(&key),
            UiAction::RunDiagnostic => self.run_diagnostic(),
            UiAction::LaunchClaude(danger) => {
                return Ok(Some(ExternalAction::LaunchClaude { danger }));
            }
        }
        Ok(None)
    }

    fn activate_selection(&mut self) -> Result<()> {
        match self.page {
            Page::Repositories => self.use_selected_repository(),
            Page::Providers => self.configure_selected_provider(),
            Page::Models => self.use_selected_model("MODEL"),
            Page::Routing | Page::Context | Page::Local | Page::Settings => self.edit_action()?,
            Page::Diagnostics => self.run_diagnostic(),
            _ => {}
        }
        Ok(())
    }

    fn edit_action(&mut self) -> Result<()> {
        match self.page {
            Page::Providers => self.edit_selected_custom_provider(),
            Page::Routing | Page::Context | Page::Local | Page::Settings => {
                if let Some(index) = self.selected_field_index() {
                    self.open_field_editor(index);
                }
            }
            _ => {}
        }
        Ok(())
    }

    fn refresh_current(&mut self) {
        if self.bootstrap_mode {
            self.set_notice(
                "Live refresh starts after the server launches; this screen uses the prelaunch snapshot."
                    .to_string(),
            );
            return;
        }
        match self.page {
            Page::Repositories => self.refresh_repositories(true),
            Page::Models => match self.api.refresh_models() {
                Ok(value) => {
                    self.models = value;
                    self.sync_model_browser();
                    self.set_notice("Model catalog refreshed".to_string());
                }
                Err(error) => self.set_error(error.to_string()),
            },
            Page::Usage => match self.api.usage(30) {
                Ok(value) => self.usage = value,
                Err(error) => self.set_error(error.to_string()),
            },
            Page::Local => match self.api.local_provider_status() {
                Ok(value) => self.local_status = value.providers,
                Err(error) => self.set_error(error.to_string()),
            },
            _ => self.refresh_all(),
        }
        self.clamp_selections();
    }

    fn next_page(&mut self, delta: isize) {
        let current = self.page.index() as isize;
        let len = Page::ALL.len() as isize;
        let next = (current + delta).rem_euclid(len) as usize;
        self.page = Page::ALL[next];
    }

    fn move_selection(&mut self, delta: isize) {
        let len = match self.page {
            Page::Repositories => self.repositories.len(),
            Page::Providers => self.config.provider_status.len(),
            Page::Models => self.filtered_models().len(),
            Page::Routing => self.routing_field_indices().len(),
            Page::Local => self.local_field_indices().len(),
            Page::Settings => self.settings_field_indices().len(),
            _ => return,
        };
        let selection = match self.page {
            Page::Repositories => &mut self.repository_selected,
            Page::Providers => &mut self.provider_selected,
            Page::Models => &mut self.browser.selected,
            Page::Routing => &mut self.routing_selected,
            Page::Local => &mut self.local_selected,
            Page::Settings => &mut self.setting_selected,
            _ => return,
        };
        if len == 0 {
            *selection = 0;
            return;
        }
        *selection = (*selection as isize + delta).clamp(0, len as isize - 1) as usize;
    }

    fn clamp_selections(&mut self) {
        self.repository_selected = clamp(self.repository_selected, self.repositories.len());
        self.provider_selected = clamp(self.provider_selected, self.config.provider_status.len());
        let snapshot = self.catalog_snapshot();
        self.browser.clamp_selection(&snapshot);
        self.routing_selected = clamp(self.routing_selected, self.routing_field_indices().len());
        self.local_selected = clamp(self.local_selected, self.local_field_indices().len());
        self.setting_selected = clamp(self.setting_selected, self.settings_field_indices().len());
    }

    fn set_repository_response(&mut self, response: RepositoriesResponse) {
        self.repositories = response.repositories;
        self.selected_repo_path = response.selected_path.filter(|path| {
            self.repositories
                .iter()
                .any(|repository| repository.path == *path)
        });
        if let Some(selected_path) = self.selected_repo_path.as_deref() {
            self.repository_selected = self
                .repositories
                .iter()
                .position(|repository| repository.path == selected_path)
                .unwrap_or(0);
        }
        self.clamp_selections();
    }

    fn refresh_repositories(&mut self, refresh: bool) {
        if self.bootstrap_mode {
            self.set_notice(
                "Repository discovery is complete for this launch; refresh is available after the server starts."
                    .to_string(),
            );
            return;
        }
        match self.api.repositories(refresh) {
            Ok(value) => {
                self.set_repository_response(value);
                if refresh {
                    self.set_notice("Repository inventory refreshed".to_string());
                }
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    pub fn selected_repository(&self) -> Option<&Repository> {
        self.repositories.get(self.repository_selected)
    }

    pub fn launch_repository_path(&self) -> Option<&str> {
        self.selected_repository()
            .map(|repository| repository.path.as_str())
            .or(self.selected_repo_path.as_deref())
    }

    fn use_selected_repository(&mut self) {
        let Some(repository) = self.selected_repository().cloned() else {
            self.set_notice("No repository is selected. Press Refresh first.".to_string());
            return;
        };
        if self.bootstrap_mode {
            let previous = self.selected_repo_path.clone();
            self.selected_repo_path = Some(repository.path.clone());
            if !self.persist_bootstrap_result() {
                self.selected_repo_path = previous;
                return;
            }
            if self.bootstrap_launch_after_repository {
                self.start_server();
                return;
            }
            self.set_notice(format!(
                "Repository selected: {} (saved for the next server launch)",
                repository.identity
            ));
            return;
        }
        match self.api.select_repository(&repository.path) {
            Ok(result) => {
                self.selected_repo_path = Some(result.repository.path.clone());
                if let Some(current) = self
                    .repositories
                    .iter_mut()
                    .find(|candidate| candidate.path == result.repository.path)
                {
                    *current = result.repository;
                }
                self.set_notice(if result.persisted {
                    format!("Repository selected: {}", repository.identity)
                } else {
                    format!(
                        "Repository selected for this session; cache unavailable: {}",
                        repository.identity
                    )
                });
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    pub fn catalog_snapshot(&self) -> CatalogSnapshot {
        CatalogSnapshot::from_admin(&self.models, &self.config)
    }

    pub fn sync_model_browser(&mut self) {
        let snapshot = self.catalog_snapshot();
        self.browser.sync(&snapshot);
    }

    pub fn filtered_models(&self) -> Vec<String> {
        let snapshot = self.catalog_snapshot();
        self.browser.filtered_refs(&snapshot)
    }

    pub fn model_is_routable(&self, model: &str) -> bool {
        self.catalog_snapshot()
            .record(model)
            .map(|record| record.routable)
            .unwrap_or(false)
    }

    pub fn routing_field_indices(&self) -> Vec<usize> {
        ROUTING_KEYS
            .iter()
            .filter_map(|key| {
                self.config
                    .fields
                    .iter()
                    .position(|field| field.key == *key)
            })
            .collect()
    }

    pub fn local_field_indices(&self) -> Vec<usize> {
        LOCAL_KEYS
            .iter()
            .filter_map(|key| {
                self.config
                    .fields
                    .iter()
                    .position(|field| field.key == *key)
            })
            .collect()
    }

    pub fn settings_field_indices(&self) -> Vec<usize> {
        self.config
            .fields
            .iter()
            .enumerate()
            .filter(|(_, field)| !field.section_id.eq_ignore_ascii_case("providers"))
            .filter(|(_, field)| self.show_advanced || !field.advanced)
            .map(|(index, _)| index)
            .collect()
    }

    pub fn selected_provider(&self) -> Option<&ProviderStatus> {
        self.config.provider_status.get(self.provider_selected)
    }

    pub fn selected_model(&self) -> Option<String> {
        let snapshot = self.catalog_snapshot();
        self.browser.selected_ref(&snapshot)
    }

    pub fn selected_field_index(&self) -> Option<usize> {
        match self.page {
            Page::Routing => self
                .routing_field_indices()
                .get(self.routing_selected)
                .copied(),
            // FCC context intervention is disabled. Keep the page available
            // for an explicit status explanation, but never open an editor.
            Page::Context => None,
            Page::Local => self.local_field_indices().get(self.local_selected).copied(),
            Page::Settings => self
                .settings_field_indices()
                .get(self.setting_selected)
                .copied(),
            _ => None,
        }
    }

    fn configure_selected_provider(&mut self) {
        let Some(provider) = self.selected_provider().cloned() else {
            return;
        };
        if provider.custom {
            self.edit_selected_custom_provider();
            return;
        }
        if provider.kind == "connected_account" {
            self.login_provider("browser");
            return;
        }
        let indices = self.provider_field_indices(&provider);
        if indices.is_empty() {
            self.set_notice("No editable provider fields were advertised".to_string());
            return;
        }
        self.modal = Some(Modal::FieldPicker {
            title: format!("Configure {}", provider.display_name),
            field_indices: indices,
            selected: 0,
        });
    }

    fn provider_field_indices(&self, provider: &ProviderStatus) -> Vec<usize> {
        let mut keys = provider
            .configuration
            .split('+')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_string)
            .collect::<Vec<_>>();
        if provider.kind == "local" {
            let key = match provider.provider_id.as_str() {
                "lmstudio" => Some("LM_STUDIO_BASE_URL"),
                "llamacpp" => Some("LLAMACPP_BASE_URL"),
                "ollama" => Some("OLLAMA_BASE_URL"),
                _ => None,
            };
            if let Some(key) = key {
                keys.push(key.to_string());
            }
        }
        keys.sort();
        keys.dedup();
        keys.iter()
            .filter_map(|key| {
                self.config
                    .fields
                    .iter()
                    .position(|field| field.key == *key)
            })
            .collect()
    }

    fn open_field_editor(&mut self, index: usize) {
        let Some(field) = self.config.fields.get(index).cloned() else {
            return;
        };
        if field.locked {
            self.set_notice(format!("{} is locked by {}", field.label, field.source));
            return;
        }
        if field.field_type == "boolean" {
            self.modal = Some(Modal::Choice {
                key: field.key,
                label: field.label,
                options: vec![
                    ConfigOption {
                        value: "true".to_string(),
                        label: "Enabled".to_string(),
                    },
                    ConfigOption {
                        value: "false".to_string(),
                        label: "Disabled".to_string(),
                    },
                ],
                selected: if field.value.eq_ignore_ascii_case("false") {
                    1
                } else {
                    0
                },
            });
            return;
        }
        if !field.options.is_empty() {
            let selected = field
                .options
                .iter()
                .position(|option| option.value == field.value)
                .unwrap_or(0);
            self.modal = Some(Modal::Choice {
                key: field.key,
                label: field.label,
                options: field.options,
                selected,
            });
            return;
        }
        let initial = if field.secret && field.value == MASKED_SECRET {
            String::new()
        } else {
            field.value.clone()
        };
        self.modal = Some(Modal::EditField {
            input: TextInput::new(initial, field.field_type == "textarea", field.secret),
            field,
        });
    }

    fn clear_selected_secret(&mut self) {
        let Some(index) = self.selected_field_index() else {
            return;
        };
        let Some(field) = self.config.fields.get(index) else {
            return;
        };
        if !field.secret || field.locked {
            return;
        }
        self.modal = Some(Modal::Confirm {
            title: "Clear secret".to_string(),
            body: format!("Clear {}? This writes an empty value.", field.label),
            action: ConfirmAction::ClearField(field.key.clone()),
        });
    }

    fn apply_field_value(&mut self, key: &str, value: Value) {
        if key == CONTEXT_KEY {
            self.set_error("FCC context policy is disabled and cannot be edited".to_string());
            return;
        }
        if self.bootstrap_mode {
            if key == CUSTOM_PROVIDERS_KEY {
                self.set_notice(
                    "Custom provider registration is available after the server starts; credentials are not staged here."
                        .to_string(),
                );
                return;
            }
            let Some(field) = self.config.fields.iter().find(|field| field.key == key) else {
                self.set_error(format!("Unknown configuration field: {key}"));
                return;
            };
            if field.locked {
                self.set_notice(format!("{} is locked by {}", field.label, field.source));
                return;
            }
            let previous_config = self.config.clone();
            let previous_values = self.staged_values.clone();
            let values = HashMap::from([(key.to_string(), value)]);
            self.stage_values(&values);
            if !self.persist_bootstrap_result() {
                self.config = previous_config;
                self.staged_values = previous_values;
                return;
            }
            self.set_notice(format!("Saved {key} locally; Start server to apply it."));
            return;
        }
        match self.api.apply_field(key, value) {
            Ok(result) if result.valid && result.applied => {
                self.refresh_all();
                if result.pending_fields.is_empty() {
                    self.set_notice(format!("Saved {key}"));
                } else {
                    self.set_notice(format!(
                        "Saved {key}; restart/session boundary: {}",
                        result.pending_fields.join(", ")
                    ));
                }
            }
            Ok(result) => self.set_error(if result.errors.is_empty() {
                format!("{key} was not applied")
            } else {
                result.errors.join("\n")
            }),
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn use_selected_model(&mut self, key: &str) {
        let Some(model) = self.selected_model() else {
            return;
        };
        if key == MODEL_KEY {
            let snapshot = self.catalog_snapshot();
            match self.browser.select_model(&model, &snapshot) {
                Some(message) => self.set_notice(message),
                None => self.set_error("Select a catalog model first".to_string()),
            }
            return;
        }
        self.apply_field_value(key, Value::String(model.clone()));
        if self.error.is_none() {
            self.set_notice(format!("{key} → {model}"));
        }
    }

    fn assign_selected_route(&mut self, key: &str) {
        let Some(model) = self.selected_model() else {
            self.set_error("Choose a model on the Models tab first".to_string());
            return;
        };
        self.apply_field_value(key, Value::String(model.clone()));
        if self.error.is_none() {
            self.set_notice(format!("{key} → {model}"));
        }
    }

    fn toggle_selected_model_access(&mut self) {
        let Some(model) = self.selected_model() else {
            return;
        };
        let snapshot = self.catalog_snapshot();
        match self.browser.toggle_access(&model, &snapshot) {
            Ok(message) => self.set_notice(message),
            Err(message) => self.set_error(message),
        }
    }

    fn disable_all_models(&mut self) {
        let message = self.browser.disable_all();
        self.set_notice(message);
    }

    fn discard_model_changes(&mut self) {
        self.browser.discard();
        self.set_notice("Discarded unsaved model changes".to_string());
    }

    fn save_model_catalog(&mut self) {
        let snapshot = self.catalog_snapshot();
        if !self.browser.dirty() {
            self.set_notice("No model changes to save".to_string());
            return;
        }
        let payload = self.browser.save_payload();
        let expected = self.browser.expected_readback(&snapshot);
        if self.bootstrap_mode {
            let previous_config = self.config.clone();
            let previous_values = self.staged_values.clone();
            self.stage_values(&payload);
            if !self.persist_bootstrap_result() {
                self.config = previous_config;
                self.staged_values = previous_values;
                return;
            }
            let snapshot = self.catalog_snapshot();
            self.browser.commit(&snapshot);
            self.set_notice(
                "Saved model catalog locally; Start server to apply and verify it.".to_string(),
            );
            return;
        }
        match self.api.apply_fields(payload) {
            Ok(result) if result.valid && result.applied => {
                match self.api.config() {
                    Ok(config) => {
                        if let Err(message) = verify_catalog_readback(&expected, &config) {
                            self.config = config;
                            self.set_error(message);
                            return;
                        }
                        self.config = config;
                    }
                    Err(error) => {
                        self.set_error(format!(
                            "Saved, but could not read Admin config back: {error}"
                        ));
                        return;
                    }
                }
                match self.api.models() {
                    Ok(models) => self.models = models,
                    Err(error) => self.set_error(format!(
                        "Saved, but could not reload the cached model catalog: {error}"
                    )),
                }
                let snapshot = self.catalog_snapshot();
                self.browser.commit(&snapshot);
                if result.pending_fields.is_empty() {
                    self.set_notice("Saved model catalog (read-back verified)".to_string());
                } else {
                    self.set_notice(format!(
                        "Saved model catalog; restart/session boundary: {}",
                        result.pending_fields.join(", ")
                    ));
                }
            }
            Ok(result) => self.set_error(if result.errors.is_empty() {
                "Model catalog was not applied".to_string()
            } else {
                result.errors.join("\n")
            }),
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn stage_values(&mut self, values: &HashMap<String, Value>) {
        for (key, value) in values {
            self.staged_values.insert(key.clone(), value.clone());
            let raw = config_value_string(value);
            if let Some(field) = self
                .config
                .fields
                .iter_mut()
                .find(|field| field.key == *key)
            {
                field.configured = !raw.trim().is_empty();
                field.value = if field.secret && field.configured {
                    MASKED_SECRET.to_string()
                } else {
                    raw
                };
            }
        }
    }

    fn request_quit(&mut self) {
        if self.bootstrap_mode && self.browser.dirty() {
            self.save_model_catalog();
            if self.error.is_some() {
                return;
            }
        }
        self.should_quit = true;
    }

    fn start_server(&mut self) {
        if !self.bootstrap_mode {
            self.set_notice("The server is already running.".to_string());
            return;
        }
        if self.browser.dirty() {
            self.save_model_catalog();
            if self.error.is_some() {
                return;
            }
        }
        let previous = self.start_server_requested;
        self.start_server_requested = true;
        if !self.persist_bootstrap_result() {
            self.start_server_requested = previous;
            return;
        }
        self.set_notice(if self.bootstrap_launch_after_repository {
            "Choices saved. Starting FCC server, then Claude…".to_string()
        } else {
            "Choices saved. Starting FCC server…".to_string()
        });
        self.should_quit = true;
    }

    fn persist_bootstrap_result(&mut self) -> bool {
        match self.write_bootstrap_result() {
            Ok(()) => true,
            Err(error) => {
                self.set_error(format!("Could not save prelaunch choices: {error}"));
                false
            }
        }
    }

    /// Persist the parent handoff atomically with owner-only permissions.
    ///
    /// The bootstrap snapshot is intentionally read-only from the TUI's
    /// perspective. This result is the sole write handoff; the Python parent
    /// validates and commits it before creating the server runtime.
    pub fn write_bootstrap_result(&self) -> Result<()> {
        if !self.bootstrap_mode {
            return Ok(());
        }
        let path = self
            .bootstrap_result_path
            .as_deref()
            .ok_or_else(|| anyhow::anyhow!("bootstrap result path is missing"))?;
        let values = self
            .staged_values
            .iter()
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect::<Map<String, Value>>();
        let payload = json!({
            "version": 1,
            "values": values,
            "selected_repository": self.selected_repo_path,
            "start_server": self.start_server_requested,
        });
        let encoded = serde_json::to_vec_pretty(&payload)
            .map_err(|error| anyhow::anyhow!("could not encode prelaunch choices: {error}"))?;
        let temporary = path.with_extension("tmp");
        let mut options = OpenOptions::new();
        options.create(true).truncate(true).write(true);
        #[cfg(unix)]
        options.mode(0o600);
        let mut file = options
            .open(&temporary)
            .map_err(|error| anyhow::anyhow!("could not open result file: {error}"))?;
        file.write_all(&encoded)
            .map_err(|error| anyhow::anyhow!("could not write result file: {error}"))?;
        file.sync_all()
            .map_err(|error| anyhow::anyhow!("could not sync result file: {error}"))?;
        #[cfg(unix)]
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))?;
        fs::rename(&temporary, path)
            .map_err(|error| anyhow::anyhow!("could not publish result file: {error}"))?;
        Ok(())
    }

    fn test_selected_provider(&mut self) {
        if self.bootstrap_mode {
            self.set_notice(
                "Provider tests run after the server starts; configuration edits are saved now."
                    .to_string(),
            );
            return;
        }
        let Some(provider) = self.selected_provider().cloned() else {
            return;
        };
        match self.api.test_provider(&provider.provider_id) {
            Ok(value) => {
                self.modal = Some(Modal::Message {
                    title: format!("{} test", provider.display_name),
                    body: pretty(&value),
                })
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn new_custom_provider(&mut self) {
        if self.bootstrap_mode {
            self.set_notice(
                "Custom provider registration is available after the server starts.".to_string(),
            );
            return;
        }
        self.modal = Some(Modal::ProviderEditor {
            existing_id: None,
            draft: ProviderDraft::empty(),
            selected: 0,
            editing: None,
        });
    }

    fn edit_selected_custom_provider(&mut self) {
        if self.bootstrap_mode {
            self.set_notice(
                "Custom provider editing is available after the server starts.".to_string(),
            );
            return;
        }
        let Some(status) = self.selected_provider() else {
            return;
        };
        if !status.custom {
            return;
        }
        let Some(provider) = self
            .custom_providers
            .iter()
            .find(|provider| provider.provider_id == status.provider_id)
            .cloned()
        else {
            self.set_error("Custom provider details are unavailable".to_string());
            return;
        };
        self.modal = Some(Modal::ProviderEditor {
            existing_id: Some(provider.provider_id.clone()),
            draft: ProviderDraft::from_existing(&provider),
            selected: 0,
            editing: None,
        });
    }

    fn delete_custom_provider(&mut self) {
        if self.bootstrap_mode {
            self.set_notice(
                "Custom provider deletion is available after the server starts.".to_string(),
            );
            return;
        }
        let Some(provider) = self.selected_provider() else {
            return;
        };
        if !provider.custom {
            return;
        }
        self.modal = Some(Modal::Confirm {
            title: "Delete custom provider".to_string(),
            body: format!(
                "Delete {} ({})?",
                provider.display_name, provider.provider_id
            ),
            action: ConfirmAction::DeleteCustom(provider.provider_id.clone()),
        });
    }

    fn login_provider(&mut self, mode: &str) {
        if self.bootstrap_mode {
            self.set_notice(
                "Connected-account sign-in is available after the server starts.".to_string(),
            );
            return;
        }
        let Some(provider) = self.selected_provider().cloned() else {
            return;
        };
        if provider.kind != "connected_account" {
            return;
        }
        match self
            .api
            .connected_account_login(&provider.provider_id, mode)
        {
            Ok(value) => {
                self.modal = Some(Modal::Message {
                    title: format!("{} sign-in", provider.display_name),
                    body: pretty(&value),
                })
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn disconnect_provider(&mut self) {
        if self.bootstrap_mode {
            self.set_notice(
                "Connected-account disconnect is available after the server starts.".to_string(),
            );
            return;
        }
        let Some(provider) = self.selected_provider() else {
            return;
        };
        if provider.kind != "connected_account" {
            return;
        }
        self.modal = Some(Modal::Confirm {
            title: "Disconnect account".to_string(),
            body: format!("Disconnect {}?", provider.display_name),
            action: ConfirmAction::DisconnectProvider(provider.provider_id.clone()),
        });
    }

    fn run_diagnostic(&mut self) {
        if self.bootstrap_mode {
            self.set_notice(
                "Route diagnostics run after the server starts; the prelaunch catalog is already populated."
                    .to_string(),
            );
            return;
        }
        let model = self
            .config
            .fields
            .iter()
            .find(|field| field.key == "MODEL")
            .map(|field| field.value.as_str())
            .filter(|value| !value.is_empty());
        match self.api.route_diagnostic(model) {
            Ok(value) => self.diagnostic = value,
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn handle_modal_key(&mut self, key: KeyEvent) -> Result<()> {
        let Some(modal) = self.modal.take() else {
            return Ok(());
        };
        match modal {
            Modal::Message { title, body } => {
                if !matches!(key.code, KeyCode::Esc | KeyCode::Enter) {
                    self.modal = Some(Modal::Message { title, body });
                }
            }
            Modal::ProviderPicker {
                options,
                mut selected,
            } => {
                match key.code {
                    KeyCode::Esc => return Ok(()),
                    KeyCode::Up | KeyCode::Char('k') => selected = selected.saturating_sub(1),
                    KeyCode::Down | KeyCode::Char('j') => {
                        selected = selected
                            .saturating_add(1)
                            .min(options.len().saturating_sub(1))
                    }
                    KeyCode::Enter => {
                        if let Some(option) = options.get(selected) {
                            let snapshot = self.catalog_snapshot();
                            let provider = (!option.id.is_empty()).then(|| option.id.clone());
                            let message = self.browser.set_provider_filter(provider, &snapshot);
                            self.set_notice(message);
                            return Ok(());
                        }
                    }
                    _ => {}
                }
                self.modal = Some(Modal::ProviderPicker { options, selected });
            }
            Modal::EditField { field, mut input } => match edit_input(&mut input, key) {
                InputOutcome::Cancel => {}
                InputOutcome::Submit => {
                    if field.secret && field.configured && input.value.trim().is_empty() {
                        self.set_notice(format!("{} unchanged", field.label));
                    } else {
                        self.apply_field_value(&field.key, Value::String(input.value));
                    }
                }
                InputOutcome::Continue => self.modal = Some(Modal::EditField { field, input }),
            },
            Modal::Choice {
                key: field_key,
                label,
                options,
                mut selected,
            } => {
                match key.code {
                    KeyCode::Esc => {}
                    KeyCode::Up | KeyCode::Char('k') => {
                        selected = wrap_index(selected, options.len(), -1)
                    }
                    KeyCode::Down | KeyCode::Char('j') => {
                        selected = wrap_index(selected, options.len(), 1)
                    }
                    KeyCode::Enter => {
                        if let Some(option) = options.get(selected) {
                            let value = if option.value == "true" {
                                Value::Bool(true)
                            } else if option.value == "false" {
                                Value::Bool(false)
                            } else {
                                Value::String(option.value.clone())
                            };
                            self.apply_field_value(&field_key, value);
                            return Ok(());
                        }
                    }
                    _ => {}
                }
                self.modal = Some(Modal::Choice {
                    key: field_key,
                    label,
                    options,
                    selected,
                });
            }
            Modal::FieldPicker {
                title,
                field_indices,
                mut selected,
            } => {
                match key.code {
                    KeyCode::Esc => return Ok(()),
                    KeyCode::Up | KeyCode::Char('k') => {
                        selected = wrap_index(selected, field_indices.len(), -1)
                    }
                    KeyCode::Down | KeyCode::Char('j') => {
                        selected = wrap_index(selected, field_indices.len(), 1)
                    }
                    KeyCode::Enter => {
                        if let Some(index) = field_indices.get(selected).copied() {
                            self.open_field_editor(index);
                            return Ok(());
                        }
                    }
                    _ => {}
                }
                self.modal = Some(Modal::FieldPicker {
                    title,
                    field_indices,
                    selected,
                });
            }
            Modal::ProviderEditor {
                existing_id,
                mut draft,
                mut selected,
                mut editing,
            } => {
                if let Some(mut input) = editing.take() {
                    match edit_input(&mut input, key) {
                        InputOutcome::Cancel => {}
                        InputOutcome::Submit => draft.set_value(selected, input.value),
                        InputOutcome::Continue => editing = Some(input),
                    }
                    self.modal = Some(Modal::ProviderEditor {
                        existing_id,
                        draft,
                        selected,
                        editing,
                    });
                    return Ok(());
                }
                match key.code {
                    KeyCode::Esc => return Ok(()),
                    KeyCode::Up | KeyCode::Char('k') => selected = wrap_index(selected, 8, -1),
                    KeyCode::Down | KeyCode::Char('j') => selected = wrap_index(selected, 8, 1),
                    KeyCode::Char(' ') | KeyCode::Enter if selected == 6 => {
                        draft.local = !draft.local
                    }
                    KeyCode::Char(' ') | KeyCode::Enter if selected == 7 => {
                        draft.enabled = !draft.enabled
                    }
                    KeyCode::Enter => {
                        if let Some((value, multiline, secret)) = draft.edit_value(selected) {
                            editing = Some(TextInput::new(value, multiline, secret));
                        }
                    }
                    KeyCode::Char('s') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                        self.save_provider(existing_id, draft);
                        return Ok(());
                    }
                    _ => {}
                }
                self.modal = Some(Modal::ProviderEditor {
                    existing_id,
                    draft,
                    selected,
                    editing,
                });
            }
            Modal::Confirm {
                title,
                body,
                action,
            } => match key.code {
                KeyCode::Esc | KeyCode::Char('n') => {}
                KeyCode::Enter | KeyCode::Char('y') => self.execute_confirm(action),
                _ => {
                    self.modal = Some(Modal::Confirm {
                        title,
                        body,
                        action,
                    })
                }
            },
        }
        Ok(())
    }

    fn save_provider(&mut self, existing_id: Option<String>, draft: ProviderDraft) {
        if self.bootstrap_mode {
            let _ = (existing_id, draft);
            self.set_notice(
                "Custom provider changes are available after the server starts.".to_string(),
            );
            return;
        }
        let payload = draft.payload(existing_id.is_some());
        let result = if let Some(existing_id) = existing_id.as_deref() {
            self.api.update_custom_provider(existing_id, &payload)
        } else {
            self.api.add_custom_provider(&payload)
        };
        match result {
            Ok(_) => {
                self.refresh_all();
                self.set_notice("Custom provider saved".to_string());
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn execute_confirm(&mut self, action: ConfirmAction) {
        match action {
            ConfirmAction::ClearField(key) => {
                self.apply_field_value(&key, Value::String(String::new()))
            }
            ConfirmAction::DeleteCustom(provider_id) => {
                match self.api.remove_custom_provider(&provider_id) {
                    Ok(_) => {
                        self.refresh_all();
                        self.set_notice(format!("Deleted {provider_id}"));
                    }
                    Err(error) => self.set_error(error.to_string()),
                }
            }
            ConfirmAction::DisconnectProvider(provider_id) => {
                match self.api.connected_account_disconnect(&provider_id) {
                    Ok(value) => {
                        self.refresh_all();
                        self.modal = Some(Modal::Message {
                            title: "Account disconnected".to_string(),
                            body: pretty(&value),
                        });
                    }
                    Err(error) => self.set_error(error.to_string()),
                }
            }
        }
    }

    pub fn display_field_value(field: &ConfigField) -> String {
        if field.secret {
            if field.configured {
                return "••••••••  configured".to_string();
            }
            return "Not configured".to_string();
        }
        let compact = field.value.replace('\n', " ↵ ");
        if compact.is_empty() {
            "—".to_string()
        } else if compact.chars().count() > 54 {
            format!("{}…", compact.chars().take(53).collect::<String>())
        } else {
            compact
        }
    }

    pub fn status_model(&self) -> String {
        self.status
            .get("model")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string()
    }

    pub fn status_text(&self) -> String {
        let host = if self.server_identity.host.is_empty() {
            self.status
                .get("host")
                .and_then(Value::as_str)
                .unwrap_or("127.0.0.1")
        } else {
            self.server_identity.host.as_str()
        };
        let port = if self.server_identity.port == 0 {
            self.status.get("port").and_then(Value::as_u64).unwrap_or(0) as u16
        } else {
            self.server_identity.port
        };
        format!("{} · {host}:{port}", self.connection_state.label())
    }

    pub fn last_check_label(&self) -> String {
        match self.last_check_epoch {
            Some(epoch) => format!("{}s ago", now_epoch().saturating_sub(epoch)),
            None => "never".to_string(),
        }
    }

    pub fn set_notice(&mut self, message: String) {
        self.notice = Some(message);
        self.error = None;
    }

    pub fn set_error(&mut self, message: String) {
        self.error = Some(message);
    }

    #[cfg(test)]
    pub fn fixture() -> Self {
        use serde_json::json;

        let api = AdminClient::new("http://127.0.0.1:8082").unwrap();
        let context = ConfigField {
            key: CONTEXT_KEY.to_string(),
            label: "Claude Context Window (tokens)".to_string(),
            section_id: "models".to_string(),
            field_type: "number".to_string(),
            value: "256000".to_string(),
            configured: true,
            description: "New FCC-launched Claude sessions.".to_string(),
            ..ConfigField::default()
        };
        let mut app = Self {
            api,
            page: Page::Dashboard,
            config: ConfigResponse {
                fields: vec![context],
                ..ConfigResponse::default()
            },
            status: json!({"status":"running","host":"127.0.0.1","port":8082,"model":"demo/model"}),
            server_identity: ServerIdentity {
                service: "agentswitchboard".to_string(),
                protocol: 1,
                mode: "standard".to_string(),
                status: "healthy".to_string(),
                ..ServerIdentity::default()
            },
            connection_state: ConnectionState::Running,
            last_check_epoch: Some(now_epoch()),
            last_connection_error: None,
            models: ModelsResponse::default(),
            custom_providers: Vec::new(),
            local_status: Vec::new(),
            usage: Value::Null,
            diagnostic: Value::Null,
            repositories: Vec::new(),
            repository_selected: 0,
            selected_repo_path: None,
            provider_selected: 0,
            routing_selected: 0,
            local_selected: 0,
            setting_selected: 0,
            browser: ModelBrowser::default(),
            show_advanced: false,
            modal: None,
            notice: None,
            error: None,
            should_quit: false,
            hitboxes: Vec::new(),
            geometry: ChromeGeometry::default(),
            mouse: None,
            bootstrap_mode: false,
            staged_values: HashMap::new(),
            bootstrap_result_path: None,
            bootstrap_launch_after_repository: false,
            bootstrap_launch_danger: false,
            start_server_requested: false,
        };
        app.sync_model_browser();
        app
    }
}

fn now_epoch() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0)
}

fn identity_from_status(status: &Value) -> ServerIdentity {
    serde_json::from_value(status.clone()).unwrap_or_default()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum InputOutcome {
    Continue,
    Submit,
    Cancel,
}

fn edit_input(input: &mut TextInput, key: KeyEvent) -> InputOutcome {
    match key.code {
        KeyCode::Esc => InputOutcome::Cancel,
        KeyCode::Enter if !input.multiline || key.modifiers.contains(KeyModifiers::CONTROL) => {
            InputOutcome::Submit
        }
        KeyCode::Enter => {
            input.insert_char('\n');
            InputOutcome::Continue
        }
        KeyCode::Backspace => {
            input.backspace();
            InputOutcome::Continue
        }
        KeyCode::Delete => {
            input.delete();
            InputOutcome::Continue
        }
        KeyCode::Left => {
            input.move_left();
            InputOutcome::Continue
        }
        KeyCode::Right => {
            input.move_right();
            InputOutcome::Continue
        }
        KeyCode::Home => {
            input.cursor = 0;
            InputOutcome::Continue
        }
        KeyCode::End => {
            input.cursor = input.value.len();
            InputOutcome::Continue
        }
        KeyCode::Char(character) if !key.modifiers.contains(KeyModifiers::CONTROL) => {
            input.insert_char(character);
            InputOutcome::Continue
        }
        _ => InputOutcome::Continue,
    }
}

fn config_value_string(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(value) => value.clone(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        other => other.to_string(),
    }
}

fn wrap_index(current: usize, len: usize, delta: isize) -> usize {
    if len == 0 {
        return 0;
    }
    (current as isize + delta).rem_euclid(len as isize) as usize
}

fn clamp(current: usize, len: usize) -> usize {
    if len == 0 {
        0
    } else {
        current.min(len - 1)
    }
}

fn contains(rect: Rect, x: u16, y: u16) -> bool {
    x >= rect.x
        && x < rect.x.saturating_add(rect.width)
        && y >= rect.y
        && y < rect.y.saturating_add(rect.height)
}

pub fn pretty(value: &Value) -> String {
    serde_json::to_string_pretty(value).unwrap_or_else(|_| value.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn connection_state_labels_and_status_text_show_liveness() {
        assert_eq!(ConnectionState::Starting.label(), "STARTING");
        assert_eq!(ConnectionState::Running.label(), "RUNNING");
        assert_eq!(ConnectionState::Degraded.label(), "DEGRADED");
        assert_eq!(ConnectionState::Offline.label(), "OFFLINE");
        assert_eq!(ConnectionState::Unknown.label(), "UNKNOWN");

        let mut app = App::fixture();
        app.connection_state = ConnectionState::Offline;
        app.server_identity.host = "127.0.0.1".to_string();
        app.server_identity.port = 8083;
        assert_eq!(app.status_text(), "OFFLINE · 127.0.0.1:8083");
    }

    #[test]
    fn offline_state_retains_last_server_identity_for_diagnostics() {
        let mut app = App::fixture();
        app.server_identity.instance_id = "0123456789abcdef".to_string();
        app.server_identity.pid = 12345;
        app.server_identity.uptime_seconds = 3661.0;
        app.connection_state = ConnectionState::Offline;
        app.last_connection_error = Some("connection refused".to_string());

        assert_eq!(app.server_identity.instance_id, "0123456789abcdef");
        assert_eq!(app.server_identity.pid, 12345);
        assert_eq!(app.server_identity.uptime_seconds, 3661.0);
        assert_eq!(
            app.last_connection_error.as_deref(),
            Some("connection refused")
        );
    }

    #[test]
    fn configured_secret_is_never_rendered() {
        let field = ConfigField {
            secret: true,
            configured: true,
            value: MASKED_SECRET.to_string(),
            ..ConfigField::default()
        };
        let rendered = App::display_field_value(&field);
        assert!(!rendered.contains(MASKED_SECRET));
        assert!(rendered.contains("configured"));
    }

    #[test]
    fn app_settings_exclude_provider_registration_fields() {
        let mut app = App::fixture();
        app.config.fields.extend([
            ConfigField {
                key: "BAI_API_KEY".to_string(),
                label: "B.AI API Key".to_string(),
                section_id: "providers".to_string(),
                secret: true,
                configured: true,
                ..ConfigField::default()
            },
            ConfigField {
                key: "BAI_BASE_URL".to_string(),
                label: "B.AI Base URL".to_string(),
                section_id: "providers".to_string(),
                ..ConfigField::default()
            },
            ConfigField {
                key: "FCC_PROVIDER_POLICY_MODE".to_string(),
                label: "Provider Policy Mode".to_string(),
                section_id: "runtime".to_string(),
                ..ConfigField::default()
            },
        ]);

        let settings = app.settings_field_indices();
        assert!(!settings
            .iter()
            .any(|index| app.config.fields[*index].key == "BAI_API_KEY"));
        assert!(!settings
            .iter()
            .any(|index| app.config.fields[*index].key == "BAI_BASE_URL"));
        assert!(settings
            .iter()
            .any(|index| app.config.fields[*index].key == "FCC_PROVIDER_POLICY_MODE"));
    }

    #[test]
    fn editing_custom_provider_with_blank_key_preserves_key() {
        let provider = CustomProvider {
            provider_id: "lab".to_string(),
            display_name: "Lab".to_string(),
            base_url: "https://example.invalid/v1".to_string(),
            enabled: true,
            api_key_configured: true,
            ..CustomProvider::default()
        };
        let draft = ProviderDraft::from_existing(&provider);
        let payload = draft.payload(true);
        assert!(payload.api_key.is_none());
    }

    #[test]
    fn editing_custom_provider_with_blank_proxy_preserves_proxy() {
        let provider = CustomProvider {
            provider_id: "lab".to_string(),
            display_name: "Lab".to_string(),
            base_url: "https://example.invalid/v1".to_string(),
            enabled: true,
            proxy_configured: true,
            ..CustomProvider::default()
        };
        let draft = ProviderDraft::from_existing(&provider);
        let payload = draft.payload(true);
        assert!(payload.proxy.is_none());
        assert_eq!(draft.field_value(4), "configured — blank preserves");
    }

    #[test]
    fn model_selection_navigates_visible_and_catalog_rows() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/free".to_string()];
        app.models.catalog_models = vec![
            "provider/free".to_string(),
            "provider/hidden-free".to_string(),
        ];
        app.models.catalog_model_labels.insert(
            "provider/hidden-free".to_string(),
            "Hidden Free".to_string(),
        );
        app.sync_model_browser();
        app.browser.toggle_catalog();

        let visible = app.filtered_models();
        assert!(visible.contains(&"provider/free".to_string()));
        assert!(visible.contains(&"provider/hidden-free".to_string()));
        app.handle_event(Event::Key(KeyEvent::new(KeyCode::Down, KeyModifiers::NONE)))
            .unwrap();
        assert_eq!(app.browser.selected, 1);
        assert_eq!(app.selected_model().as_deref(), Some(visible[1].as_str()));
        assert!(!app.model_is_routable("provider/hidden-free"));

        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('/'),
            KeyModifiers::NONE,
        )))
        .unwrap();
        for character in ['h', 'i', 'd', 'd', 'e', 'n'] {
            app.handle_event(Event::Key(KeyEvent::new(
                KeyCode::Char(character),
                KeyModifiers::NONE,
            )))
            .unwrap();
        }
        assert_eq!(app.filtered_models(), ["provider/hidden-free"]);
        assert_eq!(app.browser.selected, 0);
        assert!(app.browser.search_focused);
    }

    #[test]
    fn blocked_catalog_model_can_be_enabled_and_selected_as_active() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/routable".to_string()];
        app.models.catalog_models = vec![
            "provider/routable".to_string(),
            "provider/hidden".to_string(),
        ];
        app.config.fields.push(ConfigField {
            key: MODEL_KEY.to_string(),
            value: "provider/routable".to_string(),
            ..ConfigField::default()
        });
        app.sync_model_browser();
        app.browser.toggle_catalog();
        app.browser.query = "hidden".to_string();
        app.clamp_selections();

        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();

        assert!(app.error.is_none());
        assert_eq!(app.browser.pending_model(), "provider/hidden");
        assert!(app.browser.is_enabled("provider/hidden"));
        assert!(app.browser.dirty());
        let payload = app.browser.save_payload();
        assert_eq!(
            payload.get(MODEL_KEY),
            Some(&Value::String("provider/hidden".to_string()))
        );
    }

    #[test]
    fn unavailable_configured_model_stays_visible_in_chrome() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/alpha".to_string()];
        app.models.catalog_models = vec!["provider/alpha".to_string()];
        app.config.fields.push(ConfigField {
            key: MODEL_KEY.to_string(),
            value: "gateway/missing".to_string(),
            ..ConfigField::default()
        });
        app.sync_model_browser();
        let snapshot = app.catalog_snapshot();
        assert_eq!(app.browser.pending_model(), "gateway/missing");
        assert!(app.browser.active_model_unavailable(&snapshot));
        assert!(!app.browser.dirty());
        assert_eq!(app.filtered_models(), ["provider/alpha"]);
    }

    #[test]
    fn model_rows_are_selectable_with_a_mouse_click() {
        use ratatui::backend::TestBackend;
        use ratatui::Terminal;

        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/one".to_string(), "provider/two".to_string()];
        app.models.catalog_models = app.models.models.clone();
        app.sync_model_browser();
        let backend = TestBackend::new(160, 50);
        let mut terminal = Terminal::new(backend).unwrap();
        terminal
            .draw(|frame| crate::ui::render(frame, &mut app))
            .unwrap();
        let rect = app
            .hitboxes
            .iter()
            .find_map(|hitbox| match &hitbox.action {
                UiAction::SelectModel(1) => Some(hitbox.rect),
                _ => None,
            })
            .expect("second model row should have a hitbox");

        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::NONE,
        }))
        .unwrap();

        assert_eq!(app.browser.selected, 1);
        assert_eq!(app.selected_model().as_deref(), Some("provider/two"));
    }

    #[test]
    fn bootstrap_model_save_writes_a_private_parent_handoff() {
        use std::fs;

        let result_path = std::env::temp_dir().join(format!(
            "fcc-control-center-test-{}-result.json",
            std::process::id()
        ));
        let state = BootstrapState {
            config: ConfigResponse {
                fields: vec![
                    ConfigField {
                        key: MODEL_KEY.to_string(),
                        value: "provider/one".to_string(),
                        configured: true,
                        ..ConfigField::default()
                    },
                    ConfigField {
                        key: crate::models::CATALOG_MODE_KEY.to_string(),
                        value: "all".to_string(),
                        ..ConfigField::default()
                    },
                    ConfigField {
                        key: crate::models::CATALOG_ALLOWLIST_KEY.to_string(),
                        ..ConfigField::default()
                    },
                ],
                ..ConfigResponse::default()
            },
            models: ModelsResponse {
                models: vec!["provider/one".to_string(), "provider/two".to_string()],
                catalog_models: vec!["provider/one".to_string(), "provider/two".to_string()],
                ..ModelsResponse::default()
            },
            status: json!({"status": "prelaunch", "host": "127.0.0.1", "port": 8082}),
            ..BootstrapState::default()
        };
        let api = AdminClient::new("http://127.0.0.1:8082").unwrap();
        let mut app = App::from_bootstrap(api, state, None, result_path.clone());
        app.page = Page::Models;
        app.browser.selected = 1;

        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('s'),
            KeyModifiers::CONTROL,
        )))
        .unwrap();

        let result: Value = serde_json::from_str(
            &fs::read_to_string(&result_path).expect("bootstrap result should exist"),
        )
        .unwrap();
        assert_eq!(result["values"][MODEL_KEY], "provider/two");
        assert_eq!(result["start_server"], false);
        assert!(!app.browser.dirty());
        #[cfg(unix)]
        assert_eq!(
            fs::metadata(&result_path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        let _ = fs::remove_file(result_path);
    }

    #[test]
    fn bootstrap_quit_auto_saves_pending_model_change() {
        use std::fs;

        let result_path = std::env::temp_dir().join(format!(
            "fcc-control-center-test-{}-quit.json",
            std::process::id()
        ));
        let state = BootstrapState {
            config: ConfigResponse {
                fields: vec![ConfigField {
                    key: MODEL_KEY.to_string(),
                    value: "provider/one".to_string(),
                    configured: true,
                    ..ConfigField::default()
                }],
                ..ConfigResponse::default()
            },
            models: ModelsResponse {
                models: vec!["provider/one".to_string(), "provider/two".to_string()],
                ..ModelsResponse::default()
            },
            ..BootstrapState::default()
        };
        let api = AdminClient::new("http://127.0.0.1:8082").unwrap();
        let mut app = App::from_bootstrap(api, state, None, result_path.clone());
        app.page = Page::Models;
        app.browser.selected = 1;
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('q'),
            KeyModifiers::NONE,
        )))
        .unwrap();

        let result: Value =
            serde_json::from_str(&fs::read_to_string(&result_path).unwrap()).unwrap();
        assert_eq!(result["values"][MODEL_KEY], "provider/two");
        assert_eq!(result["start_server"], false);
        assert!(app.should_quit);
        let _ = fs::remove_file(result_path);
    }

    #[test]
    fn launch_path_follows_highlighted_repository_not_stale_persisted_path() {
        let mut app = App::fixture();
        app.repositories = vec![
            Repository {
                path: "/sandbox/first".to_string(),
                ..Repository::default()
            },
            Repository {
                path: "/sandbox/selected".to_string(),
                ..Repository::default()
            },
        ];
        app.repository_selected = 1;
        app.selected_repo_path = Some("/sandbox/first".to_string());

        assert_eq!(app.launch_repository_path(), Some("/sandbox/selected"));
    }

    #[test]
    fn direct_bootstrap_uses_repository_selection_as_final_launch_handoff() {
        use std::fs;

        let result_path = std::env::temp_dir().join(format!(
            "fcc-control-center-test-{}-direct.json",
            std::process::id()
        ));
        let repository_path = std::env::temp_dir().join(format!(
            "fcc-control-center-test-{}-repository",
            std::process::id()
        ));
        let state = BootstrapState {
            models: ModelsResponse {
                models: vec!["provider/one".to_string()],
                ..ModelsResponse::default()
            },
            repositories: RepositoriesResponse {
                repositories: vec![Repository {
                    path: repository_path.to_string_lossy().into_owned(),
                    identity: "owner/repository".to_string(),
                    ..Repository::default()
                }],
                ..RepositoriesResponse::default()
            },
            launch_after_repository: true,
            launch_danger: true,
            ..BootstrapState::default()
        };
        let api = AdminClient::new("http://127.0.0.1:8082").unwrap();
        let mut app = App::from_bootstrap(api, state, None, result_path.clone());

        assert_eq!(app.bootstrap_repository_action_label(), "Launch danger");
        app.page = Page::Repositories;
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();

        let result: Value =
            serde_json::from_str(&fs::read_to_string(&result_path).unwrap()).unwrap();
        assert_eq!(
            result["selected_repository"],
            repository_path.to_string_lossy().as_ref()
        );
        assert_eq!(result["start_server"], true);
        assert!(app.should_quit);

        let _ = fs::remove_file(result_path);
    }

    #[test]
    fn modified_model_click_toggles_access_but_plain_click_only_selects() {
        use ratatui::backend::TestBackend;
        use ratatui::Terminal;

        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/one".to_string(), "provider/two".to_string()];
        app.models.catalog_models = app.models.models.clone();
        app.config.fields.extend([
            ConfigField {
                key: "MODEL_CATALOG_MODE".to_string(),
                value: "curated".to_string(),
                ..ConfigField::default()
            },
            ConfigField {
                key: "MODEL_CATALOG_ALLOWLIST".to_string(),
                value: "provider/one".to_string(),
                ..ConfigField::default()
            },
        ]);
        app.sync_model_browser();
        app.browser.toggle_catalog();
        let mut terminal = Terminal::new(TestBackend::new(160, 50)).unwrap();
        terminal
            .draw(|frame| crate::ui::render(frame, &mut app))
            .unwrap();
        let rect = app
            .hitboxes
            .iter()
            .find_map(|hitbox| match &hitbox.action {
                UiAction::SelectModel(1) => Some(hitbox.rect),
                _ => None,
            })
            .expect("second model row should have a hitbox");

        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::NONE,
        }))
        .unwrap();
        assert!(!app.browser.is_enabled("provider/two"));

        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::SHIFT,
        }))
        .unwrap();
        assert!(app.browser.is_enabled("provider/two"));
    }

    #[test]
    fn list_navigation_stops_at_model_edges() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/one".to_string(), "provider/two".to_string()];
        app.models.catalog_models = app.models.models.clone();
        app.sync_model_browser();

        app.handle_event(Event::Key(KeyEvent::new(KeyCode::Up, KeyModifiers::NONE)))
            .unwrap();
        assert_eq!(app.browser.selected, 0);

        app.handle_event(Event::Key(KeyEvent::new(KeyCode::Down, KeyModifiers::NONE)))
            .unwrap();
        app.handle_event(Event::Key(KeyEvent::new(KeyCode::Down, KeyModifiers::NONE)))
            .unwrap();
        assert_eq!(app.browser.selected, 1);
    }
}
