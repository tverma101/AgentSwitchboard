use crate::api::{
    AdminClient, ConfigField, ConfigOption, ConfigResponse, CustomProvider,
    CustomProviderPayload, ModelsResponse, ProviderStatus, MASKED_SECRET,
};
use anyhow::Result;
use crossterm::event::{Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent, MouseEventKind};
use ratatui::layout::Rect;
use serde_json::{json, Value};

pub const CONTEXT_KEY: &str = "FCC_CLAUDE_CONTEXT_TOKENS";
pub const CONTEXT_MIN: u32 = 32_000;
pub const CONTEXT_MAX: u32 = 1_000_000;
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Dashboard,
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
    pub const ALL: [Self; 9] = [
        Self::Dashboard,
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
            Self::Providers => "Providers",
            Self::Models => "Models",
            Self::Routing => "Routing",
            Self::Context => "Context Window",
            Self::Local => "Local Setup",
            Self::Settings => "Settings",
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
    SelectProvider(usize),
    SelectModel(usize),
    SelectRouting(usize),
    SelectLocal(usize),
    SelectSetting(usize),
    Refresh,
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
    RunDiagnostic,
    LaunchClaude(bool),
}

#[derive(Debug, Clone)]
pub struct Hitbox {
    pub rect: Rect,
    pub action: UiAction,
}

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
            4 => self.proxy.clone(),
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
            proxy: Some(self.proxy.trim().to_string()),
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
    SearchModels {
        input: TextInput,
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
    Help,
}

pub struct App {
    pub api: AdminClient,
    pub page: Page,
    pub config: ConfigResponse,
    pub status: Value,
    pub models: ModelsResponse,
    pub custom_providers: Vec<CustomProvider>,
    pub local_status: Vec<ProviderStatus>,
    pub usage: Value,
    pub diagnostic: Value,
    pub provider_selected: usize,
    pub model_selected: usize,
    pub routing_selected: usize,
    pub local_selected: usize,
    pub setting_selected: usize,
    pub model_query: String,
    pub show_advanced: bool,
    pub modal: Option<Modal>,
    pub notice: Option<String>,
    pub error: Option<String>,
    pub should_quit: bool,
    pub hitboxes: Vec<Hitbox>,
    pub geometry: ChromeGeometry,
    pub mouse: Option<(u16, u16)>,
}

impl App {
    pub fn load(api: AdminClient, notice: Option<String>) -> Result<Self> {
        let config = api.config()?;
        let status = api.status().unwrap_or(Value::Null);
        let models = api.models().unwrap_or_default();
        let custom_providers = api.custom_providers().unwrap_or_default().providers;
        let local_status = api.local_provider_status().unwrap_or_default().providers;
        let usage = api.usage(30).unwrap_or(Value::Null);
        Ok(Self {
            api,
            page: Page::Dashboard,
            config,
            status,
            models,
            custom_providers,
            local_status,
            usage,
            diagnostic: Value::Null,
            provider_selected: 0,
            model_selected: 0,
            routing_selected: 0,
            local_selected: 0,
            setting_selected: 0,
            model_query: String::new(),
            show_advanced: false,
            modal: None,
            notice,
            error: None,
            should_quit: false,
            hitboxes: Vec::new(),
            geometry: ChromeGeometry::default(),
            mouse: None,
        })
    }

    pub fn refresh_all(&mut self) {
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
            self.should_quit = true;
            return Ok(None);
        }
        match key.code {
            KeyCode::Char('q') => self.should_quit = true,
            KeyCode::Char('?') | KeyCode::F(1) => self.modal = Some(Modal::Help),
            KeyCode::Tab => self.next_page(1),
            KeyCode::BackTab => self.next_page(-1),
            KeyCode::Up | KeyCode::Char('k') => self.move_selection(-1),
            KeyCode::Down | KeyCode::Char('j') => self.move_selection(1),
            KeyCode::Char('r') => self.refresh_current(),
            KeyCode::Char('c') => return Ok(Some(ExternalAction::LaunchClaude { danger: false })),
            KeyCode::Enter => self.default_action()?,
            KeyCode::Char('e') => self.edit_action()?,
            KeyCode::Char('t') if self.page == Page::Providers => self.test_selected_provider(),
            KeyCode::Char('n') if self.page == Page::Providers => self.new_custom_provider(),
            KeyCode::Char('x') if self.page == Page::Providers => self.delete_custom_provider(),
            KeyCode::Char('l') if self.page == Page::Providers => self.login_provider("browser"),
            KeyCode::Char('L') if self.page == Page::Providers => self.login_provider("device"),
            KeyCode::Char('D') if self.page == Page::Providers => self.disconnect_provider(),
            KeyCode::Char('/') if self.page == Page::Models => {
                self.modal = Some(Modal::SearchModels {
                    input: TextInput::new(self.model_query.clone(), false, false),
                });
            }
            KeyCode::Char('d') if self.page == Page::Models => self.assign_selected_model("MODEL"),
            KeyCode::Char('f') if self.page == Page::Models => self.assign_selected_model("MODEL_FABLE"),
            KeyCode::Char('o') if self.page == Page::Models => self.assign_selected_model("MODEL_OPUS"),
            KeyCode::Char('s') if self.page == Page::Models => self.assign_selected_model("MODEL_SONNET"),
            KeyCode::Char('h') if self.page == Page::Models => self.assign_selected_model("MODEL_HAIKU"),
            KeyCode::Char('a') if self.page == Page::Settings => self.show_advanced = !self.show_advanced,
            KeyCode::Char('x') if matches!(self.page, Page::Routing | Page::Context | Page::Local | Page::Settings) => {
                self.clear_selected_secret();
            }
            KeyCode::Char('!') => return Ok(Some(ExternalAction::LaunchClaude { danger: true })),
            _ => {}
        }
        Ok(None)
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
            return self.invoke_ui_action(action);
        }
        Ok(None)
    }

    fn invoke_ui_action(&mut self, action: UiAction) -> Result<Option<ExternalAction>> {
        match action {
            UiAction::Navigate(page) => self.page = page,
            UiAction::SelectProvider(index) => self.provider_selected = index,
            UiAction::SelectModel(index) => self.model_selected = index,
            UiAction::SelectRouting(index) => self.routing_selected = index,
            UiAction::SelectLocal(index) => self.local_selected = index,
            UiAction::SelectSetting(index) => self.setting_selected = index,
            UiAction::Refresh => self.refresh_current(),
            UiAction::ConfigureProvider => self.configure_selected_provider(),
            UiAction::TestProvider => self.test_selected_provider(),
            UiAction::NewCustomProvider => self.new_custom_provider(),
            UiAction::EditCustomProvider => self.edit_selected_custom_provider(),
            UiAction::DeleteCustomProvider => self.delete_custom_provider(),
            UiAction::LoginProvider => self.login_provider("browser"),
            UiAction::DisconnectProvider => self.disconnect_provider(),
            UiAction::EditField => self.edit_action()?,
            UiAction::ToggleAdvanced => self.show_advanced = !self.show_advanced,
            UiAction::AssignModel(key) => self.assign_selected_model(&key),
            UiAction::SearchModels => {
                self.modal = Some(Modal::SearchModels {
                    input: TextInput::new(self.model_query.clone(), false, false),
                });
            }
            UiAction::RunDiagnostic => self.run_diagnostic(),
            UiAction::LaunchClaude(danger) => {
                return Ok(Some(ExternalAction::LaunchClaude { danger }));
            }
        }
        Ok(None)
    }

    fn default_action(&mut self) -> Result<()> {
        match self.page {
            Page::Providers => self.configure_selected_provider(),
            Page::Models => self.assign_selected_model("MODEL"),
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
        match self.page {
            Page::Models => match self.api.refresh_models() {
                Ok(value) => {
                    self.models = value;
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
        let (selection, len) = match self.page {
            Page::Providers => (&mut self.provider_selected, self.config.provider_status.len()),
            Page::Models => (&mut self.model_selected, self.filtered_models().len()),
            Page::Routing => (&mut self.routing_selected, self.routing_field_indices().len()),
            Page::Local => (&mut self.local_selected, self.local_field_indices().len()),
            Page::Settings => (&mut self.setting_selected, self.settings_field_indices().len()),
            _ => return,
        };
        if len == 0 {
            *selection = 0;
            return;
        }
        *selection = ((*selection as isize + delta).rem_euclid(len as isize)) as usize;
    }

    fn clamp_selections(&mut self) {
        self.provider_selected = clamp(self.provider_selected, self.config.provider_status.len());
        self.model_selected = clamp(self.model_selected, self.filtered_models().len());
        self.routing_selected = clamp(self.routing_selected, self.routing_field_indices().len());
        self.local_selected = clamp(self.local_selected, self.local_field_indices().len());
        self.setting_selected = clamp(self.setting_selected, self.settings_field_indices().len());
    }

    pub fn filtered_models(&self) -> Vec<String> {
        let query = self.model_query.trim().to_ascii_lowercase();
        self.models
            .models
            .iter()
            .filter(|model| {
                if query.is_empty() {
                    return true;
                }
                let label = self.models.model_labels.get(*model).map(String::as_str).unwrap_or("");
                model.to_ascii_lowercase().contains(&query)
                    || label.to_ascii_lowercase().contains(&query)
            })
            .cloned()
            .collect()
    }

    pub fn routing_field_indices(&self) -> Vec<usize> {
        ROUTING_KEYS
            .iter()
            .filter_map(|key| self.config.fields.iter().position(|field| field.key == *key))
            .collect()
    }

    pub fn local_field_indices(&self) -> Vec<usize> {
        LOCAL_KEYS
            .iter()
            .filter_map(|key| self.config.fields.iter().position(|field| field.key == *key))
            .collect()
    }

    pub fn settings_field_indices(&self) -> Vec<usize> {
        self.config
            .fields
            .iter()
            .enumerate()
            .filter(|(_, field)| field.key != "CUSTOM_PROVIDERS_JSON")
            .filter(|(_, field)| self.show_advanced || !field.advanced)
            .map(|(index, _)| index)
            .collect()
    }

    pub fn context_field(&self) -> Option<&ConfigField> {
        self.config.fields.iter().find(|field| field.key == CONTEXT_KEY)
    }

    pub fn selected_provider(&self) -> Option<&ProviderStatus> {
        self.config.provider_status.get(self.provider_selected)
    }

    pub fn selected_model(&self) -> Option<String> {
        self.filtered_models().get(self.model_selected).cloned()
    }

    pub fn selected_field_index(&self) -> Option<usize> {
        match self.page {
            Page::Routing => self.routing_field_indices().get(self.routing_selected).copied(),
            Page::Context => self.config.fields.iter().position(|field| field.key == CONTEXT_KEY),
            Page::Local => self.local_field_indices().get(self.local_selected).copied(),
            Page::Settings => self.settings_field_indices().get(self.setting_selected).copied(),
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
            .filter_map(|key| self.config.fields.iter().position(|field| field.key == *key))
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
                    ConfigOption { value: "true".to_string(), label: "Enabled".to_string() },
                    ConfigOption { value: "false".to_string(), label: "Disabled".to_string() },
                ],
                selected: if field.value.eq_ignore_ascii_case("false") { 1 } else { 0 },
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
            let candidate = value.as_str().unwrap_or_default();
            if let Err(message) = validate_context(candidate) {
                self.set_error(message);
                return;
            }
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

    fn assign_selected_model(&mut self, key: &str) {
        let Some(model) = self.selected_model() else {
            return;
        };
        self.apply_field_value(key, Value::String(model.clone()));
        if self.error.is_none() {
            self.set_notice(format!("{key} → {model}"));
        }
    }

    fn test_selected_provider(&mut self) {
        let Some(provider) = self.selected_provider().cloned() else {
            return;
        };
        match self.api.test_provider(&provider.provider_id) {
            Ok(value) => self.modal = Some(Modal::Message {
                title: format!("{} test", provider.display_name),
                body: pretty(&value),
            }),
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn new_custom_provider(&mut self) {
        self.modal = Some(Modal::ProviderEditor {
            existing_id: None,
            draft: ProviderDraft::empty(),
            selected: 0,
            editing: None,
        });
    }

    fn edit_selected_custom_provider(&mut self) {
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
        let Some(provider) = self.selected_provider() else {
            return;
        };
        if !provider.custom {
            return;
        }
        self.modal = Some(Modal::Confirm {
            title: "Delete custom provider".to_string(),
            body: format!("Delete {} ({})?", provider.display_name, provider.provider_id),
            action: ConfirmAction::DeleteCustom(provider.provider_id.clone()),
        });
    }

    fn login_provider(&mut self, mode: &str) {
        let Some(provider) = self.selected_provider().cloned() else {
            return;
        };
        if provider.kind != "connected_account" {
            return;
        }
        match self.api.connected_account_login(&provider.provider_id, mode) {
            Ok(value) => self.modal = Some(Modal::Message {
                title: format!("{} sign-in", provider.display_name),
                body: pretty(&value),
            }),
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn disconnect_provider(&mut self) {
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
            Modal::Help => {
                if !matches!(key.code, KeyCode::Esc | KeyCode::Enter | KeyCode::Char('?')) {
                    self.modal = Some(Modal::Help);
                }
            }
            Modal::SearchModels { mut input } => match edit_input(&mut input, key) {
                InputOutcome::Cancel => {}
                InputOutcome::Submit => {
                    self.model_query = input.value.trim().to_string();
                    self.model_selected = 0;
                }
                InputOutcome::Continue => self.modal = Some(Modal::SearchModels { input }),
            },
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
            Modal::Choice { key: field_key, label, options, mut selected } => {
                match key.code {
                    KeyCode::Esc => {}
                    KeyCode::Up | KeyCode::Char('k') => selected = wrap_index(selected, options.len(), -1),
                    KeyCode::Down | KeyCode::Char('j') => selected = wrap_index(selected, options.len(), 1),
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
                self.modal = Some(Modal::Choice { key: field_key, label, options, selected });
            }
            Modal::FieldPicker { title, field_indices, mut selected } => {
                match key.code {
                    KeyCode::Esc => return Ok(()),
                    KeyCode::Up | KeyCode::Char('k') => selected = wrap_index(selected, field_indices.len(), -1),
                    KeyCode::Down | KeyCode::Char('j') => selected = wrap_index(selected, field_indices.len(), 1),
                    KeyCode::Enter => {
                        if let Some(index) = field_indices.get(selected).copied() {
                            self.open_field_editor(index);
                            return Ok(());
                        }
                    }
                    _ => {}
                }
                self.modal = Some(Modal::FieldPicker { title, field_indices, selected });
            }
            Modal::ProviderEditor { existing_id, mut draft, mut selected, mut editing } => {
                if let Some(mut input) = editing.take() {
                    match edit_input(&mut input, key) {
                        InputOutcome::Cancel => {}
                        InputOutcome::Submit => draft.set_value(selected, input.value),
                        InputOutcome::Continue => editing = Some(input),
                    }
                    self.modal = Some(Modal::ProviderEditor { existing_id, draft, selected, editing });
                    return Ok(());
                }
                match key.code {
                    KeyCode::Esc => return Ok(()),
                    KeyCode::Up | KeyCode::Char('k') => selected = wrap_index(selected, 8, -1),
                    KeyCode::Down | KeyCode::Char('j') => selected = wrap_index(selected, 8, 1),
                    KeyCode::Char(' ') | KeyCode::Enter if selected == 6 => draft.local = !draft.local,
                    KeyCode::Char(' ') | KeyCode::Enter if selected == 7 => draft.enabled = !draft.enabled,
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
                self.modal = Some(Modal::ProviderEditor { existing_id, draft, selected, editing });
            }
            Modal::Confirm { title, body, action } => match key.code {
                KeyCode::Esc | KeyCode::Char('n') => {}
                KeyCode::Enter | KeyCode::Char('y') => self.execute_confirm(action),
                _ => self.modal = Some(Modal::Confirm { title, body, action }),
            },
        }
        Ok(())
    }

    fn save_provider(&mut self, existing_id: Option<String>, draft: ProviderDraft) {
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
            ConfirmAction::ClearField(key) => self.apply_field_value(&key, Value::String(String::new())),
            ConfirmAction::DeleteCustom(provider_id) => match self.api.remove_custom_provider(&provider_id) {
                Ok(_) => {
                    self.refresh_all();
                    self.set_notice(format!("Deleted {provider_id}"));
                }
                Err(error) => self.set_error(error.to_string()),
            },
            ConfirmAction::DisconnectProvider(provider_id) => match self.api.connected_account_disconnect(&provider_id) {
                Ok(value) => {
                    self.refresh_all();
                    self.modal = Some(Modal::Message {
                        title: "Account disconnected".to_string(),
                        body: pretty(&value),
                    });
                }
                Err(error) => self.set_error(error.to_string()),
            },
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
        let status = self.status.get("status").and_then(Value::as_str).unwrap_or("offline");
        let host = self.status.get("host").and_then(Value::as_str).unwrap_or("127.0.0.1");
        let port = self.status.get("port").and_then(Value::as_u64).unwrap_or(0);
        format!("{status} · {host}:{port}")
    }

    pub fn current_context(&self) -> String {
        self.context_field()
            .map(|field| field.value.clone())
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "256000".to_string())
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
        Self {
            api,
            page: Page::Dashboard,
            config: ConfigResponse { fields: vec![context], ..ConfigResponse::default() },
            status: json!({"status":"running","host":"127.0.0.1","port":8082,"model":"demo/model"}),
            models: ModelsResponse::default(),
            custom_providers: Vec::new(),
            local_status: Vec::new(),
            usage: Value::Null,
            diagnostic: Value::Null,
            provider_selected: 0,
            model_selected: 0,
            routing_selected: 0,
            local_selected: 0,
            setting_selected: 0,
            model_query: String::new(),
            show_advanced: false,
            modal: None,
            notice: None,
            error: None,
            should_quit: false,
            hitboxes: Vec::new(),
            geometry: ChromeGeometry::default(),
            mouse: None,
        }
    }
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
        KeyCode::Enter if !input.multiline || key.modifiers.contains(KeyModifiers::CONTROL) => InputOutcome::Submit,
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

fn validate_context(value: &str) -> std::result::Result<u32, String> {
    let parsed = value
        .trim()
        .parse::<u32>()
        .map_err(|_| "Context window must be an integer token count".to_string())?;
    if !(CONTEXT_MIN..=CONTEXT_MAX).contains(&parsed) {
        return Err(format!(
            "Context window must be between {CONTEXT_MIN} and {CONTEXT_MAX} tokens"
        ));
    }
    Ok(parsed)
}

fn wrap_index(current: usize, len: usize, delta: isize) -> usize {
    if len == 0 {
        return 0;
    }
    (current as isize + delta).rem_euclid(len as isize) as usize
}

fn clamp(current: usize, len: usize) -> usize {
    if len == 0 { 0 } else { current.min(len - 1) }
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
    fn context_window_is_hard_bounded() {
        assert_eq!(validate_context("32000"), Ok(32_000));
        assert_eq!(validate_context("1000000"), Ok(1_000_000));
        assert!(validate_context("31999").is_err());
        assert!(validate_context("1000001").is_err());
        assert!(validate_context("banana").is_err());
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
}
