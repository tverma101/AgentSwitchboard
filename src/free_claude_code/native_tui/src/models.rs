use crate::api::{ConfigResponse, ModelsResponse};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap};

pub const MODEL_KEY: &str = "MODEL";
pub const MODEL_FABLE_KEY: &str = "MODEL_FABLE";
pub const MODEL_OPUS_KEY: &str = "MODEL_OPUS";
pub const MODEL_SONNET_KEY: &str = "MODEL_SONNET";
pub const MODEL_HAIKU_KEY: &str = "MODEL_HAIKU";
pub const CATALOG_MODE_KEY: &str = "MODEL_CATALOG_MODE";
pub const CATALOG_ALLOWLIST_KEY: &str = "MODEL_CATALOG_ALLOWLIST";
pub const ALIASES_KEY: &str = "MODEL_ALIASES";

const ROUTING_ASSIGNMENT_KEYS: [&str; 5] = [
    MODEL_KEY,
    MODEL_FABLE_KEY,
    MODEL_OPUS_KEY,
    MODEL_SONNET_KEY,
    MODEL_HAIKU_KEY,
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PriceState {
    Free,
    Paid,
    Unknown,
}

impl PriceState {
    pub fn label(self) -> &'static str {
        match self {
            Self::Free => "FREE",
            Self::Paid => "PAID",
            Self::Unknown => "PRICE?",
        }
    }

    pub fn search_token(self) -> &'static str {
        match self {
            Self::Free => "free",
            Self::Paid => "paid",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum PriceFilter {
    #[default]
    All,
    Free,
    Paid,
    Unknown,
}

impl PriceFilter {
    pub fn label(self) -> &'static str {
        match self {
            Self::All => "All prices",
            Self::Free => "Free",
            Self::Paid => "Paid",
            Self::Unknown => "Unknown price",
        }
    }

    pub fn next(self) -> Self {
        match self {
            Self::All => Self::Free,
            Self::Free => Self::Paid,
            Self::Paid => Self::Unknown,
            Self::Unknown => Self::All,
        }
    }

    fn matches(self, price: PriceState) -> bool {
        match self {
            Self::All => true,
            Self::Free => price == PriceState::Free,
            Self::Paid => price == PriceState::Paid,
            Self::Unknown => price == PriceState::Unknown,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum AccessFilter {
    #[default]
    All,
    Enabled,
    Blocked,
    Assigned,
}

impl AccessFilter {
    pub fn label(self) -> &'static str {
        match self {
            Self::All => "All models",
            Self::Enabled => "Enabled",
            Self::Blocked => "Blocked",
            Self::Assigned => "Assigned",
        }
    }

    pub fn next(self) -> Self {
        match self {
            Self::All => Self::Enabled,
            Self::Enabled => Self::Blocked,
            Self::Blocked => Self::Assigned,
            Self::Assigned => Self::All,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ModelSort {
    #[default]
    Provider,
    FreeFirst,
    Name,
}

impl ModelSort {
    pub fn label(self) -> &'static str {
        match self {
            Self::Provider => "Group: provider",
            Self::FreeFirst => "Sort: free first",
            Self::Name => "Sort: name",
        }
    }

    pub fn next(self) -> Self {
        match self {
            Self::Provider => Self::FreeFirst,
            Self::FreeFirst => Self::Name,
            Self::Name => Self::Provider,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ModelRecord {
    pub model_ref: String,
    pub label: String,
    pub provider_id: String,
    pub provider_label: String,
    pub price: PriceState,
    pub routable: bool,
    pub evidence: Value,
}

#[derive(Debug, Clone, Default)]
pub struct CatalogSnapshot {
    pub records: Vec<ModelRecord>,
    pub aliases_by_ref: HashMap<String, Vec<String>>,
    pub routing: BTreeMap<String, String>,
    pub catalog_mode: String,
    pub allowlist: String,
    pub configured_default: String,
}

impl CatalogSnapshot {
    pub fn from_admin(models: &ModelsResponse, config: &ConfigResponse) -> Self {
        let inventory = model_inventory(models);
        let routable: BTreeSet<String> = models.models.iter().cloned().collect();
        let provider_labels = provider_labels(models);
        let aliases_by_ref = reverse_aliases(config_field(config, ALIASES_KEY));
        let mut records = Vec::with_capacity(inventory.len());
        for model_ref in inventory {
            let evidence = model_evidence(models, &model_ref)
                .cloned()
                .unwrap_or(Value::Null);
            let provider_id = provider_id(&model_ref);
            let provider_label = provider_labels
                .get(&provider_id)
                .cloned()
                .unwrap_or_else(|| humanize_provider(&provider_id));
            let label = models
                .catalog_model_labels
                .get(&model_ref)
                .or_else(|| models.model_labels.get(&model_ref))
                .cloned()
                .unwrap_or_else(|| model_ref.clone());
            let routable_flag = routable.contains(&model_ref);
            records.push(ModelRecord {
                price: price_state(&model_ref, &evidence),
                model_ref,
                label,
                provider_id,
                provider_label,
                routable: routable_flag,
                evidence,
            });
        }
        let routing = ROUTING_ASSIGNMENT_KEYS
            .iter()
            .map(|key| ((*key).to_string(), config_field(config, key)))
            .collect();
        Self {
            records,
            aliases_by_ref,
            routing,
            catalog_mode: config_field(config, CATALOG_MODE_KEY),
            allowlist: config_field(config, CATALOG_ALLOWLIST_KEY),
            configured_default: config_field(config, MODEL_KEY),
        }
    }

    pub fn record(&self, model_ref: &str) -> Option<&ModelRecord> {
        self.records
            .iter()
            .find(|record| record.model_ref == model_ref)
    }

    pub fn known_refs(&self) -> BTreeSet<String> {
        self.records
            .iter()
            .map(|record| record.model_ref.clone())
            .collect()
    }

    pub fn provider_options(&self) -> Vec<(String, String)> {
        let mut seen = BTreeMap::new();
        for record in &self.records {
            seen.entry(record.provider_id.clone())
                .or_insert_with(|| record.provider_label.clone());
        }
        seen.into_iter().collect()
    }

    pub fn effective_enabled(&self) -> BTreeSet<String> {
        effective_enabled(
            &self.catalog_mode,
            &self.allowlist,
            &self.known_refs(),
            &self
                .records
                .iter()
                .filter(|record| record.routable)
                .map(|record| record.model_ref.clone())
                .collect(),
        )
    }

    pub fn default_unavailable(&self) -> bool {
        !self.configured_default.trim().is_empty()
            && !self
                .records
                .iter()
                .any(|record| record.model_ref == self.configured_default)
    }

    pub fn aliases_for(&self, model_ref: &str) -> Vec<String> {
        self.aliases_by_ref
            .get(model_ref)
            .cloned()
            .unwrap_or_default()
    }

    pub fn assigned_keys(&self, model_ref: &str) -> Vec<&'static str> {
        ROUTING_ASSIGNMENT_KEYS
            .into_iter()
            .filter(|key| self.routing.get(*key).map(String::as_str) == Some(model_ref))
            .collect()
    }
}

#[derive(Debug, Clone)]
pub struct ModelBrowser {
    pub query: String,
    pub price_filter: PriceFilter,
    pub access_filter: AccessFilter,
    pub sort: ModelSort,
    pub provider_filter: Option<String>,
    pub search_focused: bool,
    pub selected: usize,
    loaded: bool,
    initial_default: String,
    pending_default: String,
    initial_enabled: BTreeSet<String>,
    pending_enabled: BTreeSet<String>,
}

impl Default for ModelBrowser {
    fn default() -> Self {
        Self {
            query: String::new(),
            price_filter: PriceFilter::All,
            access_filter: AccessFilter::All,
            sort: ModelSort::Provider,
            provider_filter: None,
            search_focused: false,
            selected: 0,
            loaded: false,
            initial_default: String::new(),
            pending_default: String::new(),
            initial_enabled: BTreeSet::new(),
            pending_enabled: BTreeSet::new(),
        }
    }
}

impl ModelBrowser {
    pub fn sync(&mut self, snapshot: &CatalogSnapshot) {
        let known = snapshot.known_refs();
        let effective = snapshot.effective_enabled();
        if !self.loaded {
            self.initial_default = snapshot.configured_default.clone();
            self.pending_default = snapshot.configured_default.clone();
            self.initial_enabled = effective.clone();
            self.pending_enabled = effective;
            if known.contains(&self.pending_default) {
                self.initial_enabled.insert(self.pending_default.clone());
                self.pending_enabled.insert(self.pending_default.clone());
            }
            self.loaded = true;
            self.clamp_selection(snapshot);
            return;
        }

        let changed_enabled: BTreeSet<String> = self
            .pending_enabled
            .symmetric_difference(&self.initial_enabled)
            .cloned()
            .collect();
        let default_changed = self.pending_default != self.initial_default;
        self.initial_default = snapshot.configured_default.clone();
        if !default_changed {
            self.pending_default = snapshot.configured_default.clone();
        }
        self.initial_enabled = effective.intersection(&known).cloned().collect();
        let mut pending = self.initial_enabled.clone();
        for model in changed_enabled.intersection(&known) {
            if self.pending_enabled.contains(model) {
                pending.insert(model.clone());
            } else {
                pending.remove(model);
            }
        }
        self.pending_enabled = pending;
        if known.contains(&self.pending_default) {
            self.initial_enabled.insert(self.pending_default.clone());
            self.pending_enabled.insert(self.pending_default.clone());
        }
        self.clamp_selection(snapshot);
    }

    pub fn commit(&mut self, snapshot: &CatalogSnapshot) {
        self.loaded = false;
        self.sync(snapshot);
    }

    pub fn discard(&mut self) {
        self.pending_default = self.initial_default.clone();
        self.pending_enabled = self.initial_enabled.clone();
        if !self.pending_default.is_empty() {
            self.pending_enabled.insert(self.pending_default.clone());
        }
    }

    pub fn dirty(&self) -> bool {
        self.pending_default != self.initial_default || self.pending_enabled != self.initial_enabled
    }

    pub fn changes_count(&self) -> usize {
        let mut changes = self
            .pending_enabled
            .symmetric_difference(&self.initial_enabled)
            .count();
        if self.pending_default != self.initial_default {
            changes += 1;
        }
        changes
    }

    pub fn pending_default(&self) -> &str {
        &self.pending_default
    }

    pub fn is_enabled(&self, model_ref: &str) -> bool {
        self.pending_enabled.contains(model_ref)
    }

    pub fn is_default(&self, model_ref: &str) -> bool {
        self.pending_default == model_ref
    }

    pub fn default_unavailable(&self, snapshot: &CatalogSnapshot) -> bool {
        !self.pending_default.trim().is_empty() && snapshot.record(&self.pending_default).is_none()
    }

    pub fn make_default(&mut self, model_ref: &str, snapshot: &CatalogSnapshot) -> Option<String> {
        snapshot.record(model_ref)?;
        self.pending_default = model_ref.to_string();
        self.pending_enabled.insert(model_ref.to_string());
        Some(format!("Default → {model_ref} (enables on save)"))
    }

    pub fn toggle_access(
        &mut self,
        model_ref: &str,
        snapshot: &CatalogSnapshot,
    ) -> Result<String, String> {
        if snapshot.record(model_ref).is_none() {
            return Err("Select a model first".to_string());
        }
        if !self.pending_enabled.contains(model_ref) {
            self.pending_enabled.insert(model_ref.to_string());
            return Ok(format!("Enabled {model_ref} (save to persist)"));
        }
        if self.pending_default == model_ref {
            let Some(replacement) = self.choose_replacement_default(model_ref, snapshot) else {
                return Err(
                    "This is the only discovered model, so it cannot be disabled.".to_string(),
                );
            };
            self.pending_enabled.insert(replacement.clone());
            self.pending_default = replacement.clone();
            self.pending_enabled.remove(model_ref);
            return Ok(format!(
                "Disabled {model_ref}; default handed to {replacement}"
            ));
        }
        self.pending_enabled.remove(model_ref);
        Ok(format!("Disabled {model_ref} (save to persist)"))
    }

    fn choose_replacement_default(
        &self,
        model_ref: &str,
        snapshot: &CatalogSnapshot,
    ) -> Option<String> {
        let mut enabled: Vec<String> = self
            .pending_enabled
            .iter()
            .filter(|candidate| *candidate != model_ref)
            .cloned()
            .collect();
        enabled.sort_by_key(|left| left.to_ascii_lowercase());
        if let Some(replacement) = enabled.into_iter().next() {
            return Some(replacement);
        }
        let mut known: Vec<String> = snapshot
            .records
            .iter()
            .map(|record| record.model_ref.clone())
            .filter(|candidate| candidate != model_ref)
            .collect();
        known.sort_by_key(|left| left.to_ascii_lowercase());
        known.into_iter().next()
    }

    pub fn filtered_refs(&self, snapshot: &CatalogSnapshot) -> Vec<String> {
        let query = self.query.trim().to_ascii_lowercase();
        let mut rows: Vec<&ModelRecord> = snapshot
            .records
            .iter()
            .filter(|record| self.matches(record, snapshot, &query))
            .collect();
        rows.sort_by(|left, right| self.compare_records(left, right));
        rows.into_iter()
            .map(|record| record.model_ref.clone())
            .collect()
    }

    fn matches(&self, record: &ModelRecord, snapshot: &CatalogSnapshot, query: &str) -> bool {
        if let Some(provider) = &self.provider_filter {
            if !record.provider_id.eq_ignore_ascii_case(provider) {
                return false;
            }
        }
        if !self.price_filter.matches(record.price) {
            return false;
        }
        let enabled = self.pending_enabled.contains(&record.model_ref);
        let assigned = !snapshot.assigned_keys(&record.model_ref).is_empty()
            || self.pending_default == record.model_ref;
        match self.access_filter {
            AccessFilter::All => {}
            AccessFilter::Enabled => {
                if !enabled {
                    return false;
                }
            }
            AccessFilter::Blocked => {
                if enabled {
                    return false;
                }
            }
            AccessFilter::Assigned => {
                if !assigned {
                    return false;
                }
            }
        }
        if query.is_empty() {
            return true;
        }
        self.search_haystack(record, snapshot)
            .to_ascii_lowercase()
            .contains(query)
    }

    fn search_haystack(&self, record: &ModelRecord, snapshot: &CatalogSnapshot) -> String {
        let mut parts = vec![
            record.model_ref.clone(),
            record.label.clone(),
            record.provider_id.clone(),
            record.provider_label.clone(),
            record.price.search_token().to_string(),
            record.price.label().to_string(),
        ];
        parts.extend(snapshot.aliases_for(&record.model_ref));
        parts.extend(capability_search_tags(&record.evidence));
        if self.pending_enabled.contains(&record.model_ref) {
            parts.push("enabled".to_string());
        } else {
            parts.push("blocked".to_string());
            parts.push("disabled".to_string());
        }
        if self.pending_default == record.model_ref {
            parts.push("default".to_string());
        }
        if record.routable {
            parts.push("routable".to_string());
        }
        parts.join(" ")
    }

    fn compare_records(&self, left: &ModelRecord, right: &ModelRecord) -> std::cmp::Ordering {
        let price_rank = |price: PriceState| match price {
            PriceState::Free => 0,
            PriceState::Unknown => 1,
            PriceState::Paid => 2,
        };
        let provider = left
            .provider_id
            .to_ascii_lowercase()
            .cmp(&right.provider_id.to_ascii_lowercase())
            .then(
                left.provider_label
                    .to_ascii_lowercase()
                    .cmp(&right.provider_label.to_ascii_lowercase()),
            );
        let name = left
            .label
            .to_ascii_lowercase()
            .cmp(&right.label.to_ascii_lowercase())
            .then(
                left.model_ref
                    .to_ascii_lowercase()
                    .cmp(&right.model_ref.to_ascii_lowercase()),
            );
        match self.sort {
            ModelSort::Provider => provider.then_with(|| {
                price_rank(left.price)
                    .cmp(&price_rank(right.price))
                    .then(name)
            }),
            ModelSort::FreeFirst => price_rank(left.price)
                .cmp(&price_rank(right.price))
                .then(provider)
                .then(name),
            ModelSort::Name => name.then(provider),
        }
    }

    pub fn selected_ref(&self, snapshot: &CatalogSnapshot) -> Option<String> {
        self.filtered_refs(snapshot).get(self.selected).cloned()
    }

    pub fn clamp_selection(&mut self, snapshot: &CatalogSnapshot) {
        let len = self.filtered_refs(snapshot).len();
        self.selected = if len == 0 {
            0
        } else {
            self.selected.min(len - 1)
        };
    }

    pub fn cycle_provider_filter(&mut self, snapshot: &CatalogSnapshot) {
        let options = snapshot.provider_options();
        if options.is_empty() {
            self.provider_filter = None;
            return;
        }
        let current = self.provider_filter.as_deref();
        let next = match current {
            None => Some(options[0].0.clone()),
            Some(provider) => {
                let index = options
                    .iter()
                    .position(|(id, _)| id.eq_ignore_ascii_case(provider));
                match index {
                    Some(index) if index + 1 < options.len() => Some(options[index + 1].0.clone()),
                    _ => None,
                }
            }
        };
        self.provider_filter = next;
        self.selected = 0;
    }

    pub fn provider_filter_label(&self, snapshot: &CatalogSnapshot) -> String {
        match &self.provider_filter {
            None => "All providers".to_string(),
            Some(provider) => snapshot
                .provider_options()
                .into_iter()
                .find(|(id, _)| id.eq_ignore_ascii_case(provider))
                .map(|(_, label)| label)
                .unwrap_or_else(|| provider.clone()),
        }
    }

    pub fn save_payload(&self) -> HashMap<String, Value> {
        let mut values = HashMap::new();
        if self.pending_default != self.initial_default && !self.pending_default.is_empty() {
            values.insert(
                MODEL_KEY.to_string(),
                Value::String(self.pending_default.clone()),
            );
        }
        if self.pending_enabled != self.initial_enabled {
            values.insert(
                CATALOG_MODE_KEY.to_string(),
                Value::String("curated".to_string()),
            );
            values.insert(
                CATALOG_ALLOWLIST_KEY.to_string(),
                Value::String(format_allowlist(&self.pending_enabled)),
            );
        }
        values
    }

    pub fn expected_readback(&self, snapshot: &CatalogSnapshot) -> CatalogExpectation {
        let model = if self.pending_default.is_empty() {
            snapshot.configured_default.clone()
        } else {
            self.pending_default.clone()
        };
        let (mode, allowlist) = if self.pending_enabled != self.initial_enabled {
            (
                "curated".to_string(),
                format_allowlist(&self.pending_enabled),
            )
        } else {
            (snapshot.catalog_mode.clone(), snapshot.allowlist.clone())
        };
        CatalogExpectation {
            model,
            mode,
            allowlist,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CatalogExpectation {
    pub model: String,
    pub mode: String,
    pub allowlist: String,
}

pub fn verify_catalog_readback(
    expected: &CatalogExpectation,
    config: &ConfigResponse,
) -> Result<(), String> {
    let model = config_field(config, MODEL_KEY);
    let mode = config_field(config, CATALOG_MODE_KEY);
    let allowlist = config_field(config, CATALOG_ALLOWLIST_KEY);
    if model != expected.model {
        return Err(format!(
            "MODEL read-back mismatch: expected {}, got {}",
            expected.model, model
        ));
    }
    if normalize_mode(&mode) != normalize_mode(&expected.mode) {
        return Err(format!(
            "MODEL_CATALOG_MODE read-back mismatch: expected {}, got {}",
            display_mode(&expected.mode),
            display_mode(&mode)
        ));
    }
    if normalize_allowlist(&allowlist) != normalize_allowlist(&expected.allowlist) {
        return Err(format!(
            "MODEL_CATALOG_ALLOWLIST read-back mismatch: expected [{}], got [{}]",
            normalize_allowlist(&expected.allowlist).join(", "),
            normalize_allowlist(&allowlist).join(", ")
        ));
    }
    Ok(())
}

pub fn normalize_allowlist(value: &str) -> Vec<String> {
    let mut entries: Vec<String> = value
        .replace('\r', "\n")
        .split([',', '\n'])
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(str::to_string)
        .collect();
    entries.sort_by_key(|left| left.to_ascii_lowercase());
    entries.dedup_by(|left, right| left.eq_ignore_ascii_case(right));
    entries
}

pub fn format_allowlist(models: &BTreeSet<String>) -> String {
    let mut entries: Vec<String> = models.iter().cloned().collect();
    entries.sort_by_key(|left| left.to_ascii_lowercase());
    entries.join(", ")
}

pub fn provider_id(model_ref: &str) -> String {
    model_ref
        .split_once('/')
        .map(|(provider, _)| provider.to_string())
        .unwrap_or_else(|| "other".to_string())
}

pub fn config_field(config: &ConfigResponse, key: &str) -> String {
    config
        .fields
        .iter()
        .find(|field| field.key == key)
        .map(|field| field.value.clone())
        .unwrap_or_default()
}

pub fn price_state(model_ref: &str, evidence: &Value) -> PriceState {
    let record = evidence.as_object();
    if let Some(explicit) = bool_field(record, "is_free") {
        return if explicit {
            PriceState::Free
        } else {
            PriceState::Paid
        };
    }
    let metadata = record.and_then(|map| map.get("catalog_metadata").and_then(Value::as_object));
    if let Some(explicit) = bool_field(metadata, "is_free") {
        return if explicit {
            PriceState::Free
        } else {
            PriceState::Paid
        };
    }
    let pricing = record
        .and_then(|map| map.get("pricing"))
        .and_then(Value::as_object)
        .or_else(|| metadata.and_then(|map| map.get("pricing").and_then(Value::as_object)));
    match pricing.and_then(pricing_is_free) {
        Some(true) => PriceState::Free,
        Some(false) => PriceState::Paid,
        None => {
            if provider_id(model_ref) == "open_router"
                && model_ref.to_ascii_lowercase().ends_with(":free")
            {
                PriceState::Free
            } else {
                PriceState::Unknown
            }
        }
    }
}

pub fn capability_summary(evidence: &Value) -> Vec<(String, String)> {
    let mut rows = Vec::new();
    let capabilities = evidence
        .get("capabilities")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    for (key, label) in [
        ("native_tools", "Tools"),
        ("vision_input", "Vision"),
        ("reasoning_effort", "Reasoning"),
        ("structured_output", "Structured"),
        ("text_output", "Text out"),
    ] {
        let state = capabilities
            .get(key)
            .and_then(Value::as_object)
            .and_then(|map| map.get("state"))
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        rows.push((label.to_string(), state.to_string()));
    }
    let metadata = evidence
        .get("catalog_metadata")
        .cloned()
        .unwrap_or(Value::Null);
    if let Some(context) = int_field(metadata.get("context_window"))
        .or_else(|| int_field(metadata.get("max_input_tokens")))
    {
        rows.push(("Context".to_string(), format_token_count(context)));
    }
    if let Some(output) = int_field(metadata.get("max_output_tokens")) {
        rows.push(("Output".to_string(), format_token_count(output)));
    }
    rows
}

pub fn pricing_signal(evidence: &Value) -> String {
    let pricing = evidence
        .get("pricing")
        .and_then(Value::as_object)
        .cloned()
        .or_else(|| {
            evidence
                .get("catalog_metadata")
                .and_then(|value| value.get("pricing"))
                .and_then(Value::as_object)
                .cloned()
        })
        .unwrap_or_default();
    if pricing.is_empty() {
        return "unknown".to_string();
    }
    let mut parts: Vec<String> = pricing
        .iter()
        .map(|(name, value)| format!("{name}={value}"))
        .collect();
    parts.sort();
    parts.join(" · ")
}

fn capability_search_tags(evidence: &Value) -> Vec<String> {
    let mut tags = Vec::new();
    if let Some(capabilities) = evidence.get("capabilities").and_then(Value::as_object) {
        for (name, body) in capabilities {
            let state = body
                .get("state")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            tags.push(name.replace('_', " "));
            tags.push(state.to_string());
            if matches!(state, "supported" | "accepted-but-unverified") {
                match name.as_str() {
                    "native_tools" | "parallel_tools" | "named_tool_choice" => {
                        tags.push("tools".to_string())
                    }
                    "vision_input" | "screenshot_vision" | "image_tool_results" => {
                        tags.push("vision".to_string())
                    }
                    "reasoning_effort" => tags.push("reasoning".to_string()),
                    _ => {}
                }
            }
        }
    }
    tags
}

fn model_inventory(models: &ModelsResponse) -> Vec<String> {
    let mut inventory = if models.catalog_models.is_empty() {
        models.models.clone()
    } else {
        models.catalog_models.clone()
    };
    for model in &models.models {
        if !inventory.iter().any(|candidate| candidate == model) {
            inventory.push(model.clone());
        }
    }
    inventory.sort_by_key(|left| left.to_ascii_lowercase());
    inventory.dedup();
    inventory
}

fn model_evidence<'a>(models: &'a ModelsResponse, model_ref: &str) -> Option<&'a Value> {
    models
        .catalog_model_evidence
        .get(model_ref)
        .or_else(|| models.model_evidence.get(model_ref))
}

fn provider_labels(models: &ModelsResponse) -> HashMap<String, String> {
    let mut labels = HashMap::new();
    for status in &models.provider_status {
        if status.provider_id.is_empty() {
            continue;
        }
        let label = if status.display_name.is_empty() {
            humanize_provider(&status.provider_id)
        } else {
            status.display_name.clone()
        };
        labels.insert(status.provider_id.clone(), label);
    }
    labels
}

fn reverse_aliases(raw: String) -> HashMap<String, Vec<String>> {
    let mut aliases: HashMap<String, Vec<String>> = HashMap::new();
    for entry in raw.replace('\r', "\n").split([',', '\n']) {
        let entry = entry.trim();
        if entry.is_empty() || !entry.contains('=') {
            continue;
        }
        let Some((alias, target)) = entry.split_once('=') else {
            continue;
        };
        let alias = alias.trim();
        let target = target.trim();
        if alias.is_empty() || target.is_empty() {
            continue;
        }
        aliases
            .entry(target.to_string())
            .or_default()
            .push(alias.to_string());
    }
    aliases
}

fn effective_enabled(
    mode: &str,
    allowlist: &str,
    known: &BTreeSet<String>,
    visible: &BTreeSet<String>,
) -> BTreeSet<String> {
    let parsed = parse_allowlist(allowlist);
    match normalize_mode(mode).as_str() {
        "all" => known.clone(),
        "curated" => known
            .iter()
            .filter(|model| allowlist_matches(&parsed, model))
            .cloned()
            .collect(),
        _ if parsed.is_empty() => visible.clone(),
        _ => known
            .iter()
            .filter(|model| allowlist_matches(&parsed, model))
            .cloned()
            .collect(),
    }
}

fn parse_allowlist(value: &str) -> BTreeSet<String> {
    normalize_allowlist(value).into_iter().collect()
}

fn allowlist_matches(allowlist: &BTreeSet<String>, model_ref: &str) -> bool {
    if allowlist.contains("*") {
        return true;
    }
    if allowlist.contains(model_ref) {
        return true;
    }
    let provider = provider_id(model_ref);
    allowlist.contains(&format!("{provider}/*"))
}

fn normalize_mode(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn display_mode(value: &str) -> &str {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        "(unset)"
    } else {
        trimmed
    }
}

fn bool_field(map: Option<&Map<String, Value>>, key: &str) -> Option<bool> {
    map.and_then(|values| values.get(key))
        .and_then(Value::as_bool)
}

fn int_field(value: Option<&Value>) -> Option<u64> {
    match value {
        Some(Value::Number(number)) => number.as_u64().or_else(|| {
            number
                .as_f64()
                .filter(|float| float.is_finite() && *float >= 0.0)
                .map(|float| float as u64)
        }),
        Some(Value::String(text)) => text.trim().parse().ok(),
        _ => None,
    }
}

fn pricing_is_free(pricing: &Map<String, Value>) -> Option<bool> {
    let mut prices: Vec<(String, f64)> = Vec::new();
    for (name, value) in pricing {
        let name = name.trim();
        if name.is_empty() {
            continue;
        }
        let price = match value {
            Value::Number(number) => number.as_f64(),
            Value::String(text) => text.trim().parse().ok(),
            _ => None,
        };
        let Some(price) = price.filter(|value| value.is_finite() && *value >= 0.0) else {
            continue;
        };
        prices.push((name.to_ascii_lowercase().replace('-', "_"), price));
    }
    if prices.is_empty() {
        return None;
    }
    let names: BTreeSet<&str> = prices.iter().map(|(name, _)| name.as_str()).collect();
    let has_input = names
        .iter()
        .any(|name| matches!(*name, "input" | "input_tokens" | "prompt" | "prompt_tokens"));
    let has_output = names.iter().any(|name| {
        matches!(
            *name,
            "completion" | "completion_tokens" | "output" | "output_tokens"
        )
    });
    if !has_input || !has_output {
        return None;
    }
    Some(prices.iter().all(|(_, price)| *price == 0.0))
}

fn humanize_provider(provider_id: &str) -> String {
    provider_id.replace('_', " ")
}

fn format_token_count(tokens: u64) -> String {
    if tokens >= 1_000_000 {
        format!("{:.2}M", tokens as f64 / 1_000_000.0)
    } else if tokens >= 1_000 {
        format!("{}K", tokens / 1_000)
    } else {
        tokens.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::{ConfigField, ModelsResponse};
    use serde_json::json;

    fn snapshot(
        models: ModelsResponse,
        default: &str,
        mode: &str,
        allowlist: &str,
    ) -> CatalogSnapshot {
        CatalogSnapshot::from_admin(
            &models,
            &ConfigResponse {
                fields: vec![
                    ConfigField {
                        key: MODEL_KEY.to_string(),
                        value: default.to_string(),
                        ..ConfigField::default()
                    },
                    ConfigField {
                        key: CATALOG_MODE_KEY.to_string(),
                        value: mode.to_string(),
                        ..ConfigField::default()
                    },
                    ConfigField {
                        key: CATALOG_ALLOWLIST_KEY.to_string(),
                        value: allowlist.to_string(),
                        ..ConfigField::default()
                    },
                    ConfigField {
                        key: ALIASES_KEY.to_string(),
                        value: "fast=open_router/provider/alpha".to_string(),
                        ..ConfigField::default()
                    },
                ],
                ..ConfigResponse::default()
            },
        )
    }

    fn catalog() -> ModelsResponse {
        ModelsResponse {
            models: vec!["open_router/provider/alpha".to_string()],
            catalog_models: vec![
                "open_router/provider/alpha".to_string(),
                "open_router/provider/beta".to_string(),
                "opencode_go/muse".to_string(),
            ],
            model_labels: [
                (
                    "open_router/provider/alpha".to_string(),
                    "Alpha".to_string(),
                ),
                ("open_router/provider/beta".to_string(), "Beta".to_string()),
                ("opencode_go/muse".to_string(), "Muse".to_string()),
            ]
            .into_iter()
            .collect(),
            catalog_model_labels: [
                (
                    "open_router/provider/alpha".to_string(),
                    "Alpha".to_string(),
                ),
                ("open_router/provider/beta".to_string(), "Beta".to_string()),
                ("opencode_go/muse".to_string(), "Muse".to_string()),
            ]
            .into_iter()
            .collect(),
            catalog_model_evidence: [
                (
                    "open_router/provider/alpha".to_string(),
                    json!({
                        "is_free": true,
                        "capabilities": {
                            "native_tools": {"state": "supported"},
                            "vision_input": {"state": "unsupported"}
                        },
                        "catalog_metadata": {"context_window": 128000, "max_output_tokens": 16000}
                    }),
                ),
                (
                    "open_router/provider/beta".to_string(),
                    json!({"is_free": false}),
                ),
                (
                    "opencode_go/muse".to_string(),
                    json!({"is_free": null, "pricing": {}}),
                ),
            ]
            .into_iter()
            .collect(),
            ..ModelsResponse::default()
        }
    }

    #[test]
    fn instant_filter_matches_provider_name_capability_and_price() {
        let snapshot = snapshot(
            catalog(),
            "open_router/provider/alpha",
            "curated",
            "open_router/provider/alpha",
        );
        let mut browser = ModelBrowser::default();
        browser.sync(&snapshot);

        browser.query = "tools".to_string();
        assert_eq!(
            browser.filtered_refs(&snapshot),
            ["open_router/provider/alpha"]
        );

        browser.query = "muse".to_string();
        assert_eq!(browser.filtered_refs(&snapshot), ["opencode_go/muse"]);

        browser.query = String::new();
        browser.price_filter = PriceFilter::Free;
        assert_eq!(
            browser.filtered_refs(&snapshot),
            ["open_router/provider/alpha"]
        );

        browser.price_filter = PriceFilter::All;
        browser.access_filter = AccessFilter::Blocked;
        assert_eq!(
            browser.filtered_refs(&snapshot),
            ["open_router/provider/beta", "opencode_go/muse"]
        );
    }

    #[test]
    fn provider_groups_and_free_first_sort_help_humans_browse() {
        let snapshot = snapshot(
            catalog(),
            "open_router/provider/alpha",
            "curated",
            "open_router/provider/alpha",
        );
        let mut browser = ModelBrowser::default();
        browser.sync(&snapshot);

        browser.sort = ModelSort::Provider;
        assert_eq!(
            browser.filtered_refs(&snapshot),
            [
                "open_router/provider/alpha",
                "open_router/provider/beta",
                "opencode_go/muse"
            ]
        );

        browser.sort = ModelSort::FreeFirst;
        assert_eq!(
            browser.filtered_refs(&snapshot)[0],
            "open_router/provider/alpha"
        );
    }

    #[test]
    fn making_default_enables_blocked_model_without_writing_until_save() {
        let snapshot = snapshot(
            catalog(),
            "open_router/provider/alpha",
            "curated",
            "open_router/provider/alpha",
        );
        let mut browser = ModelBrowser::default();
        browser.sync(&snapshot);

        browser
            .make_default("open_router/provider/beta", &snapshot)
            .unwrap();
        assert!(browser.is_enabled("open_router/provider/beta"));
        assert!(browser.is_default("open_router/provider/beta"));
        assert!(browser.dirty());

        let payload = browser.save_payload();
        assert_eq!(
            payload.get(MODEL_KEY),
            Some(&Value::String("open_router/provider/beta".to_string()))
        );
        assert_eq!(
            payload.get(CATALOG_MODE_KEY),
            Some(&Value::String("curated".to_string()))
        );
        assert_eq!(
            normalize_allowlist(payload[CATALOG_ALLOWLIST_KEY].as_str().unwrap()),
            [
                "open_router/provider/alpha".to_string(),
                "open_router/provider/beta".to_string()
            ]
        );
    }

    #[test]
    fn disabling_default_hands_status_to_another_model() {
        let snapshot = snapshot(
            catalog(),
            "open_router/provider/alpha",
            "curated",
            "open_router/provider/alpha, open_router/provider/beta",
        );
        let mut browser = ModelBrowser::default();
        browser.sync(&snapshot);
        browser
            .toggle_access("open_router/provider/alpha", &snapshot)
            .unwrap();
        assert!(!browser.is_enabled("open_router/provider/alpha"));
        assert_eq!(browser.pending_default(), "open_router/provider/beta");
        assert!(browser.is_enabled("open_router/provider/beta"));
    }

    #[test]
    fn unavailable_configured_default_is_never_silently_replaced() {
        let snapshot = snapshot(
            catalog(),
            "gateway/missing",
            "curated",
            "open_router/provider/alpha",
        );
        let mut browser = ModelBrowser::default();
        browser.sync(&snapshot);
        assert_eq!(browser.pending_default(), "gateway/missing");
        assert!(browser.default_unavailable(&snapshot));
        assert!(!browser.dirty());
        assert_eq!(
            browser.filtered_refs(&snapshot)[0],
            "open_router/provider/alpha"
        );
    }

    #[test]
    fn allowlist_readback_ignores_formatting_and_order() {
        let expected = CatalogExpectation {
            model: "open_router/provider/alpha".to_string(),
            mode: "curated".to_string(),
            allowlist: "open_router/provider/beta, open_router/provider/alpha".to_string(),
        };
        let config = ConfigResponse {
            fields: vec![
                ConfigField {
                    key: MODEL_KEY.to_string(),
                    value: "open_router/provider/alpha".to_string(),
                    ..ConfigField::default()
                },
                ConfigField {
                    key: CATALOG_MODE_KEY.to_string(),
                    value: "curated".to_string(),
                    ..ConfigField::default()
                },
                ConfigField {
                    key: CATALOG_ALLOWLIST_KEY.to_string(),
                    value: "open_router/provider/alpha\nopen_router/provider/beta".to_string(),
                    ..ConfigField::default()
                },
            ],
            ..ConfigResponse::default()
        };
        verify_catalog_readback(&expected, &config).unwrap();
    }

    #[test]
    fn alias_and_capability_inspector_fields_are_derived_from_snapshot() {
        let snapshot = snapshot(
            catalog(),
            "open_router/provider/alpha",
            "curated",
            "open_router/provider/alpha",
        );
        assert_eq!(snapshot.aliases_for("open_router/provider/alpha"), ["fast"]);
        let record = snapshot.record("open_router/provider/alpha").unwrap();
        let summary = capability_summary(&record.evidence);
        assert!(summary
            .iter()
            .any(|(label, state)| label == "Tools" && state == "supported"));
        assert!(summary
            .iter()
            .any(|(label, value)| label == "Context" && value == "128K"));
    }
}
