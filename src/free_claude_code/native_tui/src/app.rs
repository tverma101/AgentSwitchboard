use crate::api::{
    AdminClient, ApplyResponse, ConfigField, ConfigOption, ConfigResponse, CustomProvider,
    CustomProviderCollection, CustomProviderPayload, ModelsResponse, ProviderCollection,
    ProviderStatus, MASKED_SECRET,
};
use crate::theme::Colors;
use anyhow::Result;
use crossterm::event::{
    Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent, MouseEventKind,
};
use ratatui::layout::Rect;
use ratatui::widgets::{Paragraph, Wrap};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, TryRecvError};

type SnapshotResults = (
    Result<ConfigResponse>,
    Result<Value>,
    Result<ModelsResponse>,
    Result<CustomProviderCollection>,
    Result<ProviderCollection>,
    Result<Value>,
);

enum RefreshTask {
    All(Receiver<SnapshotResults>),
    Models(Receiver<Result<ModelsResponse>>),
    ModelPolicy(Receiver<Result<ApplyResponse>>, String),
}

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

/// Price filter for the model picker. Unknown pricing is kept visible in the
/// default view but is never mislabeled as paid or free.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ModelPriceFilter {
    FreeOnly,
    #[default]
    All,
}

/// Price evidence shown beside a model. Missing metadata stays unknown.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModelPriceState {
    Free,
    Paid,
    Unknown,
}

// Legacy explicit-file CLI actions remain available for compatibility, but
// none of these editor/workspace actions are exposed by the control-center
// render path or its command palette.
#[allow(dead_code)]
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
    ChooseModelProvider,
    ToggleModelSelection(usize),
    CycleModelProvider,
    CycleModelPrice,
    ToggleModelCatalog,
    ToggleSelectedModels,
    DisableAllModels,
    RunDiagnostic,
    LaunchClaude(bool),
    OpenPalette,
    ModalSelect(usize),
    ModalActivate(usize),
    Quit,
    Activity(Activity),
    ToggleSidebar,
    TogglePanel,
    FocusSidebar,
    FocusEditor,
    ActivateTree(usize),
    ActivateTab(usize),
    CloseFile(usize),
    RevealInExplorer,
    RefreshGit,
    SearchFiles,
    FindInFile,
    CloseActiveFile,
    OpenSearchHit(usize),
    OpenGitChange(usize),
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
    pub tabs: Rect,
    pub gutter: Rect,
    pub sidebar: Rect,
    pub main: Rect,
    pub editor: Rect,
    pub panel: Rect,
    pub statusbar: Rect,
    pub footer: Rect,
}

#[derive(Debug)]
pub enum ExternalAction {
    LaunchClaude { danger: bool },
    EditExternal { path: PathBuf },
}

/// One command-palette row. The palette is a compact index of AgentSwitchboard
/// pages and actions; it does not expose an editor/workbench command set.
#[derive(Debug, Clone)]
pub struct PaletteEntry {
    pub title: String,
    pub hint: String,
    pub action: UiAction,
}

/// Legacy workspace activity state retained for explicit file-oriented CLI
/// compatibility. The visible control center uses `Page` directly.
#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Activity {
    Explorer,
    Search,
    SourceControl,
    Providers,
    Models,
    Diagnostics,
}

#[allow(dead_code)]
impl Activity {
    pub const ALL: [Self; 6] = [
        Self::Explorer,
        Self::Search,
        Self::SourceControl,
        Self::Providers,
        Self::Models,
        Self::Diagnostics,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Explorer => "Explorer",
            Self::Search => "Search",
            Self::SourceControl => "Source Control",
            Self::Providers => "Providers",
            Self::Models => "Models",
            Self::Diagnostics => "Diagnostics",
        }
    }

    pub fn icon(self) -> &'static str {
        match self {
            Self::Explorer => "▤",
            Self::Search => "⌕",
            Self::SourceControl => "⎇",
            Self::Providers => "◈",
            Self::Models => "✦",
            Self::Diagnostics => "⚠",
        }
    }

    pub fn page(self) -> Option<Page> {
        match self {
            Self::Explorer | Self::Search | Self::SourceControl => None,
            Self::Providers => Some(Page::Providers),
            Self::Models => Some(Page::Models),
            Self::Diagnostics => Some(Page::Diagnostics),
        }
    }
}

/// Which control-center region owns the keyboard: page navigation or page.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Focus {
    Sidebar,
    #[default]
    Editor,
}

/// Which editor tab is visible: an opened workspace file or the FCC page.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EditorFocus {
    File(usize),
    Page,
}

#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct TreeEntry {
    pub path: PathBuf,
    pub name: String,
    pub depth: usize,
    pub is_dir: bool,
}

#[derive(Debug, Clone)]
pub struct OpenFile {
    pub path: PathBuf,
    pub lines: Vec<String>,
    pub scroll: usize,
    pub truncated: bool,
}

impl OpenFile {
    #[allow(dead_code)]
    pub fn title(&self) -> String {
        self.path
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_else(|| self.path.to_string_lossy().into_owned())
    }
}

#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct GitChange {
    pub path: String,
    pub staged: char,
    pub unstaged: char,
}

#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct SearchHit {
    pub path: PathBuf,
    pub line: usize,
    pub text: String,
}

pub const MAX_TREE_ENTRIES: usize = 500;
pub const MAX_TREE_DEPTH: usize = 6;
pub const MAX_FILE_BYTES: u64 = 1_048_576;
pub const MAX_FILE_LINES: usize = 10_000;
pub const MAX_SEARCH_HITS: usize = 100;
pub const MAX_SEARCH_FILES: usize = 2000;
pub const MAX_GIT_CHANGES: usize = 200;
const SKIP_DIRS: &[&str] = &[
    ".git",
    "target",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hg",
    ".svn",
];
/// Case-insensitive substring filter over palette titles and hints. Returns
/// indices into `entries` in stable inventory order.
pub fn match_palette(query: &str, entries: &[PaletteEntry]) -> Vec<usize> {
    let needle = query.trim().to_ascii_lowercase();
    entries
        .iter()
        .enumerate()
        .filter(|(_, entry)| {
            if needle.is_empty() {
                return true;
            }
            entry.title.to_ascii_lowercase().contains(&needle)
                || entry.hint.to_ascii_lowercase().contains(&needle)
        })
        .map(|(index, _)| index)
        .collect()
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
    SearchModels {
        input: TextInput,
    },
    SearchFiles {
        input: TextInput,
    },
    FindInFile {
        input: TextInput,
    },
    Palette {
        input: TextInput,
        selected: usize,
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
}

pub struct App {
    pub api: AdminClient,
    pub page: Page,
    pub colors: Colors,
    pub workspace: PathBuf,
    pub activity: Activity,
    pub focus: Focus,
    pub sidebar_open: bool,
    pub panel_open: bool,
    pub tree: Vec<TreeEntry>,
    pub tree_cursor: usize,
    pub expanded: HashSet<PathBuf>,
    pub files: Vec<OpenFile>,
    pub editor_focus: EditorFocus,
    pub search_query: String,
    pub search_hits: Vec<SearchHit>,
    pub find_needle: String,
    pub git_branch: String,
    pub git_changes: Vec<GitChange>,
    pub git_error: Option<String>,
    pub config: ConfigResponse,
    pub status: Value,
    pub models: ModelsResponse,
    pub custom_providers: Vec<CustomProvider>,
    pub local_status: Vec<ProviderStatus>,
    pub usage: Value,
    pub diagnostic: Value,
    /// Vertical offset for long JSON/status pages. It is deliberately shared
    /// by Usage and Diagnostics so the page remains a finite, visible
    /// document instead of a clipped terminal dump.
    pub content_scroll: usize,
    pub provider_selected: usize,
    pub model_selected: usize,
    pub routing_selected: usize,
    pub local_selected: usize,
    pub setting_selected: usize,
    pub model_query: String,
    pub model_provider_filter: String,
    pub model_price_filter: ModelPriceFilter,
    pub model_show_catalog: bool,
    pub selected_models: HashSet<String>,
    pub show_advanced: bool,
    pub modal: Option<Modal>,
    pub notice: Option<String>,
    pub error: Option<String>,
    pub should_quit: bool,
    pub sidebar_cursor: usize,
    pub hitboxes: Vec<Hitbox>,
    pub geometry: ChromeGeometry,
    pub mouse: Option<(u16, u16)>,
    refresh_task: Option<RefreshTask>,
    next_refresh_notice: Option<String>,
}

fn fetch_snapshot(api: &AdminClient) -> SnapshotResults {
    let config_api = api.clone();
    let status_api = api.clone();
    let models_api = api.clone();
    let custom_api = api.clone();
    let local_api = api.clone();
    let usage_api = api.clone();
    std::thread::scope(|scope| {
        let config = scope.spawn(move || config_api.config());
        let status = scope.spawn(move || status_api.status());
        let models = scope.spawn(move || models_api.models());
        let custom = scope.spawn(move || custom_api.custom_providers());
        let local = scope.spawn(move || local_api.local_provider_status());
        let usage = scope.spawn(move || usage_api.usage(30));
        (
            config
                .join()
                .unwrap_or_else(|_| Err(anyhow::anyhow!("config request thread panicked"))),
            status
                .join()
                .unwrap_or_else(|_| Err(anyhow::anyhow!("status request thread panicked"))),
            models
                .join()
                .unwrap_or_else(|_| Err(anyhow::anyhow!("model request thread panicked"))),
            custom.join().unwrap_or_else(|_| {
                Err(anyhow::anyhow!("custom-provider request thread panicked"))
            }),
            local
                .join()
                .unwrap_or_else(|_| Err(anyhow::anyhow!("local-provider request thread panicked"))),
            usage
                .join()
                .unwrap_or_else(|_| Err(anyhow::anyhow!("usage request thread panicked"))),
        )
    })
}

impl App {
    pub fn load(api: AdminClient, notice: Option<String>) -> Result<Self> {
        let mut load_errors = Vec::new();
        // The first screen should not wait for six serialized five-second
        // requests. Each snapshot is independent, so fetch them concurrently
        // and degrade to an actionable offline shell when the server is still
        // coming up or one endpoint is unavailable.
        let (
            config_result,
            status_result,
            models_result,
            custom_result,
            local_result,
            usage_result,
        ) = fetch_snapshot(&api);
        let config = match config_result {
            Ok(value) => value,
            Err(error) => {
                load_errors.push(format!("config: {error}"));
                ConfigResponse::default()
            }
        };
        let status = match status_result {
            Ok(value) => value,
            Err(error) => {
                load_errors.push(format!("status: {error}"));
                Value::Null
            }
        };
        let models = match models_result {
            Ok(value) => value,
            Err(error) => {
                load_errors.push(format!("models: {error}"));
                ModelsResponse::default()
            }
        };
        let custom_providers = match custom_result {
            Ok(value) => value.providers,
            Err(error) => {
                load_errors.push(format!("custom providers: {error}"));
                Vec::new()
            }
        };
        let local_status = match local_result {
            Ok(value) => value.providers,
            Err(error) => {
                load_errors.push(format!("local providers: {error}"));
                Vec::new()
            }
        };
        let usage = match usage_result {
            Ok(value) => value,
            Err(error) => {
                load_errors.push(format!("usage: {error}"));
                Value::Null
            }
        };
        Ok(Self {
            api,
            page: Page::Dashboard,
            colors: Colors::fallback(),
            workspace: std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")),
            activity: Activity::Explorer,
            focus: Focus::Editor,
            sidebar_open: true,
            panel_open: false,
            tree: Vec::new(),
            tree_cursor: 0,
            expanded: HashSet::new(),
            files: Vec::new(),
            editor_focus: EditorFocus::Page,
            search_query: String::new(),
            find_needle: String::new(),
            search_hits: Vec::new(),
            git_branch: String::new(),
            git_changes: Vec::new(),
            git_error: None,
            config,
            status,
            models,
            custom_providers,
            local_status,
            usage,
            diagnostic: Value::Null,
            content_scroll: 0,
            provider_selected: 0,
            model_selected: 0,
            routing_selected: 0,
            local_selected: 0,
            setting_selected: 0,
            model_query: String::new(),
            model_provider_filter: "all".to_string(),
            model_price_filter: ModelPriceFilter::default(),
            // Keep the first screen useful. The complete cache is an
            // explicit view because a 400-row metadata dump is not a model
            // selector.
            model_show_catalog: false,
            selected_models: HashSet::new(),
            show_advanced: false,
            modal: None,
            notice,
            error: (!load_errors.is_empty())
                .then(|| format!("Initial load incomplete — {}", load_errors.join(" · "))),
            should_quit: false,
            sidebar_cursor: 0,
            hitboxes: Vec::new(),
            geometry: ChromeGeometry::default(),
            mouse: None,
            refresh_task: None,
            next_refresh_notice: None,
        })
    }

    /// Point the control center at a workspace directory for status and
    /// explicit CLI file-preview compatibility.
    pub fn set_workspace(&mut self, workspace: PathBuf) {
        self.workspace = workspace;
        self.expanded.clear();
        self.tree_cursor = 0;
        self.files.clear();
        self.editor_focus = EditorFocus::Page;
        self.search_hits.clear();
        self.refresh_tree();
        self.refresh_git();
    }

    /// Rebuild the legacy explicit-workspace inventory from local filesystem
    /// state. The direct FCC shell does not render this inventory.
    /// Bounded: hidden entries and build-artifact directories are skipped,
    /// depth is capped, and the flat list stops at [`MAX_TREE_ENTRIES`].
    pub fn refresh_tree(&mut self) {
        let mut tree = Vec::new();
        let root = self.workspace.clone();
        let expanded = self.expanded.clone();
        Self::walk_tree(&mut tree, &expanded, &root, 0);
        self.tree = tree;
        self.tree_cursor = self.tree_cursor.min(self.tree.len().saturating_sub(1));
    }

    fn walk_tree(
        tree: &mut Vec<TreeEntry>,
        expanded: &std::collections::HashSet<PathBuf>,
        dir: &PathBuf,
        depth: usize,
    ) {
        let Ok(entries) = std::fs::read_dir(dir) else {
            return;
        };
        let mut children: Vec<_> = entries.filter_map(Result::ok).collect();
        children.sort_by_key(|entry| {
            let is_dir = entry.file_type().map(|kind| kind.is_dir()).unwrap_or(false);
            (!is_dir, entry.file_name().to_string_lossy().to_lowercase())
        });
        for entry in children {
            if tree.len() >= MAX_TREE_ENTRIES {
                return;
            }
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') {
                continue;
            }
            let path = entry.path();
            let is_dir = entry.file_type().map(|kind| kind.is_dir()).unwrap_or(false);
            if is_dir && depth < MAX_TREE_DEPTH && SKIP_DIRS.contains(&name.as_str()) {
                continue;
            }
            tree.push(TreeEntry {
                path: path.clone(),
                name,
                depth,
                is_dir,
            });
            if is_dir && depth < MAX_TREE_DEPTH && expanded.contains(&path) {
                Self::walk_tree(tree, expanded, &path, depth + 1);
            }
        }
    }

    fn toggle_tree_dir(&mut self, index: usize) {
        let Some(entry) = self.tree.get(index).cloned() else {
            return;
        };
        if !entry.is_dir {
            return;
        }
        if self.expanded.contains(&entry.path) {
            self.expanded.remove(&entry.path);
            self.expanded.retain(|path| !path.starts_with(&entry.path));
        } else {
            self.expanded.insert(entry.path);
        }
        self.refresh_tree();
    }

    /// Activate the tree row under the cursor: expand/collapse directories,
    /// open files as explicit read-only previews.
    pub fn activate_tree(&mut self, index: usize) {
        let Some(entry) = self.tree.get(index).cloned() else {
            return;
        };
        self.tree_cursor = index;
        if entry.is_dir {
            self.toggle_tree_dir(index);
        } else {
            self.open_file(entry.path, None);
        }
    }

    /// Open a workspace file as an editor tab (read-only viewer) and focus
    /// it, optionally jumping to a 1-based line. Files beyond
    /// [`MAX_FILE_BYTES`] or [`MAX_FILE_LINES`] open truncated with a marker.
    pub fn open_file(&mut self, path: PathBuf, line: Option<usize>) {
        self.focus = Focus::Editor;
        if let Some(position) = self.files.iter().position(|file| file.path == path) {
            self.editor_focus = EditorFocus::File(position);
            if let Some(line) = line {
                self.jump_to_line(position, line);
            }
            return;
        }
        let bytes = std::fs::read(&path).unwrap_or_default();
        let mut truncated = bytes.len() as u64 > MAX_FILE_BYTES;
        let text = String::from_utf8_lossy(&bytes);
        let mut lines: Vec<String> = text
            .lines()
            .take(MAX_FILE_LINES + 1)
            .map(str::to_owned)
            .collect();
        if lines.len() > MAX_FILE_LINES {
            lines.truncate(MAX_FILE_LINES);
            truncated = true;
        }
        self.files.push(OpenFile {
            path,
            lines,
            scroll: 0,
            truncated,
        });
        let position = self.files.len() - 1;
        self.editor_focus = EditorFocus::File(position);
        if let Some(line) = line {
            self.jump_to_line(position, line);
        }
    }

    pub fn jump_to_line(&mut self, position: usize, line: usize) {
        let Some(file) = self.files.get_mut(position) else {
            return;
        };
        let target = line
            .saturating_sub(1)
            .min(file.lines.len().saturating_sub(1));
        file.scroll = target;
    }

    pub fn close_file(&mut self, position: usize) {
        if position >= self.files.len() {
            return;
        }
        self.files.remove(position);
        self.editor_focus = match self.editor_focus {
            EditorFocus::File(active) if active == position => EditorFocus::Page,
            EditorFocus::File(active) if active > position => EditorFocus::File(active - 1),
            focused => focused,
        };
    }

    pub fn close_active_file(&mut self) {
        if let EditorFocus::File(position) = self.editor_focus {
            self.close_file(position);
        }
    }

    pub fn active_file(&self) -> Option<(usize, &OpenFile)> {
        match self.editor_focus {
            EditorFocus::File(position) => self.files.get(position).map(|file| (position, file)),
            EditorFocus::Page => None,
        }
    }

    #[allow(dead_code)]
    pub fn active_file_title(&self) -> Option<String> {
        self.active_file().map(|(_, file)| file.title())
    }

    /// Move the tree cursor to the open file and expand its parents.
    pub fn reveal_in_explorer(&mut self) {
        let Some((_, file)) = self.active_file() else {
            return;
        };
        let path = file.path.clone();
        let mut ancestor = path.parent();
        while let Some(dir) = ancestor {
            if dir == self.workspace {
                break;
            }
            self.expanded.insert(dir.to_path_buf());
            ancestor = dir.parent();
        }
        self.activity = Activity::Explorer;
        self.focus = Focus::Sidebar;
        self.refresh_tree();
        if let Some(position) = self.tree.iter().position(|entry| entry.path == path) {
            self.tree_cursor = position;
        }
    }

    /// Run a bounded case-insensitive substring search over workspace files.
    pub fn run_search(&mut self, query: &str) {
        self.search_query = query.to_string();
        self.search_hits.clear();
        let needle = query.to_ascii_lowercase();
        if needle.is_empty() {
            return;
        }
        let mut scanned = 0usize;
        let mut stack = vec![self.workspace.clone()];
        while let Some(dir) = stack.pop() {
            let Ok(entries) = std::fs::read_dir(&dir) else {
                continue;
            };
            for entry in entries.filter_map(Result::ok) {
                let name = entry.file_name().to_string_lossy().into_owned();
                if name.starts_with('.') {
                    continue;
                }
                let path = entry.path();
                let is_dir = entry.file_type().map(|kind| kind.is_dir()).unwrap_or(false);
                if is_dir {
                    if SKIP_DIRS.contains(&name.as_str()) {
                        continue;
                    }
                    stack.push(path);
                    continue;
                }
                scanned += 1;
                if scanned > MAX_SEARCH_FILES || self.search_hits.len() >= MAX_SEARCH_HITS {
                    return;
                }
                if entry
                    .metadata()
                    .map(|meta| meta.len() > MAX_FILE_BYTES)
                    .unwrap_or(true)
                {
                    continue;
                }
                let Ok(bytes) = std::fs::read(&path) else {
                    continue;
                };
                if bytes.contains(&0) {
                    continue;
                }
                let text = String::from_utf8_lossy(&bytes);
                for (number, line) in text.lines().enumerate() {
                    if line.to_ascii_lowercase().contains(&needle) {
                        self.search_hits.push(SearchHit {
                            path: path.clone(),
                            line: number + 1,
                            text: line.chars().take(120).collect(),
                        });
                        if self.search_hits.len() >= MAX_SEARCH_HITS {
                            return;
                        }
                    }
                }
            }
        }
    }

    /// Refresh retained workspace git metadata. Failures stay as local state
    /// (offline or non-checkout workspaces remain usable).
    pub fn refresh_git(&mut self) {
        self.git_error = None;
        let status = std::process::Command::new("git")
            .args(["status", "--porcelain=v1", "--untracked-files=normal"])
            .current_dir(&self.workspace)
            .output();
        let Ok(status) = status else {
            self.git_error = Some("git is not available".to_string());
            return;
        };
        if !status.status.success() {
            self.git_error = Some("not a git checkout".to_string());
            self.git_branch.clear();
            self.git_changes.clear();
            return;
        }
        let branch = std::process::Command::new("git")
            .args(["branch", "--show-current"])
            .current_dir(&self.workspace)
            .output();
        self.git_branch = branch
            .ok()
            .filter(|output| output.status.success())
            .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_owned())
            .filter(|name| !name.is_empty())
            .unwrap_or_else(|| "(detached)".to_string());
        let mut changes = Vec::new();
        for line in String::from_utf8_lossy(&status.stdout).lines() {
            if changes.len() >= MAX_GIT_CHANGES {
                break;
            }
            let bytes = line.as_bytes();
            let staged = bytes.first().copied().unwrap_or(b' ') as char;
            let unstaged = bytes.get(1).copied().unwrap_or(b' ') as char;
            let path = line.get(3..).unwrap_or_default();
            let path = path.rsplit(" -> ").next().unwrap_or(path).to_owned();
            if path.is_empty() {
                continue;
            }
            changes.push(GitChange {
                path,
                staged,
                unstaged,
            });
        }
        self.git_changes = changes;
    }

    pub fn set_activity(&mut self, activity: Activity) {
        self.activity = activity;
        self.sidebar_cursor = 0;
        if let Some(page) = activity.page() {
            self.page = page;
            self.editor_focus = EditorFocus::Page;
        }
        if activity.page().is_some() {
            self.focus = Focus::Editor;
        }
        if activity == Activity::SourceControl {
            self.refresh_git();
        }
    }

    pub fn problem_counts(&self) -> (usize, usize) {
        let errors = self.models.failed_providers.len();
        let warnings = self
            .config
            .provider_status
            .iter()
            .filter(|provider| {
                matches!(
                    provider.status.as_str(),
                    "missing_key" | "missing_config" | "missing_url" | "unknown"
                )
            })
            .count();
        (errors, warnings)
    }

    pub fn status_model_short(&self) -> String {
        let model = self.status_model();
        match model.rsplit_once('/') {
            Some((_, leaf)) => leaf.to_string(),
            None => model,
        }
    }

    pub fn refresh_all(&mut self) -> bool {
        if self.refresh_task.is_some() {
            self.set_notice("Another operation is still in progress".to_string());
            return false;
        }
        self.next_refresh_notice = None;
        self.apply_snapshot(fetch_snapshot(&self.api))
    }

    fn apply_snapshot(&mut self, snapshot: SnapshotResults) -> bool {
        let (
            config_result,
            status_result,
            models_result,
            custom_result,
            local_result,
            usage_result,
        ) = snapshot;
        let mut errors = Vec::new();
        match config_result {
            Ok(value) => self.config = value,
            Err(error) => errors.push(format!("config: {error}")),
        }
        match status_result {
            Ok(value) => self.status = value,
            Err(error) => errors.push(format!("status: {error}")),
        }
        match models_result {
            Ok(value) => self.models = value,
            Err(error) => errors.push(format!("models: {error}")),
        }
        match custom_result {
            Ok(value) => self.custom_providers = value.providers,
            Err(error) => errors.push(format!("custom providers: {error}")),
        }
        match local_result {
            Ok(value) => self.local_status = value.providers,
            Err(error) => errors.push(format!("local providers: {error}")),
        }
        match usage_result {
            Ok(value) => self.usage = value,
            Err(error) => errors.push(format!("usage: {error}")),
        }
        if errors.is_empty() {
            self.error = None;
        } else {
            self.set_error(format!("Refresh incomplete — {}", errors.join(" · ")));
        }
        self.clamp_selections();
        errors.is_empty()
    }

    /// Start a full snapshot refresh without blocking terminal redraws or
    /// input. Only one refresh is kept in flight so repeated `R` presses are
    /// deterministic and cannot apply stale responses out of order.
    pub fn begin_refresh_all(&mut self) {
        self.begin_refresh_all_with_notice(None);
    }

    fn begin_refresh_all_with_notice(&mut self, success_notice: Option<String>) {
        if self.refresh_task.is_some() {
            self.set_notice("Refresh already in progress".to_string());
            return;
        }
        let api = self.api.clone();
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let _ = sender.send(fetch_snapshot(&api));
        });
        self.next_refresh_notice = success_notice;
        self.refresh_task = Some(RefreshTask::All(receiver));
        self.set_notice("Refreshing FCC snapshot…".to_string());
    }

    fn begin_model_refresh(&mut self) {
        if self.refresh_task.is_some() {
            self.set_notice("Refresh already in progress".to_string());
            return;
        }
        let api = self.api.clone();
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let _ = sender.send(api.refresh_models());
        });
        self.refresh_task = Some(RefreshTask::Models(receiver));
        self.set_notice("Refreshing model catalog…".to_string());
    }

    /// Apply completed background work between frames. A pending task is
    /// intentionally non-blocking; the next 200ms event-poll tick redraws the
    /// same screen and lets the user continue navigating.
    pub fn poll_background(&mut self) {
        let Some(task) = self.refresh_task.take() else {
            return;
        };
        match task {
            RefreshTask::All(receiver) => match receiver.try_recv() {
                Ok(snapshot) => {
                    if self.apply_snapshot(snapshot) {
                        let notice = self
                            .next_refresh_notice
                            .take()
                            .unwrap_or_else(|| "FCC snapshot refreshed".to_string());
                        self.set_notice(notice);
                    }
                }
                Err(TryRecvError::Empty) => self.refresh_task = Some(RefreshTask::All(receiver)),
                Err(TryRecvError::Disconnected) => {
                    self.next_refresh_notice = None;
                    self.set_error("Refresh worker stopped before returning a snapshot".to_string())
                }
            },
            RefreshTask::Models(receiver) => match receiver.try_recv() {
                Ok(Ok(models)) => {
                    let failed_providers = models.failed_providers.clone();
                    self.models = models;
                    self.clamp_selections();
                    if failed_providers.is_empty() {
                        self.set_notice("Model catalog refreshed".to_string());
                    } else {
                        self.set_error(format!(
                            "Model refresh incomplete — provider requests failed: {}",
                            failed_providers.join(", ")
                        ));
                    }
                }
                Ok(Err(error)) => self.set_error(error.to_string()),
                Err(TryRecvError::Empty) => self.refresh_task = Some(RefreshTask::Models(receiver)),
                Err(TryRecvError::Disconnected) => {
                    self.set_error("Model refresh worker stopped before returning data".to_string())
                }
            },
            RefreshTask::ModelPolicy(receiver, success_notice) => match receiver.try_recv() {
                Ok(Ok(result)) if result.valid && result.applied => {
                    self.selected_models.clear();
                    self.begin_refresh_all_with_notice(Some(success_notice));
                }
                Ok(Ok(result)) => {
                    self.set_error(if result.errors.is_empty() {
                        "Model catalog update was rejected".to_string()
                    } else {
                        result.errors.join("\n")
                    });
                }
                Ok(Err(error)) => self.set_error(error.to_string()),
                Err(TryRecvError::Empty) => {
                    self.refresh_task = Some(RefreshTask::ModelPolicy(receiver, success_notice))
                }
                Err(TryRecvError::Disconnected) => self.set_error(
                    "Model catalog worker stopped before returning a result".to_string(),
                ),
            },
        }
    }

    pub fn handle_event(&mut self, event: Event) -> Result<Option<ExternalAction>> {
        match event {
            Event::Key(key) if key.kind == KeyEventKind::Press => self.handle_key(key),
            Event::Mouse(mouse) => self.handle_mouse(mouse),
            _ => Ok(None),
        }
    }

    fn handle_key(&mut self, key: KeyEvent) -> Result<Option<ExternalAction>> {
        let palette_open = matches!(self.modal, Some(Modal::Palette { .. }));
        if key.modifiers.contains(KeyModifiers::CONTROL)
            && matches!(key.code, KeyCode::Char('k') | KeyCode::Char('K'))
        {
            self.open_palette();
            return Ok(None);
        }
        if key.modifiers.contains(KeyModifiers::CONTROL)
            && matches!(key.code, KeyCode::Char('p') | KeyCode::Char('P'))
            && !palette_open
        {
            self.open_palette();
            return Ok(None);
        }
        if self.modal.is_some() {
            return self.handle_modal_key(key);
        }

        if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('c') {
            self.should_quit = true;
            return Ok(None);
        }
        if key.modifiers.contains(KeyModifiers::CONTROL) {
            match key.code {
                KeyCode::Char('b') | KeyCode::Char('B') => {
                    self.sidebar_open = !self.sidebar_open;
                    if !self.sidebar_open {
                        // Never leave keyboard focus on a hidden navigation
                        // pane: arrows must not change pages invisibly.
                        self.focus = Focus::Editor;
                    }
                    return Ok(None);
                }
                KeyCode::Char('j') | KeyCode::Char('J') => {
                    self.panel_open = !self.panel_open;
                    return Ok(None);
                }
                KeyCode::Char('0') => {
                    self.focus = Focus::Sidebar;
                    self.sidebar_cursor = self.page.index();
                    return Ok(None);
                }
                KeyCode::Char('1') => {
                    self.focus = Focus::Editor;
                    return Ok(None);
                }
                _ => {}
            }
        }
        match key.code {
            KeyCode::Char('q') => self.should_quit = true,
            KeyCode::Tab | KeyCode::BackTab => self.toggle_focus(),
            KeyCode::Up | KeyCode::Char('k') => self.move_focused(-1),
            KeyCode::Down | KeyCode::Char('j') => self.move_focused(1),
            KeyCode::PageUp => self.move_focused(-12),
            KeyCode::PageDown => self.move_focused(12),
            KeyCode::Home => self.move_focused_to_edge(false),
            KeyCode::End => self.move_focused_to_edge(true),
            KeyCode::Char('g') if self.editor_file_active() => self.scroll_top(),
            KeyCode::Char('G') if self.editor_file_active() => self.scroll_bottom(),
            KeyCode::Char('r') => self.refresh_current(),
            KeyCode::Char('c') => return Ok(Some(ExternalAction::LaunchClaude { danger: false })),
            KeyCode::Enter => self.default_action()?,
            KeyCode::Char('x') if self.editor_file_active() => self.close_active_file(),
            KeyCode::Char('e') if self.editor_file_active() => {
                return self.launch_external_editor();
            }
            KeyCode::Char(' ') if self.model_page_focused() => self.toggle_selected_model(),
            KeyCode::Char('p') if self.model_page_focused() => self.open_model_provider_picker(),
            KeyCode::Char('v') if self.model_page_focused() => self.toggle_model_catalog(),
            KeyCode::Char('n') if self.model_page_focused() => self.cycle_model_price(),
            KeyCode::Char('t') if self.model_page_focused() => self.toggle_selected_models(),
            KeyCode::Char('X') if self.model_page_focused() => self.disable_all_models(),
            KeyCode::Char('e') => self.edit_action()?,
            KeyCode::Char('t') if self.page == Page::Providers => self.test_selected_provider(),
            KeyCode::Char('n') if self.page == Page::Providers => self.new_custom_provider(),
            KeyCode::Char('x') if self.page == Page::Providers => self.delete_custom_provider(),
            KeyCode::Char('l') if self.page == Page::Providers => self.login_provider("browser"),
            KeyCode::Char('L') if self.page == Page::Providers => self.login_provider("device"),
            KeyCode::Char('D') if self.page == Page::Providers => self.disconnect_provider(),
            KeyCode::Char('/') if self.editor_file_active() => {
                self.open_find_in_file();
            }
            KeyCode::Char('/') if self.model_page_focused() => {
                self.modal = Some(Modal::SearchModels {
                    input: TextInput::new(self.model_query.clone(), false, false),
                });
            }
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
            KeyCode::Char('!') => return Ok(Some(ExternalAction::LaunchClaude { danger: true })),
            _ => {}
        }
        Ok(None)
    }

    fn handle_mouse(&mut self, mouse: MouseEvent) -> Result<Option<ExternalAction>> {
        self.mouse = Some((mouse.column, mouse.row));
        // A modal owns the input surface. Its list rows get modal-specific
        // hitboxes; clicks that miss those rows are ignored so the page
        // underneath can never change accidentally.
        if self.modal.is_some() {
            let action = self
                .hitboxes
                .iter()
                .rev()
                .find(|hitbox| contains(hitbox.rect, mouse.column, mouse.row))
                .map(|hitbox| hitbox.action.clone());
            return match action {
                Some(action @ (UiAction::ModalSelect(_) | UiAction::ModalActivate(_))) => {
                    self.invoke_ui_action(action)
                }
                _ => Ok(None),
            };
        }
        match mouse.kind {
            MouseEventKind::ScrollUp => {
                if self.sidebar_open && contains(self.geometry.sidebar, mouse.column, mouse.row) {
                    self.focus = Focus::Sidebar;
                } else {
                    self.focus = Focus::Editor;
                }
                self.move_focused(-2);
                return Ok(None);
            }
            MouseEventKind::ScrollDown => {
                if self.sidebar_open && contains(self.geometry.sidebar, mouse.column, mouse.row) {
                    self.focus = Focus::Sidebar;
                } else {
                    self.focus = Focus::Editor;
                }
                self.move_focused(2);
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
            let action = match action {
                UiAction::SelectModel(index)
                    if mouse
                        .modifiers
                        .intersects(KeyModifiers::SHIFT | KeyModifiers::CONTROL) =>
                {
                    UiAction::ToggleModelSelection(index)
                }
                other => other,
            };
            return self.invoke_ui_action(action);
        }
        Ok(None)
    }

    fn invoke_ui_action(&mut self, action: UiAction) -> Result<Option<ExternalAction>> {
        match action {
            UiAction::Navigate(page) => {
                self.page = page;
                self.sidebar_cursor = page.index();
                self.editor_focus = EditorFocus::Page;
                self.focus = Focus::Editor;
                self.content_scroll = 0;
            }
            UiAction::SelectProvider(index) => {
                self.provider_selected = index;
                self.focus = Focus::Editor;
                self.editor_focus = EditorFocus::Page;
            }
            UiAction::SelectModel(index) => {
                self.model_selected = index;
                self.focus = Focus::Editor;
                self.editor_focus = EditorFocus::Page;
            }
            UiAction::ToggleModelSelection(index) => {
                self.toggle_model_selection(index);
                self.focus = Focus::Editor;
                self.editor_focus = EditorFocus::Page;
            }
            UiAction::CycleModelProvider => self.cycle_model_provider(),
            UiAction::CycleModelPrice => self.cycle_model_price(),
            UiAction::ToggleModelCatalog => self.toggle_model_catalog(),
            UiAction::ToggleSelectedModels => self.toggle_selected_models(),
            UiAction::DisableAllModels => self.disable_all_models(),
            UiAction::SelectRouting(index) => {
                self.routing_selected = index;
                self.focus = Focus::Editor;
                self.editor_focus = EditorFocus::Page;
            }
            UiAction::SelectLocal(index) => {
                self.local_selected = index;
                self.focus = Focus::Editor;
                self.editor_focus = EditorFocus::Page;
            }
            UiAction::SelectSetting(index) => {
                self.setting_selected = index;
                self.focus = Focus::Editor;
                self.editor_focus = EditorFocus::Page;
            }
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
            UiAction::ChooseModelProvider => self.open_model_provider_picker(),
            UiAction::RunDiagnostic => self.run_diagnostic(),
            UiAction::LaunchClaude(danger) => {
                return Ok(Some(ExternalAction::LaunchClaude { danger }));
            }
            UiAction::OpenPalette => self.open_palette(),
            UiAction::ModalSelect(index) => self.select_modal_index(index),
            UiAction::ModalActivate(index) => return self.activate_modal_index(index),
            UiAction::Quit => self.should_quit = true,
            UiAction::Activity(activity) => self.set_activity(activity),
            UiAction::ToggleSidebar => self.sidebar_open = !self.sidebar_open,
            UiAction::TogglePanel => self.panel_open = !self.panel_open,
            UiAction::FocusSidebar => {
                self.focus = Focus::Sidebar;
                self.sidebar_cursor = self.page.index();
            }
            UiAction::FocusEditor => self.focus = Focus::Editor,
            UiAction::ActivateTree(index) => {
                self.focus = Focus::Sidebar;
                self.activate_tree(index);
            }
            UiAction::ActivateTab(index) => self.activate_tab(index),
            UiAction::CloseFile(index) => self.close_file(index),
            UiAction::RevealInExplorer => self.reveal_in_explorer(),
            UiAction::RefreshGit => self.refresh_git(),
            UiAction::SearchFiles => {
                self.modal = Some(Modal::SearchFiles {
                    input: TextInput::new(self.search_query.clone(), false, false),
                });
            }
            UiAction::FindInFile => self.open_find_in_file(),
            UiAction::CloseActiveFile => self.close_active_file(),
            UiAction::OpenSearchHit(index) => self.open_search_hit(index),
            UiAction::OpenGitChange(index) => self.open_git_change(index),
        }
        Ok(None)
    }

    fn activate_tab(&mut self, index: usize) {
        // FCC pages are the main editor surface, not a second tab. File tabs
        // are optional and only appear after a file is opened.
        if index < self.files.len() {
            self.editor_focus = EditorFocus::File(index);
        } else {
            self.editor_focus = EditorFocus::Page;
        }
    }

    #[allow(dead_code)]
    pub fn tab_count(&self) -> usize {
        self.files.len()
    }

    fn open_find_in_file(&mut self) {
        if !matches!(self.editor_focus, EditorFocus::File(_)) {
            return;
        }
        self.modal = Some(Modal::FindInFile {
            input: TextInput::new(String::new(), false, false),
        });
    }

    fn find_in_file(&mut self, needle: &str) {
        self.find_needle = needle.to_string();
        let EditorFocus::File(position) = self.editor_focus else {
            return;
        };
        let Some(file) = self.files.get_mut(position) else {
            return;
        };
        if needle.is_empty() || file.lines.is_empty() {
            return;
        }
        let needle = needle.to_ascii_lowercase();
        let start = (file.scroll + 1) % file.lines.len();
        for offset in 0..file.lines.len() {
            let index = (start + offset) % file.lines.len();
            if file.lines[index].to_ascii_lowercase().contains(&needle) {
                file.scroll = index;
                return;
            }
        }
    }

    pub fn editor_file_active(&self) -> bool {
        self.focus == Focus::Editor && matches!(self.editor_focus, EditorFocus::File(_))
    }

    /// Model-page shortcuts belong to the page itself, not to the surrounding
    /// navigation chrome. This prevents Space or a filter key from changing
    /// model state while the sidebar or an opened file owns focus.
    pub fn model_page_focused(&self) -> bool {
        self.page == Page::Models
            && self.focus == Focus::Editor
            && matches!(self.editor_focus, EditorFocus::Page)
    }

    /// Route vertical motion to the focused pane: page navigation moves across
    /// the finite FCC page list, the file viewer scrolls by line, and page
    /// controls keep their bounded list behavior.
    pub fn move_focused(&mut self, delta: isize) {
        if self.focus == Focus::Sidebar {
            let len = Page::ALL.len() as isize;
            if len > 0 {
                let next = (self.sidebar_cursor as isize + delta).clamp(0, len - 1) as usize;
                self.sidebar_cursor = next;
                self.page = Page::ALL[next];
                self.editor_focus = EditorFocus::Page;
                self.content_scroll = 0;
            }
            return;
        }
        if matches!(self.editor_focus, EditorFocus::File(_)) {
            self.scroll_viewer(delta);
            return;
        }
        if matches!(self.page, Page::Usage | Page::Diagnostics) {
            self.scroll_content(delta);
            return;
        }
        self.move_selection(delta);
    }

    /// Move the focused finite control to its first or last reachable item.
    /// Edge keys must follow the same focus ownership as arrow/page motion;
    /// otherwise Home/End on the sidebar can unexpectedly scroll the page
    /// behind it.
    pub fn move_focused_to_edge(&mut self, end: bool) {
        if self.focus == Focus::Sidebar {
            let index = if end {
                Page::ALL.len().saturating_sub(1)
            } else {
                0
            };
            self.sidebar_cursor = index;
            self.page = Page::ALL[index];
            self.editor_focus = EditorFocus::Page;
            self.content_scroll = 0;
            return;
        }
        if matches!(self.editor_focus, EditorFocus::File(_)) {
            if end {
                self.scroll_bottom();
            } else {
                self.scroll_top();
            }
            return;
        }
        if matches!(self.page, Page::Usage | Page::Diagnostics) {
            if end {
                self.scroll_content_to_end();
            } else {
                self.scroll_content_to_start();
            }
            return;
        }
        let index = if end {
            self.page_selection_len().saturating_sub(1)
        } else {
            0
        };
        match self.page {
            Page::Providers => self.provider_selected = index,
            Page::Models => self.model_selected = index,
            Page::Routing => self.routing_selected = index,
            Page::Local => self.local_selected = index,
            Page::Settings => self.setting_selected = index,
            _ => {}
        }
    }

    fn page_selection_len(&self) -> usize {
        match self.page {
            Page::Providers => self.config.provider_status.len(),
            Page::Models => self.filtered_models().len(),
            Page::Routing => self.routing_field_indices().len(),
            Page::Local => self.local_field_indices().len(),
            Page::Settings => self.settings_field_indices().len(),
            _ => 0,
        }
    }

    /// Scroll the current page's long-form output or explicit file viewer.
    /// Page output is bounded to the number of rendered lines; it never grows
    /// an unobservable cursor past the document.
    pub fn scroll_content(&mut self, delta: isize) {
        if matches!(self.editor_focus, EditorFocus::File(_)) {
            self.scroll_viewer(delta);
            return;
        }
        if !matches!(self.page, Page::Usage | Page::Diagnostics) {
            return;
        }
        let total = self.content_line_count();
        let viewport = self.content_viewport_height();
        let max = total.saturating_sub(viewport);
        self.content_scroll =
            (self.content_scroll as isize + delta).clamp(0, max as isize) as usize;
    }

    pub fn scroll_content_to_start(&mut self) {
        if self.editor_file_active() {
            self.scroll_top();
        } else if matches!(self.page, Page::Usage | Page::Diagnostics) {
            self.content_scroll = 0;
        }
    }

    pub fn scroll_content_to_end(&mut self) {
        if self.editor_file_active() {
            self.scroll_bottom();
        } else if matches!(self.page, Page::Usage | Page::Diagnostics) {
            self.content_scroll = self
                .content_line_count()
                .saturating_sub(self.content_viewport_height());
        }
    }

    pub fn content_line_count(&self) -> usize {
        let body = match self.page {
            Page::Usage => pretty(&self.usage),
            Page::Diagnostics if self.diagnostic.is_null() => {
                "Run a synthetic route diagnostic. No prompt content is sent to a provider."
                    .to_string()
            }
            Page::Diagnostics => pretty(&self.diagnostic),
            _ => String::new(),
        };
        rendered_line_count(&body, self.content_viewport_width())
    }

    fn content_viewport_width(&self) -> u16 {
        self.geometry.editor.width.saturating_sub(2).max(1)
    }

    fn content_viewport_height(&self) -> usize {
        // The page surface reserves three rows for the action bar and the
        // bordered output block consumes two more rows.
        self.geometry.editor.height.saturating_sub(5).max(1) as usize
    }

    pub fn scroll_viewer(&mut self, delta: isize) {
        let EditorFocus::File(position) = self.editor_focus else {
            return;
        };
        let Some(file) = self.files.get_mut(position) else {
            return;
        };
        if file.lines.is_empty() {
            return;
        }
        let max = file.lines.len() - 1;
        let next = (file.scroll as isize + delta).clamp(0, max as isize);
        file.scroll = next as usize;
    }

    pub fn scroll_top(&mut self) {
        let EditorFocus::File(position) = self.editor_focus else {
            return;
        };
        if let Some(file) = self.files.get_mut(position) {
            file.scroll = 0;
        }
    }

    pub fn scroll_bottom(&mut self) {
        let EditorFocus::File(position) = self.editor_focus else {
            return;
        };
        if let Some(file) = self.files.get_mut(position) {
            file.scroll = file.lines.len().saturating_sub(1);
        }
    }

    /// Suspend the TUI and open the active file in `$EDITOR` (or `vi`).
    pub fn launch_external_editor(&self) -> Result<Option<ExternalAction>> {
        let Some((_, file)) = self.active_file() else {
            return Ok(None);
        };
        Ok(Some(ExternalAction::EditExternal {
            path: file.path.clone(),
        }))
    }

    pub fn open_search_hit(&mut self, index: usize) {
        let Some(hit) = self.search_hits.get(index).cloned() else {
            return;
        };
        self.open_file(hit.path, Some(hit.line));
    }

    pub fn open_git_change(&mut self, index: usize) {
        let Some(change) = self.git_changes.get(index).cloned() else {
            return;
        };
        let path = self.workspace.join(&change.path);
        if !path.is_file() {
            self.notice = Some(format!("{} is not on disk", change.path));
            return;
        }
        self.open_file(path, None);
    }

    fn default_action(&mut self) -> Result<()> {
        if self.focus == Focus::Sidebar {
            if let Some(page) = Page::ALL.get(self.sidebar_cursor).copied() {
                self.page = page;
                self.editor_focus = EditorFocus::Page;
                self.focus = Focus::Editor;
            }
            return Ok(());
        }
        if matches!(self.editor_focus, EditorFocus::File(_)) {
            return Ok(());
        }
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
            Page::Models => self.begin_model_refresh(),
            _ => self.begin_refresh_all(),
        }
    }

    fn toggle_focus(&mut self) {
        self.focus = match self.focus {
            Focus::Sidebar => Focus::Editor,
            Focus::Editor => {
                self.sidebar_cursor = self.page.index();
                Focus::Sidebar
            }
        };
    }

    fn move_selection(&mut self, delta: isize) {
        let len = match self.page {
            Page::Providers => self.config.provider_status.len(),
            Page::Models => self.filtered_models().len(),
            Page::Routing => self.routing_field_indices().len(),
            Page::Local => self.local_field_indices().len(),
            Page::Settings => self.settings_field_indices().len(),
            _ => return,
        };
        let selection = match self.page {
            Page::Providers => &mut self.provider_selected,
            Page::Models => &mut self.model_selected,
            Page::Routing => &mut self.routing_selected,
            Page::Local => &mut self.local_selected,
            Page::Settings => &mut self.setting_selected,
            _ => return,
        };
        if len == 0 {
            *selection = 0;
            return;
        }
        // Lists are finite controls. Stop at the first/last row so a wheel or
        // repeated arrow press never turns a bounded list into an endless
        // loop that hides the actual edge of the inventory.
        *selection =
            (*selection as isize + delta).clamp(0, len.saturating_sub(1) as isize) as usize;
    }

    fn clamp_selections(&mut self) {
        self.provider_selected = clamp(self.provider_selected, self.config.provider_status.len());
        self.normalize_model_filters();
        let inventory = self.model_inventory();
        self.selected_models
            .retain(|model| inventory.iter().any(|candidate| candidate == model));
        self.model_selected = clamp(self.model_selected, self.filtered_models().len());
        self.routing_selected = clamp(self.routing_selected, self.routing_field_indices().len());
        self.local_selected = clamp(self.local_selected, self.local_field_indices().len());
        self.setting_selected = clamp(self.setting_selected, self.settings_field_indices().len());
    }

    pub fn filtered_models(&self) -> Vec<String> {
        let query = self.model_query.trim().to_ascii_lowercase();
        let registered = self
            .model_provider_options()
            .into_iter()
            .skip(1)
            .map(|(_, value)| value.to_ascii_lowercase())
            .collect::<HashSet<_>>();
        let mut models = self.model_candidates();
        models.retain(|model| {
            let provider = Self::model_provider_id(model).to_ascii_lowercase();
            // If the server did not return provider status, keep the cached
            // rows usable. When status exists, the catalog view is limited to
            // providers the user actually registered.
            let registered_or_unreported =
                registered.is_empty() || registered.contains(&provider) || !self.model_show_catalog;
            let provider_matches = self.model_provider_filter == "all"
                || provider.eq_ignore_ascii_case(&self.model_provider_filter);
            let price_matches = self.model_price_filter != ModelPriceFilter::FreeOnly
                || self.model_price_state(model) == ModelPriceState::Free;
            let search_matches = if query.is_empty() {
                true
            } else {
                let label = self.model_label(model);
                model.to_ascii_lowercase().contains(&query)
                    || label.to_ascii_lowercase().contains(&query)
            };
            registered_or_unreported && provider_matches && price_matches && search_matches
        });
        models.sort_by(|left, right| {
            let left_label = self.model_label(left);
            let right_label = self.model_label(right);
            left_label
                .to_ascii_lowercase()
                .cmp(&right_label.to_ascii_lowercase())
                .then_with(|| left.to_ascii_lowercase().cmp(&right.to_ascii_lowercase()))
        });
        models
    }

    fn model_candidates(&self) -> Vec<String> {
        let source = if self.model_show_catalog {
            self.model_inventory()
        } else {
            self.models.models.clone()
        };
        let mut models = Vec::with_capacity(source.len());
        for model in source {
            if !models.iter().any(|candidate| candidate == &model) {
                models.push(model);
            }
        }
        models
    }

    /// Registered providers are the server's configured/connected inventory
    /// plus enabled custom providers. If an older server omits all provider
    /// status records, active model prefixes are retained as a compatibility
    /// fallback; a populated status response is authoritative and prevents
    /// unknown catalog prefixes from appearing as selectable providers.
    pub fn model_provider_options(&self) -> Vec<(String, String)> {
        let mut providers: HashMap<String, (String, String, String)> = HashMap::new();
        let provider_statuses = self
            .config
            .provider_status
            .iter()
            .chain(self.models.provider_status.iter());
        let mut has_provider_status_records = false;
        for status in provider_statuses {
            has_provider_status_records |= !status.provider_id.is_empty();
            if !Self::registered_provider_status(&status.status) || status.provider_id.is_empty() {
                continue;
            }
            let key = status.provider_id.to_ascii_lowercase();
            let label = if status.display_name.is_empty() {
                status.provider_id.clone()
            } else {
                status.display_name.clone()
            };
            let state = if status.label.is_empty() {
                status.status.clone()
            } else {
                status.label.clone()
            };
            providers.insert(key, (status.provider_id.clone(), label, state));
        }
        for provider in &self.custom_providers {
            if provider.provider_id.is_empty() || !provider.enabled {
                continue;
            }
            providers
                .entry(provider.provider_id.to_ascii_lowercase())
                .or_insert_with(|| {
                    (
                        provider.provider_id.clone(),
                        if provider.display_name.is_empty() {
                            provider.provider_id.clone()
                        } else {
                            provider.display_name.clone()
                        },
                        "Enabled".to_string(),
                    )
                });
        }
        if !has_provider_status_records {
            for model in &self.models.models {
                let provider_id = Self::model_provider_id(model).to_string();
                providers
                    .entry(provider_id.to_ascii_lowercase())
                    .or_insert_with(|| (provider_id.clone(), provider_id, "Active".to_string()));
            }
        }

        let mut options = vec![("All registered".to_string(), "all".to_string())];
        let mut values = providers.into_values().collect::<Vec<_>>();
        values.sort_by(|left, right| {
            left.1
                .to_ascii_lowercase()
                .cmp(&right.1.to_ascii_lowercase())
        });
        for (provider_id, label, state) in values {
            let has_model = self
                .model_inventory()
                .iter()
                .any(|model| Self::model_provider_id(model).eq_ignore_ascii_case(&provider_id));
            let display = if has_model {
                label
            } else {
                format!("{label} ({state})")
            };
            options.push((display, provider_id));
        }
        options
    }

    fn registered_provider_status(status: &str) -> bool {
        matches!(
            status.trim().to_ascii_lowercase().as_str(),
            "configured"
                | "connected"
                | "ready"
                | "available"
                | "not_checked"
                | "unknown"
                | "disconnected"
                | "connecting"
                | "error"
        )
    }

    pub fn normalize_model_filters(&mut self) {
        let valid = self.model_provider_options().iter().any(|(_, value)| {
            value == "all" || value.eq_ignore_ascii_case(&self.model_provider_filter)
        });
        if !valid {
            self.model_provider_filter = "all".to_string();
            self.model_selected = 0;
        }
    }

    pub fn model_scope_label(&self) -> &'static str {
        if self.model_show_catalog {
            "Catalog"
        } else {
            "Active only"
        }
    }

    pub fn model_free_filter_label(&self) -> &'static str {
        if self.model_price_filter == ModelPriceFilter::FreeOnly {
            "Free only: ON"
        } else {
            "Free only: OFF"
        }
    }

    pub fn model_provider_label(&self) -> String {
        self.model_provider_options()
            .into_iter()
            .find(|(_, value)| value.eq_ignore_ascii_case(&self.model_provider_filter))
            .map(|(label, _)| label)
            .unwrap_or_else(|| "All registered".to_string())
    }

    pub fn model_price_state(&self, model: &str) -> ModelPriceState {
        model_price_state(model, self.model_evidence(model))
    }

    pub fn toggle_model_selection(&mut self, index: usize) {
        if self.model_policy_in_flight() {
            self.set_notice("Model selection save is still in progress".to_string());
            return;
        }
        let Some(model) = self.filtered_models().get(index).cloned() else {
            return;
        };
        if !self.selected_models.insert(model.clone()) {
            self.selected_models.remove(&model);
        }
        self.model_selected = index;
    }

    fn model_policy_in_flight(&self) -> bool {
        matches!(self.refresh_task, Some(RefreshTask::ModelPolicy(_, _)))
            || self.next_refresh_notice.is_some()
    }

    fn toggle_selected_model(&mut self) {
        self.toggle_model_selection(self.model_selected);
    }

    fn cycle_model_provider(&mut self) {
        let options = self.model_provider_options();
        if options.is_empty() {
            self.model_provider_filter = "all".to_string();
            return;
        }
        let current = options
            .iter()
            .position(|(_, value)| value.eq_ignore_ascii_case(&self.model_provider_filter))
            .unwrap_or(0);
        let next = (current + 1) % options.len();
        self.model_provider_filter = options[next].1.clone();
        self.model_selected = 0;
    }

    fn open_model_provider_picker(&mut self) {
        let options = self
            .model_provider_options()
            .into_iter()
            .map(|(label, value)| ConfigOption { label, value })
            .collect::<Vec<_>>();
        let selected = options
            .iter()
            .position(|option| {
                option
                    .value
                    .eq_ignore_ascii_case(&self.model_provider_filter)
            })
            .unwrap_or(0);
        self.modal = Some(Modal::Choice {
            key: "__FCC_MODEL_PROVIDER__".to_string(),
            label: "Model provider".to_string(),
            options,
            selected,
        });
    }

    fn cycle_model_price(&mut self) {
        self.model_price_filter = if self.model_price_filter == ModelPriceFilter::FreeOnly {
            ModelPriceFilter::All
        } else {
            ModelPriceFilter::FreeOnly
        };
        self.model_selected = 0;
    }

    fn toggle_model_catalog(&mut self) {
        self.model_show_catalog = !self.model_show_catalog;
        self.model_selected = 0;
        self.normalize_model_filters();
    }

    pub fn model_catalog_allowlist(&self) -> HashSet<String> {
        self.config_value("MODEL_CATALOG_ALLOWLIST")
            .unwrap_or_default()
            .replace('\r', "\n")
            .replace('\n', ",")
            .split(',')
            .map(str::trim)
            .filter(|entry| !entry.is_empty())
            .map(str::to_string)
            .collect()
    }

    pub fn config_value(&self, key: &str) -> Option<String> {
        self.config
            .fields
            .iter()
            .find(|field| field.key == key)
            .map(|field| field.value.clone())
    }

    pub fn model_catalog_mode(&self) -> Option<String> {
        self.config_value("MODEL_CATALOG_MODE")
            .filter(|value| !value.trim().is_empty())
            .map(|value| value.trim().to_ascii_lowercase())
    }

    fn apply_model_catalog(&mut self, allowlist: HashSet<String>, message: String) {
        if self.refresh_task.is_some() {
            self.set_notice("Another model operation is still in progress".to_string());
            return;
        }
        let mut values = HashMap::new();
        values.insert(
            "MODEL_CATALOG_MODE".to_string(),
            Value::String("curated".to_string()),
        );
        values.insert(
            "MODEL_CATALOG_ALLOWLIST".to_string(),
            Value::String(join_model_allowlist(&allowlist)),
        );
        let api = self.api.clone();
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let _ = sender.send(api.apply_values(&values));
        });
        self.next_refresh_notice = None;
        self.refresh_task = Some(RefreshTask::ModelPolicy(receiver, message));
        self.set_notice("Saving model selection…".to_string());
    }

    fn toggle_selected_models(&mut self) {
        if self.selected_models.is_empty() {
            self.set_error("Select models with Space or Shift/Ctrl-click first".to_string());
            return;
        }
        let selected = self.selected_models.clone();
        let allowlist = self.model_catalog_allowlist();
        let mode = self.model_catalog_mode();
        let inventory = self.model_inventory();
        let active = self.models.models.clone();

        // A single toggle action is deterministic for mixed selections: an
        // active row is removed from the effective allowlist and an inactive
        // catalog row is added. The provider/model ID shown in each row is
        // the exact value written to the server.
        let next =
            plan_toggled_allowlist(mode.as_deref(), &allowlist, &inventory, &active, &selected);
        self.apply_model_catalog(
            next,
            format!("Toggled {} selected model(s)", selected.len()),
        );
    }

    fn disable_all_models(&mut self) {
        self.apply_model_catalog(HashSet::new(), "All discovered models disabled".to_string());
    }

    pub fn model_inventory(&self) -> Vec<String> {
        let mut models = if self.models.catalog_models.is_empty() {
            self.models.models.clone()
        } else {
            self.models.catalog_models.clone()
        };
        for model in &self.models.models {
            if !models.iter().any(|candidate| candidate == model) {
                models.push(model.clone());
            }
        }
        // Custom-provider model IDs are user-owned configuration, not a
        // best-effort discovery result. Keep them visible in Catalog even
        // when the provider's discovery endpoint is unavailable or the
        // server cache predates the provider edit. Prefix unqualified IDs so
        // the routing identity remains unambiguous while preserving exact
        // IDs that already carry their provider prefix.
        for model in self.custom_provider_model_refs() {
            if !models.iter().any(|candidate| candidate == &model) {
                models.push(model);
            }
        }
        models.sort_by_key(|model| model.to_ascii_lowercase());
        models.dedup();
        models
    }

    fn custom_provider_model_refs(&self) -> Vec<String> {
        let mut models = Vec::new();
        for provider in &self.custom_providers {
            if provider.provider_id.is_empty() || !provider.enabled {
                continue;
            }
            for model_id in &provider.model_ids {
                let model_id = model_id.trim();
                if model_id.is_empty() {
                    continue;
                }
                let model = if Self::model_provider_id(model_id)
                    .eq_ignore_ascii_case(&provider.provider_id)
                {
                    model_id.to_string()
                } else {
                    format!("{}/{}", provider.provider_id, model_id)
                };
                if !models.iter().any(|candidate| candidate == &model) {
                    models.push(model);
                }
            }
        }
        models
    }

    pub fn model_is_routable(&self, model: &str) -> bool {
        self.models
            .models
            .iter()
            .any(|candidate| candidate == model)
    }

    pub fn model_label(&self, model: &str) -> String {
        self.models
            .catalog_model_labels
            .get(model)
            .or_else(|| self.models.model_labels.get(model))
            .cloned()
            .unwrap_or_else(|| model.to_string())
    }

    pub fn model_evidence(&self, model: &str) -> Option<&Value> {
        self.models
            .catalog_model_evidence
            .get(model)
            .or_else(|| self.models.model_evidence.get(model))
    }

    pub fn model_is_default(&self, model: &str) -> bool {
        self.config_value("MODEL")
            .is_some_and(|default| default.trim() == model)
    }

    fn model_provider_id(model: &str) -> &str {
        model
            .split_once('/')
            .map(|(provider, _)| provider)
            .unwrap_or("other")
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
            .filter(|(_, field)| field.key != "CUSTOM_PROVIDERS_JSON")
            .filter(|(_, field)| self.show_advanced || !field.advanced)
            .map(|(index, _)| index)
            .collect()
    }

    pub fn context_field(&self) -> Option<&ConfigField> {
        self.config
            .fields
            .iter()
            .find(|field| field.key == CONTEXT_KEY)
    }

    pub fn selected_provider(&self) -> Option<&ProviderStatus> {
        self.config.provider_status.get(self.provider_selected)
    }

    pub fn selected_model(&self) -> Option<String> {
        self.filtered_models().get(self.model_selected).cloned()
    }

    pub fn selected_field_index(&self) -> Option<usize> {
        match self.page {
            Page::Routing => self
                .routing_field_indices()
                .get(self.routing_selected)
                .copied(),
            Page::Context => self
                .config
                .fields
                .iter()
                .position(|field| field.key == CONTEXT_KEY),
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
        if self.refresh_task.is_some() {
            self.set_error("Another operation is still in progress".to_string());
            return;
        }
        if key == CONTEXT_KEY {
            let candidate = value.as_str().unwrap_or_default();
            if let Err(message) = validate_context(candidate) {
                self.set_error(message);
                return;
            }
        }
        match self.api.apply_field(key, value) {
            Ok(result) if result.valid && result.applied => {
                let refreshed = self.refresh_all();
                if refreshed {
                    if result.pending_fields.is_empty() {
                        self.set_notice(format!("Saved {key}"));
                    } else {
                        self.set_notice(format!(
                            "Saved {key}; restart/session boundary: {}",
                            result.pending_fields.join(", ")
                        ));
                    }
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
        if !self.model_is_routable(&model) {
            self.set_error(format!(
                "{model} is cataloged but not currently routable; update the model catalog policy first"
            ));
            return;
        }
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
            body: format!(
                "Delete {} ({})?",
                provider.display_name, provider.provider_id
            ),
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
        match self
            .api
            .connected_account_login(&provider.provider_id, mode)
        {
            Ok(value) => {
                self.modal = Some(Modal::Message {
                    title: format!("{} sign-in", provider.display_name),
                    body: connected_account_message(&provider.display_name, &value),
                })
            }
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
            Ok(value) => {
                self.diagnostic = value;
                self.content_scroll = 0;
                self.set_notice("Route diagnostic completed".to_string());
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn open_palette(&mut self) {
        self.modal = Some(Modal::Palette {
            input: TextInput::new(String::new(), false, false),
            selected: 0,
        });
    }

    fn select_modal_index(&mut self, index: usize) {
        let Some(modal) = self.modal.as_mut() else {
            return;
        };
        match modal {
            Modal::Choice {
                options, selected, ..
            } => *selected = clamp(index, options.len()),
            Modal::FieldPicker {
                field_indices,
                selected,
                ..
            } => *selected = clamp(index, field_indices.len()),
            Modal::ProviderEditor {
                selected, editing, ..
            } => {
                // A field editor owns the keyboard until it is submitted or
                // cancelled. Do not let a stray click retarget the draft
                // while the user is typing into a different field.
                if editing.is_none() {
                    *selected = index.min(7);
                }
            }
            Modal::Palette { selected, .. } => *selected = index,
            _ => {}
        }
    }

    /// A mouse click on a modal option is an activation, not a second
    /// keyboard-style selection step. This makes provider filters and field
    /// choices usable with a single click while keeping ProviderEditor rows
    /// as select-only controls because those rows open a text editor on Enter.
    fn activate_modal_index(&mut self, index: usize) -> Result<Option<ExternalAction>> {
        let Some(modal) = self.modal.as_ref() else {
            return Ok(None);
        };
        match modal {
            Modal::Choice { key, options, .. } => {
                let Some(option) = options.get(index).cloned() else {
                    return Ok(None);
                };
                let field_key = key.clone();
                self.modal = None;
                if field_key == "__FCC_MODEL_PROVIDER__" {
                    self.model_provider_filter = option.value;
                    self.model_selected = 0;
                } else {
                    let value = match option.value.as_str() {
                        "true" => Value::Bool(true),
                        "false" => Value::Bool(false),
                        _ => Value::String(option.value),
                    };
                    self.apply_field_value(&field_key, value);
                }
            }
            Modal::FieldPicker { field_indices, .. } => {
                let Some(field_index) = field_indices.get(index).copied() else {
                    return Ok(None);
                };
                self.modal = None;
                self.open_field_editor(field_index);
            }
            Modal::ProviderEditor { .. } => self.select_modal_index(index),
            Modal::Palette { .. } => return self.execute_palette_index(index),
            _ => {}
        }
        Ok(None)
    }

    /// Every palette row available from the current page. Page navigation and
    /// global actions are always present so all functionality stays reachable
    /// from the keyboard; page-contextual rows mirror the visible action bar.
    pub fn palette_inventory(&self) -> Vec<PaletteEntry> {
        let mut entries = Vec::new();
        for page in Page::ALL {
            entries.push(PaletteEntry {
                title: format!("Go to {}", page.label()),
                hint: "page".to_string(),
                action: UiAction::Navigate(page),
            });
        }
        let mut push = |title: &str, hint: &str, action: UiAction| {
            entries.push(PaletteEntry {
                title: title.to_string(),
                hint: hint.to_string(),
                action,
            })
        };
        push("Refresh current view", "reload snapshot", UiAction::Refresh);
        push("Toggle page navigation", "Ctrl-B", UiAction::ToggleSidebar);
        push("Toggle status panel", "Ctrl-J", UiAction::TogglePanel);
        push("Focus page navigation", "Ctrl-0", UiAction::FocusSidebar);
        push("Focus page", "Ctrl-1", UiAction::FocusEditor);
        push(
            "Launch Claude",
            "suspend TUI and run fcc-claude",
            UiAction::LaunchClaude(false),
        );
        push(
            "Launch Claude with danger permissions",
            "suspend TUI and run fccdanger",
            UiAction::LaunchClaude(true),
        );
        push(
            "Open command palette",
            "keyboard Ctrl-K Ctrl-P",
            UiAction::OpenPalette,
        );
        push("Quit control center", "exit", UiAction::Quit);
        match self.page {
            Page::Providers => {
                push(
                    "Configure selected provider",
                    "providers edit fields",
                    UiAction::ConfigureProvider,
                );
                push(
                    "Test selected provider",
                    "providers connectivity",
                    UiAction::TestProvider,
                );
                push(
                    "Add custom provider",
                    "providers new OpenAI compatible",
                    UiAction::NewCustomProvider,
                );
                push(
                    "Edit custom provider",
                    "providers",
                    UiAction::EditCustomProvider,
                );
                push(
                    "Delete custom provider",
                    "providers remove",
                    UiAction::DeleteCustomProvider,
                );
                push(
                    "Sign in connected account",
                    "providers OAuth login",
                    UiAction::LoginProvider,
                );
                push(
                    "Disconnect connected account",
                    "providers sign out",
                    UiAction::DisconnectProvider,
                );
            }
            Page::Models => {
                push("Search models", "models filter", UiAction::SearchModels);
                push(
                    "Choose model provider",
                    "models registered provider filter",
                    UiAction::ChooseModelProvider,
                );
                push(
                    "Toggle selected models",
                    "models catalog",
                    UiAction::ToggleSelectedModels,
                );
                push(
                    "Disable all models",
                    "models catalog",
                    UiAction::DisableAllModels,
                );
                push(
                    "Set MODEL to selected model",
                    "models exact route",
                    UiAction::AssignModel("MODEL".to_string()),
                );
            }
            Page::Routing | Page::Context | Page::Local | Page::Settings => {
                push("Edit selected field", "settings value", UiAction::EditField);
            }
            Page::Diagnostics => {
                push(
                    "Run route diagnostic",
                    "synthetic no network",
                    UiAction::RunDiagnostic,
                );
            }
            Page::Dashboard | Page::Usage => {}
        }
        if self.page == Page::Settings {
            push(
                "Toggle advanced fields",
                "settings show hide",
                UiAction::ToggleAdvanced,
            );
        }
        entries
    }

    fn execute_palette_index(&mut self, display_index: usize) -> Result<Option<ExternalAction>> {
        let inventory = self.palette_inventory();
        let query = match &self.modal {
            Some(Modal::Palette { input, .. }) => input.value.clone(),
            _ => return Ok(None),
        };
        let visible = match_palette(&query, &inventory);
        let Some(entry) = visible
            .get(display_index)
            .and_then(|index| inventory.get(*index))
            .cloned()
        else {
            return Ok(None);
        };
        self.modal = None;
        self.invoke_ui_action(entry.action)
    }

    fn handle_modal_key(&mut self, key: KeyEvent) -> Result<Option<ExternalAction>> {
        let Some(modal) = self.modal.take() else {
            return Ok(None);
        };
        match modal {
            Modal::Message { title, body } => {
                if !matches!(key.code, KeyCode::Esc | KeyCode::Enter) {
                    self.modal = Some(Modal::Message { title, body });
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
            Modal::SearchFiles { mut input } => match edit_input(&mut input, key) {
                InputOutcome::Cancel => {}
                InputOutcome::Submit => {
                    let query = input.value.trim().to_string();
                    self.sidebar_cursor = 0;
                    self.run_search(&query);
                }
                InputOutcome::Continue => self.modal = Some(Modal::SearchFiles { input }),
            },
            Modal::FindInFile { mut input } => match edit_input(&mut input, key) {
                InputOutcome::Cancel => {}
                InputOutcome::Submit => {
                    let needle = input.value.clone();
                    self.find_in_file(&needle);
                }
                InputOutcome::Continue => self.modal = Some(Modal::FindInFile { input }),
            },
            Modal::Palette {
                mut input,
                mut selected,
            } => {
                let control = key.modifiers.contains(KeyModifiers::CONTROL);
                match key.code {
                    KeyCode::Esc => return Ok(None),
                    KeyCode::Up => {
                        selected = selected.saturating_sub(1);
                        self.modal = Some(Modal::Palette { input, selected });
                        return Ok(None);
                    }
                    KeyCode::Down => {
                        selected = selected.saturating_add(1);
                        self.modal = Some(Modal::Palette { input, selected });
                        return Ok(None);
                    }
                    KeyCode::Char('p') | KeyCode::Char('P') if control => {
                        selected = selected.saturating_sub(1);
                        self.modal = Some(Modal::Palette { input, selected });
                        return Ok(None);
                    }
                    KeyCode::Char('n') | KeyCode::Char('N') if control => {
                        selected = selected.saturating_add(1);
                        self.modal = Some(Modal::Palette { input, selected });
                        return Ok(None);
                    }
                    KeyCode::Enter => {
                        self.modal = Some(Modal::Palette { input, selected });
                        let action = self.execute_palette_index(selected)?;
                        return Ok(action);
                    }
                    _ => {}
                }
                match edit_input(&mut input, key) {
                    InputOutcome::Cancel => {}
                    InputOutcome::Submit => {
                        self.modal = Some(Modal::Palette { input, selected });
                        let action = self.execute_palette_index(selected)?;
                        return Ok(action);
                    }
                    InputOutcome::Continue => {
                        self.modal = Some(Modal::Palette { input, selected: 0 })
                    }
                }
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
                    KeyCode::Esc => return Ok(None),
                    KeyCode::Up | KeyCode::Char('k') => {
                        selected = wrap_index(selected, options.len(), -1)
                    }
                    KeyCode::Down | KeyCode::Char('j') => {
                        selected = wrap_index(selected, options.len(), 1)
                    }
                    KeyCode::Enter => {
                        if let Some(option) = options.get(selected) {
                            if field_key == "__FCC_MODEL_PROVIDER__" {
                                self.model_provider_filter = option.value.clone();
                                self.model_selected = 0;
                                return Ok(None);
                            }
                            let value = if option.value == "true" {
                                Value::Bool(true)
                            } else if option.value == "false" {
                                Value::Bool(false)
                            } else {
                                Value::String(option.value.clone())
                            };
                            self.apply_field_value(&field_key, value);
                            return Ok(None);
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
                    KeyCode::Esc => return Ok(None),
                    KeyCode::Up | KeyCode::Char('k') => {
                        selected = wrap_index(selected, field_indices.len(), -1)
                    }
                    KeyCode::Down | KeyCode::Char('j') => {
                        selected = wrap_index(selected, field_indices.len(), 1)
                    }
                    KeyCode::Enter => {
                        if let Some(index) = field_indices.get(selected).copied() {
                            self.open_field_editor(index);
                            return Ok(None);
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
                    return Ok(None);
                }
                match key.code {
                    KeyCode::Esc => return Ok(None),
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
                        return Ok(None);
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
        Ok(None)
    }

    fn save_provider(&mut self, existing_id: Option<String>, draft: ProviderDraft) {
        if self.refresh_task.is_some() {
            self.set_error("Another operation is still in progress".to_string());
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
                if self.refresh_all() {
                    self.set_notice("Custom provider saved".to_string());
                }
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn execute_confirm(&mut self, action: ConfirmAction) {
        if self.refresh_task.is_some() {
            self.set_error("Another operation is still in progress".to_string());
            return;
        }
        match action {
            ConfirmAction::ClearField(key) => {
                self.apply_field_value(&key, Value::String(String::new()))
            }
            ConfirmAction::DeleteCustom(provider_id) => {
                match self.api.remove_custom_provider(&provider_id) {
                    Ok(_) => {
                        if self.refresh_all() {
                            self.set_notice(format!("Deleted {provider_id}"));
                        }
                    }
                    Err(error) => self.set_error(error.to_string()),
                }
            }
            ConfirmAction::DisconnectProvider(provider_id) => {
                match self.api.connected_account_disconnect(&provider_id) {
                    Ok(value) => {
                        let refreshed = self.refresh_all();
                        if refreshed {
                            self.modal = Some(Modal::Message {
                                title: "Account disconnected".to_string(),
                                body: pretty(&value),
                            });
                        } else {
                            self.modal = None;
                        }
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
        let status = self
            .status
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("offline");
        let host = self
            .status
            .get("host")
            .and_then(Value::as_str)
            .unwrap_or("127.0.0.1");
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
        self.notice = None;
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
        Self {
            api,
            page: Page::Dashboard,
            colors: Colors::fallback(),
            workspace: PathBuf::from("."),
            activity: Activity::Explorer,
            focus: Focus::Editor,
            sidebar_open: true,
            panel_open: false,
            tree: Vec::new(),
            tree_cursor: 0,
            expanded: HashSet::new(),
            files: Vec::new(),
            editor_focus: EditorFocus::Page,
            search_query: String::new(),
            find_needle: String::new(),
            search_hits: Vec::new(),
            git_branch: String::new(),
            git_changes: Vec::new(),
            git_error: None,
            config: ConfigResponse {
                fields: vec![context],
                ..ConfigResponse::default()
            },
            status: json!({"status":"running","host":"127.0.0.1","port":8082,"model":"demo/model"}),
            models: ModelsResponse::default(),
            custom_providers: Vec::new(),
            local_status: Vec::new(),
            usage: Value::Null,
            diagnostic: Value::Null,
            content_scroll: 0,
            provider_selected: 0,
            model_selected: 0,
            routing_selected: 0,
            local_selected: 0,
            setting_selected: 0,
            model_query: String::new(),
            model_provider_filter: "all".to_string(),
            model_price_filter: ModelPriceFilter::default(),
            model_show_catalog: false,
            selected_models: HashSet::new(),
            show_advanced: false,
            modal: None,
            notice: None,
            error: None,
            should_quit: false,
            sidebar_cursor: 0,
            hitboxes: Vec::new(),
            geometry: ChromeGeometry::default(),
            mouse: None,
            refresh_task: None,
            next_refresh_notice: None,
        }
    }
}

fn connected_account_message(provider: &str, value: &Value) -> String {
    let state = value
        .get("state")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_ascii_lowercase();
    let mode = value
        .get("mode")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_ascii_lowercase();
    match state.as_str() {
        "connecting" | "pending" | "authorizing" => {
            if mode == "device" {
                let code = value
                    .get("user_code")
                    .and_then(Value::as_str)
                    .filter(|code| !code.is_empty())
                    .unwrap_or("not yet available");
                format!(
                    "{provider} device sign-in started.\n\nVerification code: {code}\n\nComplete the verification step, then press R to refresh provider status."
                )
            } else {
                format!(
                    "{provider} sign-in started in your browser.\n\nComplete sign-in, then press R to refresh provider status."
                )
            }
        }
        "connected" => format!("{provider} is connected. Press R to refresh its models."),
        "error" => value
            .get("message")
            .and_then(Value::as_str)
            .filter(|message| !message.is_empty())
            .map(|message| format!("{provider} sign-in failed:\n\n{message}"))
            .unwrap_or_else(|| format!("{provider} sign-in failed. Check Diagnostics.")),
        _ => format!("{provider} sign-in state: {state}. Press R to refresh."),
    }
}

fn model_price_state(model: &str, evidence: Option<&Value>) -> ModelPriceState {
    let Some(record) = evidence.and_then(Value::as_object) else {
        return openrouter_free_fallback(model);
    };
    if let Some(is_free) = record.get("is_free").and_then(Value::as_bool) {
        return if is_free {
            ModelPriceState::Free
        } else {
            ModelPriceState::Paid
        };
    }
    if let Some(metadata) = record.get("catalog_metadata").and_then(Value::as_object) {
        if let Some(is_free) = metadata.get("is_free").and_then(Value::as_bool) {
            return if is_free {
                ModelPriceState::Free
            } else {
                ModelPriceState::Paid
            };
        }
        if let Some(is_free) = pricing_is_free(metadata.get("pricing")) {
            return if is_free {
                ModelPriceState::Free
            } else {
                ModelPriceState::Paid
            };
        }
    }
    if let Some(is_free) = pricing_is_free(record.get("pricing")) {
        return if is_free {
            ModelPriceState::Free
        } else {
            ModelPriceState::Paid
        };
    }
    openrouter_free_fallback(model)
}

fn openrouter_free_fallback(model: &str) -> ModelPriceState {
    // `:free` is an explicit model-ID contract used by OpenRouter and custom
    // OpenAI-compatible catalogs such as Cline. It is safe to honor without
    // inventing paid/free status for models that have no suffix or metadata.
    if model.to_ascii_lowercase().ends_with(":free") {
        ModelPriceState::Free
    } else {
        ModelPriceState::Unknown
    }
}

fn pricing_is_free(value: Option<&Value>) -> Option<bool> {
    let mut numbers = Vec::new();
    collect_price_numbers(value, &mut numbers);
    if numbers.is_empty() {
        return None;
    }
    Some(numbers.iter().all(|number| *number == 0.0))
}

fn collect_price_numbers(value: Option<&Value>, numbers: &mut Vec<f64>) {
    match value {
        Some(Value::Number(number)) => {
            if let Some(number) = number
                .as_f64()
                .filter(|number| number.is_finite() && *number >= 0.0)
            {
                numbers.push(number);
            }
        }
        Some(Value::String(value)) => {
            if let Some(number) = value
                .trim()
                .parse::<f64>()
                .ok()
                .filter(|number| number.is_finite() && *number >= 0.0)
            {
                numbers.push(number);
            }
        }
        Some(Value::Array(values)) => {
            for value in values {
                collect_price_numbers(Some(value), numbers);
            }
        }
        Some(Value::Object(values)) => {
            for value in values.values() {
                collect_price_numbers(Some(value), numbers);
            }
        }
        _ => {}
    }
}

fn join_model_allowlist(allowlist: &HashSet<String>) -> String {
    let mut values = allowlist.iter().cloned().collect::<Vec<_>>();
    values.sort_by_key(|value| value.to_ascii_lowercase());
    values.join(", ")
}

fn plan_disabled_allowlist(
    mode: Option<&str>,
    allowlist: &HashSet<String>,
    inventory: &[String],
    active: &[String],
    selected: &HashSet<String>,
) -> HashSet<String> {
    let has_wildcard = allowlist
        .iter()
        .any(|entry| entry == "*" || entry.ends_with("/*"));
    let broad_policy = mode == Some("all") || mode.is_none() || has_wildcard;
    let mut enabled = if !broad_policy {
        allowlist.clone()
    } else if mode == Some("all") {
        inventory.iter().cloned().collect()
    } else if mode.is_none() && allowlist.is_empty() {
        active.iter().cloned().collect()
    } else {
        inventory
            .iter()
            .filter(|model| model_is_allowlisted(model, allowlist))
            .cloned()
            .collect()
    };
    enabled.retain(|model| !selected.contains(model));
    if broad_policy {
        enabled.extend(
            allowlist
                .iter()
                .filter(|entry| !entry.ends_with("/*") && entry.as_str() != "*")
                .filter(|entry| !selected.contains(*entry))
                .cloned(),
        );
    }
    enabled
}

fn plan_toggled_allowlist(
    mode: Option<&str>,
    allowlist: &HashSet<String>,
    inventory: &[String],
    active: &[String],
    selected: &HashSet<String>,
) -> HashSet<String> {
    let active_selected = selected
        .iter()
        .filter(|model| active.iter().any(|candidate| candidate == *model))
        .cloned()
        .collect::<HashSet<_>>();
    let inactive_selected = selected
        .iter()
        .filter(|model| !active_selected.contains(*model))
        .cloned()
        .collect::<HashSet<_>>();
    let mut next = if active_selected.is_empty() {
        allowlist.clone()
    } else {
        plan_disabled_allowlist(mode, allowlist, inventory, active, &active_selected)
    };
    next.extend(inactive_selected);
    next
}

fn model_is_allowlisted(model: &str, allowlist: &HashSet<String>) -> bool {
    let provider = App::model_provider_id(model);
    allowlist.contains("*")
        || allowlist.contains(model)
        || allowlist.contains(&format!("{provider}/*"))
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

pub fn rendered_line_count(body: &str, width: u16) -> usize {
    Paragraph::new(body.to_string())
        .wrap(Wrap { trim: false })
        .line_count(width.max(1))
        .max(1)
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

    fn workbench_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("fcc-workbench-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("src")).unwrap();
        std::fs::write(
            dir.join("src").join("main.rs"),
            "fn main() {\n    println!(\"hi\");\n}\n",
        )
        .unwrap();
        std::fs::write(dir.join("notes.md"), "hello workspace\nsecond line\n").unwrap();
        dir
    }

    #[test]
    fn explorer_lists_directories_before_files_and_skips_hidden() {
        let dir = workbench_dir("explorer");
        std::fs::write(dir.join(".hidden"), "secret").unwrap();
        let mut app = App::fixture();
        app.set_workspace(dir.clone());
        assert!(app
            .tree
            .iter()
            .any(|entry| entry.name == "src" && entry.is_dir));
        assert!(app
            .tree
            .iter()
            .any(|entry| entry.name == "notes.md" && !entry.is_dir));
        assert!(!app.tree.iter().any(|entry| entry.name == ".hidden"));
        let first_dir = app.tree.iter().position(|entry| entry.is_dir).unwrap();
        let first_file = app.tree.iter().position(|entry| !entry.is_dir).unwrap();
        assert!(first_dir < first_file);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn open_file_jumps_to_line_and_viewer_scrolls() {
        let dir = workbench_dir("viewer");
        let mut app = App::fixture();
        app.set_workspace(dir.clone());
        app.open_file(dir.join("src").join("main.rs"), Some(2));
        assert_eq!(app.focus, Focus::Editor);
        let (_, file) = app.active_file().expect("file tab opens");
        assert_eq!(file.lines.len(), 3);
        assert_eq!(file.scroll, 1);
        app.move_focused(5);
        let (_, file) = app.active_file().expect("file tab stays open");
        assert_eq!(file.scroll, 2);
        app.scroll_top();
        let (_, file) = app.active_file().expect("file tab stays open");
        assert_eq!(file.scroll, 0);
        app.scroll_bottom();
        let (_, file) = app.active_file().expect("file tab stays open");
        assert_eq!(file.scroll, 2);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn mouse_scroll_keeps_file_viewer_focus() {
        let dir = workbench_dir("mouse-viewer");
        let mut app = App::fixture();
        app.set_workspace(dir.clone());
        app.open_file(dir.join("src").join("main.rs"), None);
        app.geometry.sidebar = Rect {
            x: 0,
            y: 0,
            width: 20,
            height: 20,
        };
        app.geometry.editor = Rect {
            x: 20,
            y: 0,
            width: 60,
            height: 20,
        };

        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::ScrollDown,
            column: 25,
            row: 4,
            modifiers: KeyModifiers::NONE,
        }))
        .unwrap();

        assert_eq!(app.editor_focus, EditorFocus::File(0));
        assert_eq!(app.active_file().expect("file remains active").1.scroll, 2);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn search_finds_case_insensitive_hits_and_skips_vendor_dirs() {
        let dir = workbench_dir("search");
        std::fs::create_dir_all(dir.join("node_modules")).unwrap();
        std::fs::write(dir.join("node_modules").join("bundle.js"), "hello hidden").unwrap();
        std::fs::write(dir.join(".dotfile"), "hello hidden").unwrap();
        let mut app = App::fixture();
        app.set_workspace(dir.clone());
        app.run_search("HELLO");
        assert_eq!(app.search_hits.len(), 1);
        assert_eq!(app.search_hits[0].line, 1);
        assert!(app.search_hits[0].path.ends_with("notes.md"));
        app.open_search_hit(0);
        assert!(app.active_file_title().unwrap().contains("notes.md"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn git_status_after_commit_reports_clean_tree() {
        if std::process::Command::new("git")
            .arg("--version")
            .output()
            .is_err()
        {
            return;
        }
        let dir = workbench_dir("git");
        let git = |args: &[&str]| {
            std::process::Command::new("git")
                .args(args)
                .current_dir(&dir)
                .output()
                .expect("git command runs")
        };
        assert!(git(&["init"]).status.success());
        assert!(git(&["add", "."]).status.success());
        let commit = std::process::Command::new("git")
            .args([
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-m",
                "init",
            ])
            .current_dir(&dir)
            .output()
            .expect("git commit runs");
        assert!(commit.status.success());
        let mut app = App::fixture();
        app.set_workspace(dir.clone());
        assert!(app.git_error.is_none());
        assert!(!app.git_branch.is_empty());
        assert!(app.git_changes.is_empty());
        std::fs::write(
            dir.join("notes.md"),
            "hello workspace\nsecond line\nedited\n",
        )
        .unwrap();
        app.refresh_git();
        assert_eq!(app.git_changes.len(), 1);
        assert_eq!(app.git_changes[0].unstaged, 'M');
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn activity_switch_resets_sidebar_cursor_and_maps_pages() {
        let mut app = App::fixture();
        app.sidebar_cursor = 5;
        app.set_activity(Activity::Models);
        assert_eq!(app.page, Page::Models);
        assert_eq!(app.focus, Focus::Editor);
        assert_eq!(app.sidebar_cursor, 0);
        app.focus = Focus::Sidebar;
        app.set_activity(Activity::Explorer);
        assert_eq!(app.focus, Focus::Sidebar);
    }

    #[test]
    fn reveal_in_explorer_selects_the_open_file_row() {
        let dir = workbench_dir("reveal");
        let mut app = App::fixture();
        app.set_workspace(dir.clone());
        app.open_file(dir.join("notes.md"), None);
        app.reveal_in_explorer();
        assert_eq!(app.activity, Activity::Explorer);
        assert_eq!(app.focus, Focus::Sidebar);
        let entry = app.tree.get(app.tree_cursor).expect("cursor row exists");
        assert!(entry.path.ends_with("notes.md"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn close_file_keeps_a_valid_editor_focus() {
        let dir = workbench_dir("tabs");
        let mut app = App::fixture();
        app.set_workspace(dir.clone());
        app.open_file(dir.join("notes.md"), None);
        app.open_file(dir.join("src").join("main.rs"), None);
        assert_eq!(app.tab_count(), 2);
        app.close_file(0);
        assert_eq!(app.editor_focus, EditorFocus::File(0));
        assert!(app.active_file_title().unwrap().contains("main.rs"));
        app.close_active_file();
        assert_eq!(app.editor_focus, EditorFocus::Page);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn control_chords_toggle_chrome_and_focus() {
        use crossterm::event::{Event, KeyCode, KeyEvent, KeyModifiers};
        let mut app = App::fixture();
        let chord = |code| {
            Event::Key(KeyEvent::new_with_kind(
                code,
                KeyModifiers::CONTROL,
                crossterm::event::KeyEventKind::Press,
            ))
        };
        app.handle_event(chord(KeyCode::Char('b'))).unwrap();
        assert!(!app.sidebar_open);
        app.handle_event(chord(KeyCode::Char('j'))).unwrap();
        assert!(app.panel_open);
        app.handle_event(chord(KeyCode::Char('0'))).unwrap();
        assert_eq!(app.focus, Focus::Sidebar);
        app.handle_event(chord(KeyCode::Char('1'))).unwrap();
        assert_eq!(app.focus, Focus::Editor);
    }

    #[test]
    fn tab_toggles_focus_without_cycling_pages_or_files() {
        let dir = workbench_dir("tab-focus");
        let mut app = App::fixture();
        app.open_file(dir.join("notes.md"), None);
        let original_page = app.page;

        app.handle_event(Event::Key(KeyEvent::new(KeyCode::Tab, KeyModifiers::NONE)))
            .unwrap();
        assert_eq!(app.focus, Focus::Sidebar);
        assert_eq!(app.page, original_page);
        assert_eq!(app.editor_focus, EditorFocus::File(0));

        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::BackTab,
            KeyModifiers::SHIFT,
        )))
        .unwrap();
        assert_eq!(app.focus, Focus::Editor);
        assert_eq!(app.page, original_page);
        assert_eq!(app.editor_focus, EditorFocus::File(0));

        app.focus = Focus::Sidebar;
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('b'),
            KeyModifiers::CONTROL,
        )))
        .unwrap();
        assert!(!app.sidebar_open);
        assert_eq!(app.focus, Focus::Editor);
        assert_eq!(app.page, original_page);
        let _ = std::fs::remove_dir_all(&dir);
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

        assert_eq!(app.filtered_models(), ["provider/free"]);
        app.model_show_catalog = true;
        assert_eq!(app.filtered_models().len(), 2);
        assert!(app
            .filtered_models()
            .iter()
            .any(|model| model == "provider/hidden-free"));
        app.model_query = "hidden".to_string();
        app.clamp_selections();
        assert_eq!(app.model_selected, 0);
        assert_eq!(
            app.selected_model().as_deref(),
            Some("provider/hidden-free")
        );
        assert!(!app.model_is_routable("provider/hidden-free"));
        assert_eq!(app.filtered_models(), ["provider/hidden-free"]);
    }

    #[test]
    fn list_navigation_stops_at_edges_and_model_keys_respect_focus() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["bai/one".to_string(), "bai/two".to_string()];

        app.move_focused(-20);
        assert_eq!(app.model_selected, 0);
        app.move_focused(20);
        assert_eq!(app.model_selected, 1);
        app.move_focused(20);
        assert_eq!(app.model_selected, 1);

        // The page can remain visible while the sidebar owns the keyboard;
        // model controls must not fire from that unrelated focus region.
        app.focus = Focus::Sidebar;
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char(' '),
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert!(app.selected_models.is_empty());

        app.focus = Focus::Editor;
        app.model_selected = 0;
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char(' '),
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert_eq!(app.selected_models, HashSet::from(["bai/one".to_string()]));
    }

    #[test]
    fn edge_keys_follow_sidebar_focus_instead_of_scrolling_the_page() {
        let mut app = App::fixture();
        app.page = Page::Usage;
        app.focus = Focus::Sidebar;
        app.sidebar_cursor = Page::Usage.index();
        app.content_scroll = 4;

        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::PageDown,
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert_eq!(app.page, Page::Diagnostics);
        assert_eq!(app.content_scroll, 0);

        app.handle_event(Event::Key(KeyEvent::new(KeyCode::Home, KeyModifiers::NONE)))
            .unwrap();
        assert_eq!(app.page, Page::Dashboard);
        assert_eq!(app.sidebar_cursor, 0);
        assert_eq!(app.content_scroll, 0);
    }

    #[test]
    fn usage_and_diagnostics_output_scroll_is_finite() {
        let mut app = App::fixture();
        app.page = Page::Usage;
        app.geometry.editor = Rect {
            x: 0,
            y: 0,
            width: 80,
            height: 12,
        };
        app.usage = serde_json::json!({
            "entries": (0..40).map(|index| serde_json::json!({"index": index})).collect::<Vec<_>>()
        });
        let max = app.content_line_count().saturating_sub(7);
        app.move_focused(10_000);
        assert_eq!(app.content_scroll, max);
        app.move_focused(10_000);
        assert_eq!(app.content_scroll, max);
        app.move_focused(-10_000);
        assert_eq!(app.content_scroll, 0);
        app.page = Page::Diagnostics;
        app.diagnostic = serde_json::json!({
            "checks": (0..30).map(|index| serde_json::json!({"index": index})).collect::<Vec<_>>()
        });
        app.scroll_content_to_end();
        assert_eq!(
            app.content_scroll,
            app.content_line_count().saturating_sub(7)
        );
    }

    #[test]
    fn content_scroll_counts_wrapped_output_lines() {
        let mut app = App::fixture();
        app.page = Page::Usage;
        app.geometry.editor = Rect {
            x: 0,
            y: 0,
            width: 24,
            height: 12,
        };
        app.usage = serde_json::json!({
            "long": "this is a deliberately long usage value that wraps on a compact terminal"
        });
        let logical_lines = pretty(&app.usage).lines().count();
        let rendered_lines = app.content_line_count();
        assert!(rendered_lines > logical_lines);

        app.scroll_content_to_end();
        assert_eq!(
            app.content_scroll,
            rendered_lines.saturating_sub(app.content_viewport_height())
        );
    }

    #[test]
    fn completed_background_refresh_updates_the_snapshot_without_blocking() {
        let mut app = App::fixture();
        let (sender, receiver) = std::sync::mpsc::channel();
        app.refresh_task = Some(RefreshTask::All(receiver));

        app.poll_background();
        assert!(app.refresh_task.is_some());

        let status = serde_json::json!({"status": "running"});
        sender
            .send((
                Ok(ConfigResponse::default()),
                Ok(status.clone()),
                Ok(ModelsResponse::default()),
                Ok(CustomProviderCollection::default()),
                Ok(ProviderCollection::default()),
                Ok(Value::Null),
            ))
            .unwrap();
        app.poll_background();

        assert!(app.refresh_task.is_none());
        assert_eq!(app.status, status);
        assert_eq!(app.notice.as_deref(), Some("FCC snapshot refreshed"));
    }

    #[test]
    fn model_refresh_surfaces_failed_provider_requests() {
        let mut app = App::fixture();
        let (sender, receiver) = std::sync::mpsc::channel();
        app.refresh_task = Some(RefreshTask::Models(receiver));
        let models = ModelsResponse {
            failed_providers: vec!["bai".to_string(), "cline".to_string()],
            ..ModelsResponse::default()
        };

        sender.send(Ok(models)).unwrap();
        app.poll_background();

        assert!(app.refresh_task.is_none());
        assert_eq!(app.notice, None);
        assert_eq!(
            app.error.as_deref(),
            Some("Model refresh incomplete — provider requests failed: bai, cline")
        );
    }

    #[test]
    fn completed_model_policy_save_starts_snapshot_refresh() {
        let mut app = App::fixture();
        app.selected_models.insert("bai/one".to_string());
        let (sender, receiver) = std::sync::mpsc::channel();
        app.refresh_task = Some(RefreshTask::ModelPolicy(
            receiver,
            "Models changed".to_string(),
        ));

        sender
            .send(Ok(ApplyResponse {
                valid: true,
                applied: true,
                ..ApplyResponse::default()
            }))
            .unwrap();
        app.poll_background();

        assert!(matches!(app.refresh_task, Some(RefreshTask::All(_))));
        assert!(app.selected_models.is_empty());
        assert_eq!(app.notice.as_deref(), Some("Refreshing FCC snapshot…"));
        assert_eq!(app.next_refresh_notice.as_deref(), Some("Models changed"));
    }

    #[test]
    fn model_selection_is_locked_while_policy_save_refreshes() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["bai/one".to_string()];
        let (_sender, receiver) = std::sync::mpsc::channel();
        app.refresh_task = Some(RefreshTask::ModelPolicy(receiver, "done".to_string()));

        app.toggle_model_selection(0);

        assert!(app.selected_models.is_empty());
        assert_eq!(
            app.notice.as_deref(),
            Some("Model selection save is still in progress")
        );
    }

    #[test]
    fn hidden_catalog_model_cannot_be_assigned_without_policy_change() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/routable".to_string()];
        app.models.catalog_models = vec![
            "provider/routable".to_string(),
            "provider/hidden".to_string(),
        ];
        app.model_show_catalog = true;
        app.model_query = "hidden".to_string();

        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();

        assert!(app
            .error
            .as_deref()
            .is_some_and(|message| message.contains("not currently routable")));
    }

    #[test]
    fn model_rows_are_selectable_with_a_mouse_click() {
        use ratatui::backend::TestBackend;
        use ratatui::Terminal;

        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["provider/one".to_string(), "provider/two".to_string()];
        app.models.catalog_models = app.models.models.clone();
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

        assert_eq!(app.model_selected, 1);
        assert_eq!(app.focus, Focus::Editor);
        assert_eq!(app.selected_model().as_deref(), Some("provider/two"));

        let first_rect = app
            .hitboxes
            .iter()
            .find_map(|hitbox| match &hitbox.action {
                UiAction::SelectModel(0) => Some(hitbox.rect),
                _ => None,
            })
            .expect("first model row should have a hitbox");
        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: first_rect.x,
            row: first_rect.y,
            modifiers: KeyModifiers::CONTROL,
        }))
        .unwrap();
        assert_eq!(
            app.selected_models,
            HashSet::from(["provider/one".to_string()])
        );

        app.handle_event(Event::Mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: rect.x,
            row: rect.y,
            modifiers: KeyModifiers::SHIFT,
        }))
        .unwrap();
        assert_eq!(
            app.selected_models,
            HashSet::from(["provider/one".to_string(), "provider/two".to_string()])
        );
    }

    #[test]
    fn model_provider_options_only_show_registered_or_active_providers() {
        let mut app = App::fixture();
        app.models.models = vec!["bai/free-model".to_string()];
        app.models.catalog_models = vec![
            "bai/free-model".to_string(),
            "missing/metadata-only".to_string(),
        ];
        app.config.provider_status = vec![
            ProviderStatus {
                provider_id: "bai".to_string(),
                display_name: "B.AI".to_string(),
                status: "configured".to_string(),
                label: "Configured".to_string(),
                ..ProviderStatus::default()
            },
            ProviderStatus {
                provider_id: "openai".to_string(),
                display_name: "OpenAI / ChatGPT".to_string(),
                status: "disconnected".to_string(),
                label: "Not connected".to_string(),
                ..ProviderStatus::default()
            },
            ProviderStatus {
                provider_id: "missing".to_string(),
                display_name: "Missing".to_string(),
                status: "missing_key".to_string(),
                label: "Missing key".to_string(),
                ..ProviderStatus::default()
            },
        ];

        let options = app.model_provider_options();
        assert!(options
            .iter()
            .any(|(label, value)| { label == "B.AI" && value == "bai" }));
        assert!(options.iter().any(|(label, value)| {
            label == "OpenAI / ChatGPT (Not connected)" && value == "openai"
        }));
        assert!(!options.iter().any(|(_, value)| value == "missing"));
        assert!(!options.iter().any(|(_, value)| value == "metadata-only"));
    }

    #[test]
    fn custom_provider_models_are_visible_in_catalog_and_free_ids_are_explicit() {
        let mut app = App::fixture();
        app.model_show_catalog = true;
        app.custom_providers = vec![
            CustomProvider {
                provider_id: "cline".to_string(),
                display_name: "Cline".to_string(),
                enabled: true,
                model_ids: vec![
                    "z-ai/glm-5.3-flash:free".to_string(),
                    "cline/already-prefixed".to_string(),
                    "".to_string(),
                ],
                ..CustomProvider::default()
            },
            CustomProvider {
                provider_id: "disabled".to_string(),
                enabled: false,
                model_ids: vec!["hidden/model:free".to_string()],
                ..CustomProvider::default()
            },
        ];
        app.config.provider_status = vec![ProviderStatus {
            provider_id: "cline".to_string(),
            display_name: "Cline".to_string(),
            status: "configured".to_string(),
            ..ProviderStatus::default()
        }];

        let inventory = app.model_inventory();
        assert!(inventory.contains(&"cline/z-ai/glm-5.3-flash:free".to_string()));
        assert!(inventory.contains(&"cline/already-prefixed".to_string()));
        assert!(!inventory.iter().any(|model| model.starts_with("disabled/")));
        assert_eq!(
            app.model_price_state("cline/z-ai/glm-5.3-flash:free"),
            ModelPriceState::Free
        );

        app.model_price_filter = ModelPriceFilter::FreeOnly;
        assert_eq!(app.filtered_models(), ["cline/z-ai/glm-5.3-flash:free"]);
    }

    #[test]
    fn provider_picker_does_not_invent_unknown_prefixes_when_status_exists() {
        let mut app = App::fixture();
        app.models.models = vec!["bai/active".to_string(), "ghost/model".to_string()];
        app.config.provider_status = vec![ProviderStatus {
            provider_id: "bai".to_string(),
            display_name: "B.AI".to_string(),
            status: "configured".to_string(),
            ..ProviderStatus::default()
        }];

        let options = app.model_provider_options();
        assert!(options.iter().any(|(_, value)| value == "bai"));
        assert!(!options.iter().any(|(_, value)| value == "ghost"));
    }

    #[test]
    fn model_price_filter_is_explicit_and_never_uses_price_question_mark() {
        let mut app = App::fixture();
        app.models.models = vec![
            "bai/free-model".to_string(),
            "bai/unknown-model".to_string(),
            "bai/paid-model".to_string(),
        ];
        app.models.catalog_models = app.models.models.clone();
        app.models.model_evidence.insert(
            "bai/free-model".to_string(),
            serde_json::json!({"is_free": true}),
        );
        app.models.model_evidence.insert(
            "bai/paid-model".to_string(),
            serde_json::json!({"is_free": false}),
        );

        assert_eq!(
            app.filtered_models(),
            ["bai/free-model", "bai/paid-model", "bai/unknown-model"]
        );
        assert_eq!(
            app.model_price_state("bai/free-model"),
            ModelPriceState::Free
        );
        assert_eq!(
            app.model_price_state("bai/paid-model"),
            ModelPriceState::Paid
        );
        assert_eq!(
            app.model_price_state("bai/unknown-model"),
            ModelPriceState::Unknown
        );
        app.model_price_filter = ModelPriceFilter::FreeOnly;
        assert_eq!(app.filtered_models(), ["bai/free-model"]);
    }

    #[test]
    fn model_keyboard_controls_are_deterministic_and_multi_selectable() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["bai/one".to_string(), "cline/two".to_string()];
        app.models.catalog_models = app.models.models.clone();
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
                status: "configured".to_string(),
                ..ProviderStatus::default()
            },
        ];

        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char(' '),
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert_eq!(app.selected_models, HashSet::from(["bai/one".to_string()]));
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char(' '),
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert!(app.selected_models.is_empty());

        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('v'),
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert!(app.model_show_catalog);
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('n'),
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert_eq!(app.model_price_filter, ModelPriceFilter::FreeOnly);
    }

    #[test]
    fn model_provider_filter_opens_an_explicit_registered_provider_picker() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.models.models = vec!["bai/one".to_string(), "cline/two".to_string()];
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
                status: "configured".to_string(),
                ..ProviderStatus::default()
            },
        ];
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('p'),
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert!(matches!(
            app.modal,
            Some(Modal::Choice { ref key, .. }) if key == "__FCC_MODEL_PROVIDER__"
        ));
        for _ in 0..2 {
            app.handle_event(Event::Key(KeyEvent::new(KeyCode::Down, KeyModifiers::NONE)))
                .unwrap();
        }
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert_eq!(app.model_provider_filter, "cline");
        assert_eq!(app.filtered_models(), ["cline/two"]);
    }

    #[test]
    fn choice_modal_escape_closes_without_applying_a_value() {
        let mut app = App::fixture();
        app.modal = Some(Modal::Choice {
            key: "__FCC_MODEL_PROVIDER__".to_string(),
            label: "Model provider".to_string(),
            options: vec![ConfigOption {
                value: "cline".to_string(),
                label: "Cline".to_string(),
            }],
            selected: 0,
        });

        app.handle_event(Event::Key(KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE)))
            .unwrap();

        assert!(app.modal.is_none());
        assert_eq!(app.model_provider_filter, "all");
    }

    #[test]
    fn disabling_models_expands_broad_policies_before_subtracting_selection() {
        let inventory = vec![
            "bai/selected".to_string(),
            "bai/retained".to_string(),
            "cline/retained".to_string(),
        ];
        let active = inventory.clone();
        let selected = HashSet::from(["bai/selected".to_string()]);
        let wildcard = HashSet::from(["*".to_string()]);
        assert_eq!(
            plan_disabled_allowlist(Some("all"), &wildcard, &inventory, &active, &selected),
            HashSet::from(["bai/retained".to_string(), "cline/retained".to_string()])
        );

        let explicit = HashSet::from(["bai/selected".to_string(), "bai/retained".to_string()]);
        assert_eq!(
            plan_disabled_allowlist(Some("curated"), &explicit, &inventory, &active, &selected),
            HashSet::from(["bai/retained".to_string()])
        );
    }

    #[test]
    fn toggling_models_inverts_active_and_catalog_selection() {
        let inventory = vec![
            "bai/active".to_string(),
            "bai/catalog-only".to_string(),
            "cline/retained".to_string(),
        ];
        let active = vec!["bai/active".to_string(), "cline/retained".to_string()];
        let allowlist = HashSet::from(["bai/active".to_string(), "cline/retained".to_string()]);
        let selected = HashSet::from(["bai/active".to_string(), "bai/catalog-only".to_string()]);

        assert_eq!(
            plan_toggled_allowlist(Some("curated"), &allowlist, &inventory, &active, &selected,),
            HashSet::from(["bai/catalog-only".to_string(), "cline/retained".to_string(),])
        );
    }

    #[test]
    fn connected_account_message_does_not_render_oauth_payload() {
        let value = serde_json::json!({
            "state": "connecting",
            "mode": "browser",
            "attempt_id": "login_secret",
            "authorization_url": "https://auth.example.test/?code=secret",
        });
        let message = connected_account_message("OpenAI / ChatGPT", &value);

        assert!(message.contains("sign-in started"));
        assert!(message.contains("refresh provider status"));
        assert!(!message.contains("auth.example.test"));
        assert!(!message.contains("login_secret"));
    }

    #[test]
    fn palette_inventory_reaches_every_page() {
        let app = App::fixture();
        let inventory = app.palette_inventory();
        for page in Page::ALL {
            assert!(
                inventory.iter().any(|entry| matches!(
                    &entry.action,
                    UiAction::Navigate(target) if *target == page
                )),
                "palette must reach {}",
                page.label()
            );
        }
    }

    #[test]
    fn palette_filter_matches_titles_and_hints_case_insensitively() {
        let app = App::fixture();
        let inventory = app.palette_inventory();
        let by_title = match_palette("diagnostic", &inventory);
        assert!(!by_title.is_empty());
        assert!(by_title.iter().all(|index| inventory[*index]
            .title
            .to_ascii_lowercase()
            .contains("diagnostic")
            || inventory[*index]
                .hint
                .to_ascii_lowercase()
                .contains("diagnostic")));
        let upper = match_palette("DIAGNOSTIC", &inventory);
        assert_eq!(by_title, upper);
        assert_eq!(match_palette("", &inventory).len(), inventory.len());
        assert!(match_palette("no-such-command-xyz", &inventory).is_empty());
        assert!(!match_palette("  launch  ", &inventory).is_empty());
    }

    #[test]
    fn control_k_opens_palette_and_enter_navigates() {
        let mut app = App::fixture();
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('k'),
            KeyModifiers::CONTROL,
        )))
        .unwrap();
        assert!(matches!(app.modal, Some(Modal::Palette { .. })));

        for character in "dashboard".chars() {
            app.handle_event(Event::Key(KeyEvent::new(
                KeyCode::Char(character),
                KeyModifiers::NONE,
            )))
            .unwrap();
        }
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert_eq!(app.page, Page::Dashboard);
        assert!(app.modal.is_none());
    }

    #[test]
    fn palette_escape_keeps_current_page() {
        let mut app = App::fixture();
        app.page = Page::Models;
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Char('p'),
            KeyModifiers::CONTROL,
        )))
        .unwrap();
        assert!(matches!(app.modal, Some(Modal::Palette { .. })));
        app.handle_event(Event::Key(KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE)))
            .unwrap();
        assert!(app.modal.is_none());
        assert_eq!(app.page, Page::Models);
    }

    #[test]
    fn palette_quit_entry_exits() {
        let mut app = App::fixture();
        app.open_palette();
        for character in "quit control".chars() {
            app.handle_event(Event::Key(KeyEvent::new(
                KeyCode::Char(character),
                KeyModifiers::NONE,
            )))
            .unwrap();
        }
        let inventory = app.palette_inventory();
        let visible = match_palette("quit control", &inventory);
        assert_eq!(visible.len(), 1);
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert!(app.should_quit);
    }

    #[test]
    fn palette_out_of_range_selection_is_a_noop() {
        let mut app = App::fixture();
        app.open_palette();
        // Filter down to one row, then move the cursor past the end.
        for character in "quit control".chars() {
            app.handle_event(Event::Key(KeyEvent::new(
                KeyCode::Char(character),
                KeyModifiers::NONE,
            )))
            .unwrap();
        }
        for _ in 0..5 {
            app.handle_event(Event::Key(KeyEvent::new(KeyCode::Down, KeyModifiers::NONE)))
                .unwrap();
        }
        app.handle_event(Event::Key(KeyEvent::new(
            KeyCode::Enter,
            KeyModifiers::NONE,
        )))
        .unwrap();
        assert!(!app.should_quit);
        assert!(matches!(app.modal, Some(Modal::Palette { .. })));
    }
}
