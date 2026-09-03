use anyhow::{bail, Context, Result};
use reqwest::blocking::{Client, Response};
use reqwest::{Method, Url};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::net::IpAddr;
use std::str::FromStr;
use std::time::Duration;

pub const MASKED_SECRET: &str = "********";

#[derive(Clone)]
pub struct AdminClient {
    root: Url,
    http: Client,
    health_http: Client,
    expected_mode: String,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize, Default)]
pub struct ConfigResponse {
    #[serde(default)]
    pub sections: Vec<ConfigSection>,
    #[serde(default)]
    pub fields: Vec<ConfigField>,
    #[serde(default)]
    pub provider_status: Vec<ProviderStatus>,
    #[serde(default)]
    pub paths: HashMap<String, Value>,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize, Default)]
pub struct ConfigSection {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub advanced: bool,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct ConfigField {
    #[serde(default)]
    pub key: String,
    #[serde(default)]
    pub label: String,
    #[allow(dead_code)]
    #[serde(default, rename = "section")]
    pub section_id: String,
    #[serde(default, rename = "type")]
    pub field_type: String,
    #[serde(default)]
    pub value: String,
    #[serde(default)]
    pub configured: bool,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub locked: bool,
    #[serde(default)]
    pub secret: bool,
    #[serde(default)]
    pub advanced: bool,
    #[serde(default)]
    pub restart_required: bool,
    #[serde(default)]
    pub session_sensitive: bool,
    #[serde(default)]
    pub options: Vec<ConfigOption>,
    #[serde(default)]
    pub description: String,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct ConfigOption {
    #[serde(default)]
    pub value: String,
    #[serde(default)]
    pub label: String,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct ProviderStatus {
    #[serde(default)]
    pub provider_id: String,
    #[serde(default)]
    pub display_name: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub base_url: String,
    #[serde(default)]
    pub configuration: String,
    #[serde(default)]
    pub custom: bool,
    #[serde(default)]
    pub api_key_configured: Option<bool>,
    #[serde(default)]
    pub proxy_configured: Option<bool>,
    #[serde(default)]
    pub model_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ServerIdentity {
    #[serde(default)]
    pub service: String,
    #[serde(default)]
    pub protocol: u32,
    #[serde(default)]
    pub instance_id: String,
    #[serde(default)]
    pub pid: u32,
    #[serde(default)]
    pub mode: String,
    #[serde(default)]
    pub lifecycle: String,
    #[serde(default)]
    pub started_at: String,
    #[serde(default)]
    pub uptime_seconds: f64,
    #[serde(default)]
    pub host: String,
    #[serde(default)]
    pub port: u16,
    #[serde(default)]
    pub health_url: String,
    #[serde(default)]
    pub admin_url: String,
    #[serde(default)]
    pub config_dir: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub version: String,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct ProviderCollection {
    #[serde(default)]
    pub providers: Vec<ProviderStatus>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct CustomProviderCollection {
    #[serde(default)]
    pub providers: Vec<CustomProvider>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct CustomProvider {
    #[serde(default)]
    pub provider_id: String,
    #[serde(default)]
    pub display_name: String,
    #[serde(default)]
    pub base_url: String,
    #[serde(default)]
    pub local: bool,
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub api_key_configured: bool,
    #[serde(default)]
    pub proxy_configured: bool,
    #[serde(default)]
    pub model_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct CustomProviderPayload {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub base_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub api_key: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub proxy: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub local: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub models: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct RepositoriesResponse {
    #[serde(default)]
    pub repositories: Vec<Repository>,
    #[serde(default)]
    pub selected_path: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Repository {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub branch: String,
    #[serde(default)]
    pub remote: String,
    #[serde(default)]
    pub display_path: String,
    #[serde(default)]
    pub identity: String,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct RepositorySelectionResponse {
    #[serde(default)]
    pub repository: Repository,
    #[serde(default)]
    pub persisted: bool,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize, Default)]
pub struct ModelsResponse {
    #[serde(default)]
    pub models: Vec<String>,
    #[serde(default)]
    pub model_labels: HashMap<String, String>,
    #[serde(default)]
    pub provider_status: Vec<ProviderStatus>,
    #[serde(default)]
    pub failed_providers: Vec<String>,
    #[serde(default)]
    pub model_evidence: HashMap<String, Value>,
    #[serde(default)]
    pub catalog_models: Vec<String>,
    #[serde(default)]
    pub catalog_model_labels: HashMap<String, String>,
    #[serde(default)]
    pub catalog_model_evidence: HashMap<String, Value>,
    /// Exact ids advertised by the Claude-compatible `/v1/models` endpoint.
    /// The editable catalog remains keyed by raw provider/model refs above.
    #[serde(default)]
    pub claude_models: Vec<String>,
    #[serde(default)]
    pub claude_model_labels: HashMap<String, String>,
}

/// Server state prepared before the HTTP server is started.
///
/// The bootstrap file contains only Admin-safe metadata. Secrets remain in the
/// managed config file and can only enter the separate, permission-restricted
/// result file through an explicit field edit.
#[derive(Debug, Clone, Deserialize, Default)]
pub struct BootstrapState {
    #[serde(default)]
    pub config: ConfigResponse,
    #[serde(default)]
    pub models: ModelsResponse,
    #[serde(default)]
    pub status: Value,
    #[serde(default)]
    pub custom_providers: Vec<CustomProvider>,
    #[serde(default)]
    pub local_status: Vec<ProviderStatus>,
    #[serde(default)]
    pub usage: Value,
    #[serde(default)]
    pub diagnostic: Value,
    #[serde(default)]
    pub repositories: RepositoriesResponse,
    /// Direct Claude launches use the repository action as the final handoff.
    #[serde(default)]
    pub launch_after_repository: bool,
    /// Preserve the requested normal/danger Claude mode across server startup.
    #[serde(default)]
    pub launch_danger: bool,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize, Default)]
pub struct ApplyResponse {
    #[serde(default)]
    pub valid: bool,
    #[serde(default)]
    pub applied: bool,
    #[serde(default)]
    pub errors: Vec<String>,
    #[serde(default)]
    pub pending_fields: Vec<String>,
    #[serde(default)]
    pub restart: Value,
    #[serde(default)]
    pub path: String,
}

impl AdminClient {
    pub fn new(base_url: &str) -> Result<Self> {
        let normalized = format!("{}/", base_url.trim().trim_end_matches('/'));
        let root = Url::parse(&normalized).context("invalid FCC server URL")?;
        if root.scheme() != "http" && root.scheme() != "https" {
            bail!("FCC Admin URL must use http or https");
        }
        let host = root.host_str().context("FCC Admin URL is missing a host")?;
        let loopback = host.eq_ignore_ascii_case("localhost")
            || IpAddr::from_str(host)
                .map(|ip| ip.is_loopback())
                .unwrap_or(false);
        if !loopback {
            bail!("FCC Admin client only connects to loopback hosts");
        }
        let http = Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .context("could not create FCC Admin HTTP client")?;
        let health_http = Client::builder()
            .timeout(Duration::from_millis(900))
            .build()
            .context("could not create FCC health HTTP client")?;
        Ok(Self {
            root,
            http,
            health_http,
            expected_mode: "standard".to_string(),
        })
    }

    pub fn with_expected_mode(mut self, expected_mode: impl Into<String>) -> Self {
        self.expected_mode = expected_mode.into();
        self
    }

    pub fn config(&self) -> Result<ConfigResponse> {
        self.get("admin/api/config")
    }

    pub fn status(&self) -> Result<Value> {
        self.get("admin/api/status")
    }

    pub fn health(&self) -> Result<ServerIdentity> {
        let url = self
            .root
            .join("health")
            .context("could not construct FCC health URL")?;
        let response = self
            .health_http
            .get(url)
            .header("Accept", "application/json")
            .send()
            .context("FCC health request failed")?;
        let identity: ServerIdentity = decode_response(response)?;
        validate_expected_mode(identity, &self.expected_mode)
    }

    pub fn models(&self) -> Result<ModelsResponse> {
        self.get("admin/api/models")
    }

    pub fn refresh_models(&self) -> Result<ModelsResponse> {
        self.request(Method::POST, "admin/api/models/refresh", None)
    }

    pub fn usage(&self, days: u16) -> Result<Value> {
        if !(1..=366).contains(&days) {
            bail!("usage range must be between 1 and 366 days");
        }
        self.get(&format!("admin/api/usage?days={days}"))
    }

    pub fn local_provider_status(&self) -> Result<ProviderCollection> {
        self.get("admin/api/providers/local-status")
    }

    pub fn custom_providers(&self) -> Result<CustomProviderCollection> {
        self.get("admin/api/custom-providers")
    }

    pub fn repositories(&self, refresh: bool) -> Result<RepositoriesResponse> {
        let path = if refresh {
            "admin/api/repositories?refresh=true"
        } else {
            "admin/api/repositories"
        };
        self.get(path)
    }

    pub fn select_repository(&self, path: &str) -> Result<RepositorySelectionResponse> {
        self.post("admin/api/repositories/select", &json!({ "path": path }))
    }

    pub fn apply_field(&self, key: &str, value: Value) -> Result<ApplyResponse> {
        let mut values = HashMap::new();
        values.insert(key.to_string(), value);
        self.apply_fields(values)
    }

    pub fn apply_fields(&self, values: HashMap<String, Value>) -> Result<ApplyResponse> {
        let payload = json!({ "values": values });
        let validation: ApplyResponse = self.post("admin/api/config/validate", &payload)?;
        if !validation.valid {
            return Ok(validation);
        }
        self.post("admin/api/config/apply", &payload)
    }

    pub fn test_provider(&self, provider_id: &str) -> Result<Value> {
        let id = safe_path_id(provider_id)?;
        self.request(
            Method::POST,
            &format!("admin/api/providers/{id}/test"),
            None,
        )
    }

    pub fn add_custom_provider(&self, payload: &CustomProviderPayload) -> Result<Value> {
        self.post("admin/api/custom-providers", payload)
    }

    pub fn update_custom_provider(
        &self,
        provider_id: &str,
        payload: &CustomProviderPayload,
    ) -> Result<Value> {
        let id = safe_path_id(provider_id)?;
        self.put(&format!("admin/api/custom-providers/{id}"), payload)
    }

    pub fn remove_custom_provider(&self, provider_id: &str) -> Result<Value> {
        let id = safe_path_id(provider_id)?;
        self.request(
            Method::DELETE,
            &format!("admin/api/custom-providers/{id}"),
            None,
        )
    }

    #[allow(dead_code)]
    pub fn connected_account_status(&self, provider_id: &str) -> Result<Value> {
        let id = safe_path_id(provider_id)?;
        self.get(&format!("admin/api/providers/{id}/auth"))
    }

    pub fn connected_account_login(&self, provider_id: &str, mode: &str) -> Result<Value> {
        let id = safe_path_id(provider_id)?;
        self.post(
            &format!("admin/api/providers/{id}/auth/login"),
            &json!({ "mode": mode }),
        )
    }

    #[allow(dead_code)]
    pub fn connected_account_cancel(&self, provider_id: &str) -> Result<Value> {
        let id = safe_path_id(provider_id)?;
        self.request(
            Method::POST,
            &format!("admin/api/providers/{id}/auth/cancel"),
            None,
        )
    }

    pub fn connected_account_disconnect(&self, provider_id: &str) -> Result<Value> {
        let id = safe_path_id(provider_id)?;
        self.request(
            Method::DELETE,
            &format!("admin/api/providers/{id}/auth"),
            None,
        )
    }

    pub fn route_diagnostic(&self, model: Option<&str>) -> Result<Value> {
        let mut payload = json!({ "shapes": ["text"], "mode": "strict" });
        if let Some(model) = model {
            payload["model"] = Value::String(model.to_string());
        }
        self.post("admin/api/diagnostics/route", &payload)
    }

    fn get<T: DeserializeOwned>(&self, path: &str) -> Result<T> {
        self.request(Method::GET, path, None)
    }

    fn post<T: DeserializeOwned, B: Serialize + ?Sized>(&self, path: &str, body: &B) -> Result<T> {
        let value = serde_json::to_value(body).context("could not encode FCC Admin request")?;
        self.request(Method::POST, path, Some(&value))
    }

    fn put<T: DeserializeOwned, B: Serialize + ?Sized>(&self, path: &str, body: &B) -> Result<T> {
        let value = serde_json::to_value(body).context("could not encode FCC Admin request")?;
        self.request(Method::PUT, path, Some(&value))
    }

    fn request<T: DeserializeOwned>(
        &self,
        method: Method,
        path: &str,
        body: Option<&Value>,
    ) -> Result<T> {
        let url = self
            .root
            .join(path.trim_start_matches('/'))
            .context("could not construct FCC Admin URL")?;
        let mut request = self
            .http
            .request(method, url)
            .header("Accept", "application/json")
            .header("Content-Type", "application/json");
        if let Some(body) = body {
            request = request.json(body);
        }
        let response = request.send().context("FCC Admin request failed")?;
        decode_response(response)
    }
}

fn validate_expected_mode(identity: ServerIdentity, expected_mode: &str) -> Result<ServerIdentity> {
    if identity.mode != expected_mode {
        bail!(
            "FCC health identity mode mismatch: expected {:?}, found {:?}",
            expected_mode,
            identity.mode
        );
    }
    Ok(identity)
}

fn decode_response<T: DeserializeOwned>(response: Response) -> Result<T> {
    let status = response.status();
    if !status.is_success() {
        let detail = response
            .json::<Value>()
            .ok()
            .and_then(|value| value.get("detail").cloned())
            .and_then(|value| value.as_str().map(str::to_owned));
        if let Some(detail) = detail {
            bail!("FCC Admin returned HTTP {status}: {detail}");
        }
        bail!("FCC Admin returned HTTP {status}");
    }
    response
        .json::<T>()
        .context("FCC Admin response was not valid JSON")
}

fn safe_path_id(value: &str) -> Result<&str> {
    if value.is_empty()
        || !value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "._-".contains(character))
    {
        bail!("provider id is not safe for an Admin API path");
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn health_identity_mode_mismatch_is_rejected() {
        let identity = ServerIdentity {
            mode: "sandbox".to_string(),
            ..ServerIdentity::default()
        };

        let error = validate_expected_mode(identity, "standard").unwrap_err();

        assert!(error.to_string().contains("mode mismatch"));
        assert!(error.to_string().contains("sandbox"));
    }

    #[test]
    fn admin_client_rejects_non_loopback_hosts() {
        assert!(AdminClient::new("https://example.com:8082").is_err());
        assert!(AdminClient::new("http://127.0.0.1:8082").is_ok());
        assert!(AdminClient::new("http://localhost:8082").is_ok());
    }

    #[test]
    fn custom_provider_payload_can_preserve_existing_secret() {
        let payload = CustomProviderPayload {
            id: None,
            display_name: Some("Local Lab".to_string()),
            base_url: Some("http://127.0.0.1:1234/v1".to_string()),
            api_key: None,
            proxy: None,
            local: Some(true),
            models: Some(vec!["model-a".to_string()]),
            enabled: Some(true),
        };
        let value = serde_json::to_value(payload).unwrap();
        assert!(value.get("api_key").is_none());
        assert!(value.get("proxy").is_none());
    }

    #[test]
    fn apply_fields_sends_a_batch_payload_shape() {
        let values = HashMap::from([
            ("MODEL".to_string(), json!("provider/free")),
            ("MODEL_CATALOG_MODE".to_string(), json!("curated")),
        ]);
        let payload = json!({ "values": values });
        assert_eq!(payload["values"]["MODEL"], "provider/free");
        assert_eq!(payload["values"]["MODEL_CATALOG_MODE"], "curated");
    }

    #[test]
    fn models_response_keeps_visible_and_full_catalog_metadata() {
        let response: ModelsResponse = serde_json::from_value(json!({
            "models": ["provider/free"],
            "catalog_models": ["provider/free", "provider/hidden"],
            "model_labels": {"provider/free": "Free"},
            "catalog_model_labels": {"provider/hidden": "Hidden"},
            "catalog_model_evidence": {
                "provider/free": {"is_free": true},
                "provider/hidden": {"is_free": true}
            },
            "claude_models": ["anthropic/provider/free"],
            "claude_model_labels": {"anthropic/provider/free": "Free"},
            "failed_providers": ["provider-down"]
        }))
        .unwrap();

        assert_eq!(response.models, vec!["provider/free"]);
        assert_eq!(response.catalog_models.len(), 2);
        assert_eq!(response.catalog_model_labels["provider/hidden"], "Hidden");
        assert_eq!(response.claude_models, vec!["anthropic/provider/free"]);
        assert_eq!(
            response.claude_model_labels["anthropic/provider/free"],
            "Free"
        );
        assert_eq!(response.failed_providers, vec!["provider-down"]);
    }

    #[test]
    fn provider_status_accepts_server_inventory_without_secret_flags() {
        let status: ProviderStatus = serde_json::from_value(json!({
            "provider_id": "open_router",
            "display_name": "OpenRouter",
            "kind": "remote",
            "status": "configured"
        }))
        .unwrap();

        assert_eq!(status.provider_id, "open_router");
        assert_eq!(status.api_key_configured, None);
        assert_eq!(status.proxy_configured, None);
    }
}
