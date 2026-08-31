const state = {
  config: null,
  fields: new Map(),
  localStatus: new Map(),
  modelOptions: [],
  modelLabels: {},
  modelEvidence: {},
  modelComboboxes: new Set(),
  authPollers: new Map(),
  customProviders: [],
  customProviderEditingId: null,
  toolAccounts: null,
  activeView: "providers",
  usageDays: 30,
  selectedModelField: "MODEL",
};

const MASKED_SECRET = "********";
const MODEL_EVIDENCE_LABELS = {
  text_input: "Text input",
  text_output: "Text output",
  native_tools: "Native tools",
  parallel_tools: "Parallel tools",
  named_tool_choice: "Named tool choice",
  reasoning_effort: "Reasoning effort",
  structured_output: "Structured output",
  vision_input: "Vision input",
  image_tool_results: "Image tool results",
  screenshot_vision: "Screenshot vision",
};
const VIEW_GROUPS = [
  {
    id: "providers",
    label: "Providers",
    title: "Providers",
    sections: ["providers", "runtime"],
    containerId: "providersSections",
  },
  {
    id: "model_config",
    label: "Model Config",
    title: "Model Config",
    sections: ["models", "reasoning", "web_tools"],
    containerId: "modelConfigSections",
  },
  {
    id: "accounts",
    label: "Accounts",
    title: "Accounts",
    sections: [],
    containerId: null,
  },
  {
    id: "usage",
    label: "Usage",
    title: "Usage",
    sections: [],
    containerId: null,
  },
  {
    id: "reviewer",
    label: "Reviewers",
    title: "Reviewers",
    sections: [],
    containerId: null,
  },
  {
    id: "messaging",
    label: "Messaging",
    title: "Messaging",
    sections: ["messaging", "voice"],
    containerId: "messagingSections",
  },
];

const byId = (id) => document.getElementById(id);

function sourceLabel(source) {
  const labels = {
    default: "default",
    template: "template",
    repo_env: "repo .env",
    managed_env: "",
    explicit_env_file: "FCC_ENV_FILE",
    process: "process env",
  };
  return Object.prototype.hasOwnProperty.call(labels, source) ? labels[source] : source;
}

function sourceText(field) {
  const parts = [];
  const label = sourceLabel(field.source);
  if (label) {
    parts.push(label);
  }
  if (field.locked) {
    parts.push("locked");
  }
  return parts.join(" ");
}

function statusClass(status) {
  if (["configured", "reachable", "running", "connected"].includes(status)) return "ok";
  if (["missing_key", "missing_config", "missing_url", "unknown", "connecting"].includes(status)) return "warn";
  if (["offline", "error"].includes(status)) return "error";
  return "neutral";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : "";
    } catch {
      // The status remains useful when an upstream proxy returns a non-JSON page.
    }
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function load() {
  showMessage("Loading admin config");
  const config = await api("/admin/api/config");
  state.config = config;
  state.fields = new Map(config.fields.map((field) => [field.key, field]));
  renderNav();
  renderProviders(config.provider_status);
  await loadCustomProviders();
  renderSections(config.sections, config.fields);
  byId("configPath").textContent = config.paths.managed;
  await refreshConnectedAccounts();
  await refreshToolAccounts();
  await hydrateModelOptions();
  await loadUsage();
  await loadReviewer();
  await validate(false);
  await refreshLocalStatus();
  updateDirtyState();
  showMessage("");
}

function renderNav() {
  const nav = byId("sectionNav");
  nav.innerHTML = "";
  VIEW_GROUPS.forEach((view, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `nav-link${index === 0 ? " active" : ""}`;
    button.dataset.view = view.id;
    button.textContent = view.label;
    if (index === 0) {
      button.setAttribute("aria-current", "page");
    }
    button.addEventListener("click", () => {
      setActiveView(view.id, { scroll: true });
    });
    nav.appendChild(button);
  });
  setActiveView(state.activeView, { scroll: false });
}

function setActiveView(viewId, { scroll = false } = {}) {
  const activeView =
    VIEW_GROUPS.find((view) => view.id === viewId) || VIEW_GROUPS[0];
  state.activeView = activeView.id;
  byId("pageTitle").textContent = activeView.title;

  document.querySelectorAll(".nav-link").forEach((link) => {
    const selected = link.dataset.view === activeView.id;
    link.classList.toggle("active", selected);
    if (selected) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });

  document.querySelectorAll(".admin-view").forEach((view) => {
    const selected = view.dataset.view === activeView.id;
    view.classList.toggle("active", selected);
    view.hidden = !selected;
  });

  if (scroll) {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function renderProviders(providerStatus) {
  const grid = byId("providerGrid");
  grid.innerHTML = "";
  providerStatus
    .filter(
      (provider) => !provider.custom && provider.kind !== "connected_account",
    )
    .forEach((provider) => {
      const card = document.createElement("article");
      card.className = "provider-card";
      card.dataset.provider = provider.provider_id;

      const title = document.createElement("div");
      title.className = "provider-title";
      title.innerHTML = `<strong>${provider.display_name || provider.provider_id}</strong>`;

      const pill = document.createElement("span");
      pill.className = `status-pill ${statusClass(provider.status)}`;
      pill.textContent = provider.label;
      title.appendChild(pill);

      const meta = document.createElement("div");
      meta.className = "provider-meta";
      meta.textContent =
        provider.kind === "local"
          ? provider.base_url || "No local URL configured"
          : provider.configuration;

      const button = document.createElement("button");
      button.type = "button";
      button.className = "test-button";
      button.textContent = provider.kind === "local" ? "Test" : "Refresh models";
      button.addEventListener("click", () => testProvider(provider.provider_id, button));

      card.append(title, meta, button);
      grid.appendChild(card);
    });
}

function renderCustomProviders() {
  const grid = byId("customProviderGrid");
  const empty = byId("customProviderEmptyState");
  grid.innerHTML = "";
  empty.hidden = state.customProviders.length > 0;
  state.customProviders.forEach((provider) => {
    const card = document.createElement("article");
    card.className = "provider-card";
    card.dataset.provider = provider.provider_id;

    const title = document.createElement("div");
    title.className = "provider-title";
    const name = document.createElement("strong");
    name.textContent = provider.display_name || provider.provider_id;
    const pill = document.createElement("span");
    pill.className = `status-pill ${statusClass(provider.status)}`;
    pill.textContent = provider.label || provider.status;
    title.append(name, pill);

    const meta = document.createElement("div");
    meta.className = "provider-meta";
    const modelCount = (provider.model_ids || []).length;
    meta.textContent = `${provider.base_url} · ${modelCount} explicit model${modelCount === 1 ? "" : "s"}${provider.api_key_configured ? " · key set" : " · no key"}`;

    const actions = document.createElement("div");
    actions.className = "provider-actions";
    actions.appendChild(
      authButton("Test", (button) => testProvider(provider.provider_id, button)),
    );
    actions.appendChild(
      authButton("Edit", () => showCustomProviderEditor(provider), "secondary-button"),
    );
    actions.appendChild(
      authButton(
        provider.enabled ? "Disable" : "Enable",
        () => toggleCustomProvider(provider),
        "secondary-button",
      ),
    );
    actions.appendChild(
      authButton("Remove", () => removeCustomProvider(provider), "secondary-button"),
    );
    card.append(title, meta, actions);
    grid.appendChild(card);
  });
}

async function loadCustomProviders() {
  try {
    const result = await api("/admin/api/custom-providers");
    state.customProviders = result.providers || [];
  } catch (error) {
    state.customProviders = [];
    showMessage(error.message, true);
  }
  renderCustomProviders();
}

function showCustomProviderEditor(provider = null) {
  const form = byId("customProviderForm");
  state.customProviderEditingId = provider?.provider_id || null;
  byId("customProviderFormTitle").textContent = provider
    ? `Edit ${provider.display_name || provider.provider_id}`
    : "Add custom provider";
  byId("customProviderId").value = provider?.provider_id || "";
  byId("customProviderId").disabled = Boolean(provider);
  byId("customProviderName").value = provider?.display_name || "";
  byId("customProviderBaseUrl").value = provider?.base_url || "";
  byId("customProviderApiKey").value = "";
  byId("customProviderApiKey").placeholder = provider?.api_key_configured
    ? "Configured - enter a new value to replace"
    : "Required for remote endpoints";
  byId("customProviderProxy").value = "";
  byId("customProviderModels").value = (provider?.model_ids || []).join(", ");
  byId("customProviderLocal").checked = Boolean(provider?.local);
  form.hidden = false;
  byId("customProviderName").focus();
}

function hideCustomProviderEditor() {
  state.customProviderEditingId = null;
  byId("customProviderForm").hidden = true;
}

async function saveCustomProvider(event) {
  event.preventDefault();
  try {
    const providerId = byId("customProviderId").value.trim();
    const payload = {
      id: providerId,
      display_name: byId("customProviderName").value.trim(),
      base_url: byId("customProviderBaseUrl").value.trim(),
      proxy: byId("customProviderProxy").value.trim(),
      local: byId("customProviderLocal").checked,
      models: byId("customProviderModels").value
        .split(",")
        .map((model) => model.trim())
        .filter(Boolean),
    };
    const key = byId("customProviderApiKey").value;
    if (key) payload.api_key = key;
    const editingId = state.customProviderEditingId;
    const path = editingId
      ? `/admin/api/custom-providers/${encodeURIComponent(editingId)}`
      : "/admin/api/custom-providers";
    const result = await api(path, {
      method: editingId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    if (!result.applied) {
      showMessage((result.errors || ["Could not save provider"]).join("; "), true);
      return;
    }
    hideCustomProviderEditor();
    await loadCustomProviders();
    await hydrateModelOptions();
    showMessage("Custom provider saved. Restart fcc-server to use it.", "ok");
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function toggleCustomProvider(provider) {
  try {
    const result = await api(`/admin/api/custom-providers/${encodeURIComponent(provider.provider_id)}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: !provider.enabled }),
    });
    if (!result.applied) {
      showMessage((result.errors || ["Could not update provider"]).join("; "), true);
      return;
    }
    await loadCustomProviders();
    showMessage("Custom provider state saved. Restart fcc-server to use it.", "ok");
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function removeCustomProvider(provider) {
  if (!window.confirm(`Remove custom provider ${provider.display_name || provider.provider_id}?`)) return;
  try {
    const result = await api(`/admin/api/custom-providers/${encodeURIComponent(provider.provider_id)}`, {
      method: "DELETE",
    });
    if (!result.applied) {
      showMessage((result.errors || ["Could not remove provider"]).join("; "), true);
      return;
    }
    await loadCustomProviders();
    await hydrateModelOptions();
    showMessage("Custom provider removed. Restart fcc-server to use the updated registry.", "ok");
  } catch (error) {
    showMessage(error.message, true);
  }
}

function renderConnectedAccountCard(provider, status = provider) {
  const card = document.createElement("article");
  card.className = "provider-card";
  card.dataset.provider = provider.provider_id;
  card.dataset.connectedAccount = "true";
  card.dataset.accountSurface = "fcc-provider";

  const title = document.createElement("div");
  title.className = "provider-title";
  const name = document.createElement("strong");
  name.textContent = "FCC Provider Account";
  const pill = document.createElement("span");
  pill.className = `status-pill ${statusClass(status.state || status.status)}`;
  pill.textContent = connectedAccountLabel(status);
  title.append(name, pill);

  const meta = document.createElement("div");
  meta.className = "provider-meta";
  meta.textContent = connectedAccountMeta(status);

  const actions = document.createElement("div");
  actions.className = "provider-actions";
  populateConnectedAccountActions(provider, status, actions);
  card.append(title, meta, actions);
  return card;
}

function connectedAccountLabel(status) {
  const labels = {
    disconnected: "Not connected",
    connecting: "Connecting",
    connected: "Connected",
    error: "Needs attention",
  };
  return labels[status.state] || status.label || "Not connected";
}

function connectedAccountMeta(status) {
  if (status.connected) {
    const identity = status.email || "Account connected";
    const models = Number.isInteger(status.model_count)
      ? `${status.model_count} model${status.model_count === 1 ? "" : "s"} available. `
      : "";
    const error = status.message ? `${status.message} ` : "";
    return `${identity}. ${models}${error}Stored only in ~/.fcc/auth/openai.json. Restart your agent to refresh its model picker.`;
  }
  if (status.mode === "device" && status.user_code) {
    return `Enter code ${status.user_code} at ${status.verification_url}`;
  }
  if (status.state === "connecting") {
    return "Finish signing in, then return to this page.";
  }
  return status.message || "Sign in to FCC's OpenAI provider account. This does not sign in or switch Codex tool accounts.";
}

function populateConnectedAccountActions(provider, status, actions) {
  const providerId = provider.provider_id;
  if (status.state === "connecting") {
    const target = status.authorization_url || status.verification_url;
    if (target) {
      actions.appendChild(authButton("Open sign-in", () => window.open(target, "_blank", "noopener")));
    }
    if (status.mode === "device" && status.user_code) {
      actions.appendChild(
        authButton(
          "Copy code",
          () => copyDeviceCode(status.user_code),
          "secondary-button",
        ),
      );
    }
    actions.appendChild(
      authButton("Cancel", () => cancelConnectedAccountLogin(providerId), "secondary-button"),
    );
    return;
  }
  if (status.connected) {
    actions.appendChild(
      authButton(
        "Reconnect",
        (button) => startConnectedAccountLogin(providerId, "browser", button),
      ),
    );
    actions.appendChild(
      authButton(
        "Disconnect",
        () => disconnectConnectedAccount(providerId),
        "secondary-button",
      ),
    );
    return;
  }
  actions.appendChild(
    authButton("Sign in", (button) => startConnectedAccountLogin(providerId, "browser", button)),
    authButton(
      "Use device code",
      (button) => startConnectedAccountLogin(providerId, "device", button),
      "secondary-button",
    ),
  );
}

function authButton(label, action, className = "test-button") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", () => action(button));
  return button;
}

async function refreshConnectedAccounts() {
  const providers = (state.config?.provider_status || []).filter(
    (provider) => provider.kind === "connected_account",
  );
  const grid = byId("connectedAccountGrid");
  await Promise.all(
    providers.map(async (provider) => {
      const current = [...grid.querySelectorAll("[data-connected-account]")].find(
        (card) => card.dataset.provider === provider.provider_id,
      );
      if (!current) grid.appendChild(renderConnectedAccountCard(provider));
      try {
        const status = await api(`/admin/api/providers/${provider.provider_id}/auth`);
        updateConnectedAccountCard(provider, status);
        if (status.state === "connecting") pollConnectedAccount(provider);
      } catch (error) {
        updateConnectedAccountCard(provider, {
          state: "error",
          connected: false,
          message: error.message,
        });
      }
    }),
  );
}

async function refreshToolAccounts() {
  try {
    const result = await api("/admin/api/tool-accounts");
    state.toolAccounts = result;
    renderToolAccounts(result);
  } catch (error) {
    state.toolAccounts = null;
    renderToolAccounts({
      available: false,
      state: "error",
      accounts: [],
      message: error.message,
    });
  }
}

function renderToolAccounts(result) {
  const grid = byId("codexToolAccountGrid");
  const empty = byId("codexToolAccountEmptyState");
  const notice = byId("codexToolAccountNotice");
  grid.innerHTML = "";
  const accounts = Array.isArray(result?.accounts) ? result.accounts : [];
  const ready = result?.available === true && result?.state === "ready";
  notice.textContent = result?.message || (
    ready
      ? "Independent from FCC Provider Account. Switching affects only new Codex/helper sessions."
      : "Codex tool account management is unavailable in this runtime."
  );
  notice.className = `account-notice ${ready ? "" : "error"}`.trim();
  empty.hidden = accounts.length > 0;
  if (!ready && !accounts.length) {
    empty.textContent = "Codex tool account storage needs attention.";
  } else {
    empty.innerHTML = "No Codex tool accounts are saved. Add one from a terminal with <code>fcc accounts add &lt;profile&gt;</code>.";
  }
  accounts.forEach((account) => grid.appendChild(renderToolAccountCard(account)));
}

function renderToolAccountCard(account) {
  const card = document.createElement("article");
  card.className = "provider-card tool-account-card";
  card.dataset.toolAccount = "true";
  card.dataset.profile = account.profile || "";

  const title = document.createElement("div");
  title.className = "provider-title";
  const name = document.createElement("strong");
  name.textContent = account.email || account.profile || "Unnamed account";
  const pill = document.createElement("span");
  pill.className = `status-pill ${account.active ? "ok" : "neutral"}`;
  pill.textContent = account.active ? "Active" : "Saved";
  title.append(name, pill);

  const meta = document.createElement("div");
  meta.className = "provider-meta account-meta";
  const details = [`profile ${account.profile || "unknown"}`, account.plan || "plan unknown"];
  details.push(...toolAccountUsageLines(account.usage));
  meta.textContent = details.join(" · ");

  const actions = document.createElement("div");
  actions.className = "provider-actions";
  if (!account.active && account.profile) {
    actions.appendChild(
      authButton("Switch", (button) => selectToolAccount(account.profile, button)),
    );
  }
  if (account.profile) {
    actions.appendChild(
      authButton(
        "Usage",
        (button) => refreshToolAccountUsage(account.profile, button),
        "secondary-button",
      ),
    );
  }
  if (!account.active && account.profile) {
    actions.appendChild(
      authButton(
        "Forget",
        () => forgetToolAccount(account.profile),
        "secondary-button",
      ),
    );
  }
  card.append(title, meta, actions);
  return card;
}

function toolAccountUsageLines(usage) {
  if (!usage || !Array.isArray(usage.windows)) return ["usage not refreshed"];
  const lines = usage.windows
    .filter((window) => window && window.remaining_percent !== null)
    .map((window) => `${window.label || "limit"} ${Math.round(window.remaining_percent)}% left`);
  return lines.length ? lines.slice(0, 2) : ["usage unavailable"];
}

async function selectToolAccount(profile, button) {
  button.disabled = true;
  try {
    await api(`/admin/api/tool-accounts/${encodeURIComponent(profile)}/select`, {
      method: "POST",
      body: "{}",
    });
    await refreshToolAccounts();
    showMessage("Codex tool account switched. Start a new Codex/helper session to use it.", "ok");
  } catch (error) {
    showMessage(error.message, true);
    button.disabled = false;
  }
}

async function refreshToolAccountUsage(profile, button) {
  button.disabled = true;
  try {
    await api(`/admin/api/tool-accounts/${encodeURIComponent(profile)}/usage`, {
      method: "POST",
      body: "{}",
    });
    await refreshToolAccounts();
    showMessage("Codex tool-account usage refreshed.", "ok");
  } catch (error) {
    showMessage(error.message, true);
    button.disabled = false;
  }
}

async function refreshAllToolAccountUsage() {
  const button = byId("codexToolAccountUsageButton");
  button.disabled = true;
  try {
    const result = await api("/admin/api/tool-accounts/usage", {
      method: "POST",
      body: "{}",
    });
    state.toolAccounts = result;
    renderToolAccounts(result);
    const errors = Object.entries(result.refresh_errors || {})
      .filter(([, message]) => message)
      .map(([profile, message]) => `${profile}: ${message}`);
    showMessage(
      errors.length ? `Some usage refreshes failed: ${errors.join("; ")}` : "Codex tool-account usage refreshed.",
      errors.length ? "error" : "ok",
    );
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function forgetToolAccount(profile) {
  if (!window.confirm("Forget this Codex tool account snapshot? This does not log out or revoke it.")) return;
  try {
    await api(`/admin/api/tool-accounts/${encodeURIComponent(profile)}`, {
      method: "DELETE",
    });
    await refreshToolAccounts();
    showMessage("Local Codex tool-account snapshot forgotten.", "ok");
  } catch (error) {
    showMessage(error.message, true);
  }
}

function showToolAccountAddInstructions() {
  const profile = window.prompt("Profile name for the new Codex tool account:");
  if (profile === null) return;
  const normalized = profile.trim();
  if (!/^[A-Za-z0-9._-]+$/.test(normalized)) {
    showMessage("Profile names may contain only letters, numbers, dot, underscore, and hyphen.", "error");
    return;
  }
  showMessage(
    `Run in a terminal: fcc accounts add ${normalized}. The official Codex sign-in will update only the Codex tool store.`,
    "ok",
  );
}

function updateConnectedAccountCard(provider, status) {
  const current = document.querySelector(
    `[data-provider="${provider.provider_id}"][data-connected-account="true"]`,
  );
  if (current) current.replaceWith(renderConnectedAccountCard(provider, status));
}

async function startConnectedAccountLogin(providerId, mode, button) {
  button.disabled = true;
  const popup = window.open("about:blank", "_blank");
  if (popup) popup.opener = null;
  try {
    const status = await api(`/admin/api/providers/${providerId}/auth/login`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    const provider = connectedAccountDescriptor(providerId);
    updateConnectedAccountCard(provider, status);
    const target = status.authorization_url || status.verification_url;
    if (target && popup) {
      popup.location.replace(target);
    } else if (target) {
      window.open(target, "_blank", "noopener");
    } else if (popup) {
      popup.close();
    }
    pollConnectedAccount(provider);
  } catch (error) {
    if (popup) popup.close();
    showMessage(error.message, true);
    button.disabled = false;
  }
}

async function cancelConnectedAccountLogin(providerId) {
  clearConnectedAccountPoll(providerId);
  const status = await api(`/admin/api/providers/${providerId}/auth/cancel`, {
    method: "POST",
  });
  updateConnectedAccountCard(connectedAccountDescriptor(providerId), status);
}

async function disconnectConnectedAccount(providerId) {
  if (!window.confirm("Disconnect this ChatGPT account from FCC?")) return;
  clearConnectedAccountPoll(providerId);
  const status = await api(`/admin/api/providers/${providerId}/auth`, {
    method: "DELETE",
  });
  updateConnectedAccountCard(connectedAccountDescriptor(providerId), status);
  await hydrateModelOptions();
}

function pollConnectedAccount(provider) {
  clearConnectedAccountPoll(provider.provider_id);
  const poll = async () => {
    try {
      const status = await api(`/admin/api/providers/${provider.provider_id}/auth`);
      updateConnectedAccountCard(provider, status);
      if (status.state === "connecting") {
        state.authPollers.set(provider.provider_id, window.setTimeout(poll, 1000));
      } else {
        state.authPollers.delete(provider.provider_id);
        if (status.connected) await hydrateModelOptions();
      }
    } catch (error) {
      state.authPollers.delete(provider.provider_id);
      showMessage(error.message, true);
    }
  };
  state.authPollers.set(provider.provider_id, window.setTimeout(poll, 1000));
}

function clearConnectedAccountPoll(providerId) {
  const timer = state.authPollers.get(providerId);
  if (timer) window.clearTimeout(timer);
  state.authPollers.delete(providerId);
}

function connectedAccountDescriptor(providerId) {
  return state.config.provider_status.find(
    (provider) => provider.provider_id === providerId,
  );
}

async function copyDeviceCode(code) {
  try {
    await navigator.clipboard.writeText(code);
    showMessage("Device code copied.");
  } catch {
    showMessage(`Copy this device code: ${code}`);
  }
}

function updateProviderCard(providerId, status, label, metaText) {
  const card = document.querySelector(`[data-provider="${providerId}"]`);
  if (!card) return;
  const pill = card.querySelector(".status-pill");
  pill.className = `status-pill ${statusClass(status)}`;
  pill.textContent = label;
  if (metaText) {
    card.querySelector(".provider-meta").textContent = metaText;
  }
}

function renderSections(sections, fields) {
  state.modelComboboxes.clear();
  VIEW_GROUPS.forEach((view) => {
    if (view.containerId) byId(view.containerId).innerHTML = "";
  });

  const sectionById = new Map(sections.map((section) => [section.id, section]));
  const bySection = new Map();
  sections.forEach((section) => bySection.set(section.id, []));
  fields.forEach((field) => {
    if (!bySection.has(field.section)) bySection.set(field.section, []);
    bySection.get(field.section).push(field);
  });

  VIEW_GROUPS.forEach((view) => {
    if (!view.containerId) return;
    const container = byId(view.containerId);
    view.sections.forEach((sectionId) => {
      const section = sectionById.get(sectionId);
      const sectionFields = bySection.get(sectionId) || [];
      if (!section || sectionFields.length === 0) return;

      const sectionEl = document.createElement("section");
      sectionEl.className = "settings-section";
      sectionEl.id = `section-${section.id}`;

      const heading = document.createElement("div");
      heading.className = "section-heading";
      heading.innerHTML = `<div><h3>${section.label}</h3><p>${section.description}</p></div>`;
      if (section.id === "models") {
        const refreshButton = document.createElement("button");
        refreshButton.type = "button";
        refreshButton.className = "secondary-button";
        refreshButton.textContent = "Refresh models";
        refreshButton.addEventListener("click", () => refreshModelOptions(refreshButton));
        heading.appendChild(refreshButton);
      }
      sectionEl.appendChild(heading);

      const grid = document.createElement("div");
      grid.className = "field-grid";
      sectionFields.forEach((field) => {
        grid.appendChild(renderField(field));
      });
      sectionEl.appendChild(grid);

      if (sectionFields.some((field) => field.advanced)) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "ghost-button advanced-toggle";
        toggle.textContent = "Show advanced";
        toggle.addEventListener("click", () => {
          const showing = sectionEl.classList.toggle("show-advanced");
          toggle.textContent = showing ? "Hide advanced" : "Show advanced";
        });
        sectionEl.appendChild(toggle);
      }

      container.appendChild(sectionEl);
    });
  });
}

function renderField(field) {
  const wrapper = document.createElement("div");
  wrapper.className = `field${field.advanced ? " advanced-field" : ""}`;
  wrapper.dataset.key = field.key;

  const label = document.createElement("label");
  label.htmlFor = `field-${field.key}`;
  const labelText = document.createElement("span");
  labelText.textContent = field.label;
  label.appendChild(labelText);

  const source = sourceText(field);
  if (source) {
    const sourceEl = document.createElement("span");
    sourceEl.className = "field-source";
    sourceEl.textContent = source;
    label.appendChild(sourceEl);
  }

  const input = inputForField(field);
  input.id = `field-${field.key}`;
  input.dataset.key = field.key;
  input.dataset.original = field.value || "";
  input.dataset.secret = field.secret ? "true" : "false";
  input.dataset.configured = field.configured ? "true" : "false";
  input.dataset.fieldType = field.type;
  input.disabled = field.locked;
  input.addEventListener("input", updateDirtyState);
  input.addEventListener("change", updateDirtyState);
  if (field.type === "model" || field.type === "optional_model") {
    const updateEvidence = () => {
      state.selectedModelField = field.key;
      renderModelEvidence();
    };
    input.addEventListener("focus", updateEvidence);
    input.addEventListener("input", updateEvidence);
    input.addEventListener("change", updateEvidence);
  }
  if (field.type === "optional_model") {
    input.addEventListener("blur", () => {
      if (!input.value.trim() || input.value.trim().toLowerCase() === "none") {
        input.value = "None";
        updateDirtyState();
      }
    });
  }

  const control =
    field.type === "model" || field.type === "optional_model"
      ? new ModelCombobox(input, field).element
      : input;
  wrapper.append(label, control);
  if (field.description) {
    const description = document.createElement("div");
    description.className = "field-description";
    description.textContent = field.description;
    wrapper.appendChild(description);
  }
  return wrapper;
}

function inputForField(field) {
  if (field.type === "boolean") {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = String(field.value).toLowerCase() === "true";
    input.dataset.original = input.checked ? "true" : "false";
    return input;
  }

  if (field.type === "select") {
    const select = document.createElement("select");
    field.options.forEach((item) =>
      select.appendChild(option(item.value, item.label)),
    );
    select.value = field.value || field.options[0]?.value || "";
    return select;
  }

  if (field.type === "textarea") {
    const textarea = document.createElement("textarea");
    textarea.value = field.value || "";
    return textarea;
  }

  if (field.type === "model" || field.type === "optional_model") {
    const input = document.createElement("input");
    input.type = "text";
    input.value = field.value || (field.type === "optional_model" ? "None" : "");
    input.autocomplete = "off";
    return input;
  }

  const input = document.createElement("input");
  input.type = field.type === "number" ? "number" : "text";
  if (field.type === "secret") {
    input.type = "password";
    input.placeholder = field.configured
      ? "Configured - enter a new value to replace"
      : "Not configured";
    input.value = "";
    input.autocomplete = "off";
  } else {
    input.value = field.value || "";
  }
  return input;
}

class ModelCombobox {
  constructor(input, field) {
    this.input = input;
    this.fieldType = field.type;
    this.activeIndex = -1;
    this.query = "";

    this.element = document.createElement("div");
    this.element.className = "model-combobox";
    this.listbox = document.createElement("div");
    this.listbox.className = "model-combobox-list";
    this.listbox.id = `model-options-${field.key}`;
    this.listbox.setAttribute("role", "listbox");
    this.listbox.hidden = true;
    this.toggle = document.createElement("button");
    this.toggle.type = "button";
    this.toggle.className = "model-combobox-toggle";
    this.toggle.disabled = input.disabled;
    this.toggle.setAttribute("aria-label", `Show ${field.label} options`);

    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-haspopup", "listbox");
    for (const control of [input, this.toggle]) {
      control.setAttribute("aria-controls", this.listbox.id);
      control.setAttribute("aria-expanded", "false");
    }

    input.addEventListener("click", () => this.open());
    input.addEventListener("input", () => this.open(input.value));
    input.addEventListener("keydown", (event) => this.handleKeydown(event));
    this.toggle.addEventListener("mousedown", (event) => event.preventDefault());
    this.toggle.addEventListener("click", () => {
      if (this.isOpen) this.close();
      else this.open();
      input.focus();
    });
    this.listbox.addEventListener("mousedown", (event) => event.preventDefault());
    this.listbox.addEventListener("mousemove", (event) => {
      const optionEl = event.target.closest('[role="option"]');
      if (optionEl) this.setActive(this.visibleOptions.indexOf(optionEl));
    });
    this.listbox.addEventListener("click", (event) => {
      const optionEl = event.target.closest('[role="option"]');
      if (optionEl) this.select(optionEl.dataset.value);
    });

    this.element.append(input, this.toggle, this.listbox);
    state.modelComboboxes.add(this);
  }

  get isOpen() {
    return this.element.classList.contains("open");
  }

  get values() {
    return this.fieldType === "optional_model"
      ? ["None", ...state.modelOptions]
      : state.modelOptions;
  }

  get visibleOptions() {
    return Array.from(this.listbox.querySelectorAll('[role="option"]'));
  }

  open(query = "") {
    if (this.input.disabled) return;
    state.modelComboboxes.forEach((combobox) => {
      if (combobox !== this) combobox.close();
    });
    this.render(query);
    this.element.classList.add("open");
    this.listbox.hidden = false;
    this.setExpanded(true);
  }

  close() {
    this.element.classList.remove("open");
    this.listbox.hidden = true;
    this.activeIndex = -1;
    this.input.removeAttribute("aria-activedescendant");
    this.setExpanded(false);
  }

  setExpanded(expanded) {
    for (const control of [this.input, this.toggle]) {
      control.setAttribute("aria-expanded", String(expanded));
    }
  }

  render(query) {
    this.query = query;
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const values = normalizedQuery
      ? this.values.filter((value) =>
          value.toLocaleLowerCase().includes(normalizedQuery),
        )
      : this.values;
    this.listbox.innerHTML = "";

    if (values.length === 0) {
      const empty = document.createElement("div");
      empty.className = "model-combobox-empty";
      empty.textContent = state.modelOptions.length
        ? "No matching models. You can still enter a custom slug."
        : "No discovered models. Refresh models or enter a custom slug.";
      this.listbox.appendChild(empty);
      this.activeIndex = -1;
      this.input.removeAttribute("aria-activedescendant");
      return;
    }

    values.forEach((value, index) => {
      const optionEl = document.createElement("div");
      optionEl.className = "model-combobox-option";
      optionEl.id = `${this.listbox.id}-option-${index}`;
      optionEl.dataset.value = value;
      optionEl.setAttribute("role", "option");
      const label = document.createElement("strong");
      label.className = "model-option-label";
      label.textContent = state.modelLabels[value] || value;
      const id = document.createElement("span");
      id.className = "model-option-id";
      id.textContent = value;
      optionEl.append(label, id);
      this.listbox.appendChild(optionEl);
    });
    const selectedIndex = values.indexOf(this.input.value);
    this.setActive(selectedIndex >= 0 ? selectedIndex : 0, false);
  }

  setActive(index, scroll = true) {
    const options = this.visibleOptions;
    if (options.length === 0) return;
    this.activeIndex = Math.max(0, Math.min(index, options.length - 1));
    options.forEach((optionEl, optionIndex) => {
      const active = optionIndex === this.activeIndex;
      optionEl.classList.toggle("active", active);
      optionEl.setAttribute("aria-selected", String(active));
    });
    const activeOption = options[this.activeIndex];
    this.input.setAttribute("aria-activedescendant", activeOption.id);
    if (scroll) activeOption.scrollIntoView({ block: "nearest" });
  }

  move(offset) {
    const count = this.visibleOptions.length;
    if (count) this.setActive((this.activeIndex + offset + count) % count);
  }

  select(value) {
    this.input.value = value;
    this.input.dispatchEvent(new Event("change", { bubbles: true }));
    this.close();
    this.input.focus();
  }

  handleKeydown(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (this.isOpen) {
        this.move(event.key === "ArrowDown" ? 1 : -1);
      } else {
        this.open();
        if (event.key === "ArrowUp") {
          this.setActive(this.visibleOptions.length - 1);
        }
      }
    } else if (this.isOpen && (event.key === "Home" || event.key === "End")) {
      event.preventDefault();
      this.setActive(event.key === "Home" ? 0 : this.visibleOptions.length - 1);
    } else if (this.isOpen && event.key === "Enter") {
      const active = this.visibleOptions[this.activeIndex];
      if (active) {
        event.preventDefault();
        this.select(active.dataset.value);
      }
    } else if (this.isOpen && event.key === "Escape") {
      event.preventDefault();
      this.close();
    } else if (this.isOpen && event.key === "Tab") {
      this.close();
    }
  }
}

function option(value, label) {
  const optionEl = document.createElement("option");
  optionEl.value = value;
  optionEl.textContent = label;
  return optionEl;
}

function readFieldValue(input) {
  if (input.type === "checkbox") return input.checked ? "true" : "false";
  if (
    input.dataset.fieldType === "optional_model" &&
    input.value.trim().toLowerCase() === "none"
  ) {
    return "";
  }
  if (input.dataset.secret === "true" && input.dataset.configured === "true") {
    return input.value ? input.value : MASKED_SECRET;
  }
  return input.value;
}

function changedValues() {
  const values = {};
  document.querySelectorAll("[data-key]").forEach((input) => {
    if (input.disabled || !input.matches("input, select, textarea")) return;
    const value = readFieldValue(input);
    if (value !== input.dataset.original) {
      values[input.dataset.key] = value;
    }
  });
  return values;
}

function updateDirtyState() {
  const count = Object.keys(changedValues()).length;
  byId("dirtyState").textContent =
    count === 0 ? "No changes" : `${count} unsaved change${count === 1 ? "" : "s"}`;
  byId("applyButton").disabled = count === 0;
}

async function validate(showResult = true) {
  const result = await api("/admin/api/config/validate", {
    method: "POST",
    body: JSON.stringify({ values: changedValues() }),
  });
  if (showResult) {
    showValidationResult(result);
  }
  return result;
}

function showValidationResult(result) {
  if (result.valid) {
    showMessage("Config shape is valid", "ok");
  } else {
    showMessage(result.errors.join("; "), "error");
  }
}

async function apply() {
  const result = await api("/admin/api/config/apply", {
    method: "POST",
    body: JSON.stringify({ values: changedValues() }),
  });
  if (!result.applied) {
    showValidationResult(result);
    return;
  }
  const restart = result.restart || {};
  if (restart.required && restart.automatic) {
    showMessage("Applied. Restarting server...", "ok");
    byId("applyButton").disabled = true;
    setTimeout(() => {
      window.location.href = restart.admin_url || "/admin";
    }, 1600);
    return;
  }
  const pending = restart.required ? restart.fields || [] : result.pending_fields || [];
  await load();
  showMessage(
    pending.length
      ? `Applied. Restart fcc-server to use: ${pending.join(", ")}`
      : "Applied",
    "ok",
  );
}

async function refreshLocalStatus() {
  const result = await api("/admin/api/providers/local-status");
  result.providers.forEach((provider) => {
    state.localStatus.set(provider.provider_id, provider);
    const meta = provider.status_code
      ? `${provider.base_url} returned HTTP ${provider.status_code}`
      : provider.base_url;
    updateProviderCard(provider.provider_id, provider.status, provider.label, meta);
  });
}

async function testProvider(providerId, button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Testing";
  try {
    const result = await api(`/admin/api/providers/${providerId}/test`, {
      method: "POST",
      body: "{}",
    });
    if (result.ok) {
      updateProviderCard(
        providerId,
        "reachable",
        `${result.models.length} models`,
        result.models.slice(0, 3).join(", ") || "No models returned",
      );
      setModelOptions([
        ...state.modelOptions,
        ...result.models.map((model) => `${providerId}/${model}`),
      ]);
    } else {
      updateProviderCard(providerId, "offline", result.error_type, result.error_type);
    }
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function hydrateModelOptions() {
  try {
    await loadModelOptions();
  } catch {
    // Model fields remain editable when optional catalog hydration is unavailable.
  }
}

async function loadModelOptions(refresh = false) {
  const result = await api("/admin/api/models" + (refresh ? "/refresh" : ""), {
    method: refresh ? "POST" : "GET",
  });
  setModelOptions(
    result.models,
    result.model_labels || {},
    result.model_evidence || {},
  );
  return result;
}

async function refreshModelOptions(button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Refreshing";
  try {
    const result = await loadModelOptions(true);
    const failedProviders = result.failed_providers || [];
    if (failedProviders.length) {
      const labels = failedProviders.map(providerDisplayName).join(", ");
      showMessage(
        `${state.modelOptions.length} models available; could not refresh ${labels}`,
        "warn",
      );
    } else {
      showMessage(`${state.modelOptions.length} models available`, "ok");
    }
  } catch (error) {
    showMessage(`Could not refresh models: ${error.message}`, "error");
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function providerDisplayName(providerId) {
  const provider = state.config?.provider_status?.find(
    (candidate) => candidate.provider_id === providerId,
  );
  return provider?.display_name || providerId;
}

function setModelOptions(models, labels = {}, evidence = null) {
  state.modelLabels = { ...state.modelLabels, ...labels };
  if (evidence) state.modelEvidence = evidence;
  state.modelOptions = Array.from(
    new Set(models.filter((model) => typeof model === "string" && model.trim())),
  ).sort((left, right) => left.localeCompare(right));
  state.modelComboboxes.forEach((combobox) => {
    if (combobox.isOpen) combobox.render(combobox.query);
  });
  renderModelEvidence();
}

function renderModelEvidence() {
  const panel = byId("modelEvidencePanel");
  const modelLabel = byId("modelEvidenceModel");
  const summary = byId("modelEvidenceSummary");
  const meta = byId("modelEvidenceMeta");
  const grid = byId("modelEvidenceGrid");
  if (!panel || !modelLabel || !summary || !meta || !grid) return;

  const modelInputs = Array.from(
    document.querySelectorAll(
      'input[data-field-type="model"], input[data-field-type="optional_model"]',
    ),
  );
  const selectedInput =
    modelInputs.find((input) => input.dataset.key === state.selectedModelField) ||
    modelInputs.find((input) => input.dataset.key === "MODEL") ||
    modelInputs[0];
  const selectedValue = selectedInput?.value.trim() || "";
  const inheritsDefault = selectedValue.toLowerCase() === "none";
  const defaultInput = modelInputs.find((input) => input.dataset.key === "MODEL");
  const modelId = inheritsDefault
    ? defaultInput?.value.trim() || ""
    : selectedValue;
  const evidence = state.modelEvidence[modelId];

  modelLabel.textContent = inheritsDefault
    ? `Uses ${modelId || "the default model"}`
    : modelId || "No model selected";
  meta.replaceChildren();
  grid.replaceChildren();

  if (!modelId) {
    summary.textContent = "Choose a model to inspect its capability evidence.";
    return;
  }

  if (!evidence) {
    summary.textContent =
      "No cached evidence is available. This model remains unknown until discovery or an explicit receipt.";
    appendEvidenceMeta(meta, {
      evidence_source: "unknown",
      observed_at: null,
      evidence_version: null,
      evidence_protocol: null,
    });
    appendUnknownCapabilityRows(grid);
    return;
  }

  const claims = Object.values(evidence.capabilities || {});
  const unverified = claims.filter(
    (claim) => claim.state === "accepted-but-unverified",
  ).length;
  summary.textContent = unverified
    ? `${unverified} claim${unverified === 1 ? " is" : "s are"} accepted but unverified; live support is not implied.`
    : "Claims are shown with their current state and provenance.";
  appendEvidenceMeta(meta, evidence);

  Object.entries(MODEL_EVIDENCE_LABELS).forEach(([capability, label]) => {
    appendCapabilityRow(
      grid,
      label,
      evidence.capabilities?.[capability] || {
        state: "unknown",
        confidence: "unknown",
        source: "unknown",
      },
    );
  });
}

function appendEvidenceMeta(meta, evidence) {
  const values = [
    ["Source", evidence.evidence_source || "unknown"],
    ["Observed", evidence.observed_at || "not recorded"],
    ["Version", evidence.evidence_version || "not recorded"],
    ["Protocol", evidence.evidence_protocol || "not recorded"],
  ];
  values.forEach(([label, value]) => {
    const item = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = `${label}:`;
    item.append(name, ` ${value}`);
    meta.appendChild(item);
  });
}

function appendUnknownCapabilityRows(grid) {
  Object.entries(MODEL_EVIDENCE_LABELS).forEach(([capability, label]) => {
    appendCapabilityRow(grid, label, {
      state: "unknown",
      confidence: "unknown",
      source: "unknown",
    });
  });
}

function appendCapabilityRow(grid, label, claim) {
  const row = document.createElement("div");
  row.className = "model-evidence-row";
  const name = document.createElement("strong");
  name.textContent = label;
  const pill = document.createElement("span");
  pill.className = `status-pill ${evidenceStatusClass(claim.state)}`;
  pill.textContent = evidenceStatusLabel(claim.state);
  const detail = document.createElement("small");
  detail.textContent = `${claim.confidence || "unknown"} · ${claim.source || "unknown"}`;
  row.append(name, pill, detail);
  grid.appendChild(row);
}

function evidenceStatusClass(status) {
  if (status === "supported") return "ok";
  if (status === "unsupported") return "error";
  if (status === "accepted-but-unverified") return "warn";
  return "neutral";
}

function evidenceStatusLabel(status) {
  if (status === "accepted-but-unverified") return "Unverified";
  if (status === "unknown") return "Unknown";
  return status ? status[0].toUpperCase() + status.slice(1) : "Unknown";
}

function formatTokens(value) {
  const number = Number(value || 0);
  if (number < 1000) return String(number);
  if (number < 1000000) return `${(number / 1000).toFixed(number < 10000 ? 1 : 0)}k`;
  return `${(number / 1000000).toFixed(number < 10000000 ? 1 : 0)}M`;
}

function renderUsage(summary) {
  const totals = summary.totals || {};
  const stats = byId("usageStats");
  stats.innerHTML = "";
  [
    ["Total tokens", Number(totals.input_tokens || 0) + Number(totals.output_tokens || 0)],
    ["Input", totals.input_tokens],
    ["Output", totals.output_tokens],
    ["Requests", totals.requests],
    ["Failed", totals.failed_requests],
    ["Cache read", totals.cache_read_input_tokens],
    ["Cache write", totals.cache_creation_input_tokens],
  ].forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "usage-stat";
    const title = document.createElement("span");
    title.textContent = label;
    const amount = document.createElement("strong");
    amount.textContent = formatTokens(value);
    card.append(title, amount);
    stats.appendChild(card);
  });

  const tracking = byId("usageTracking");
  tracking.textContent = "";
  const trackingInfo = summary.tracking || {};
  const trackingLabel = document.createElement("strong");
  trackingLabel.textContent = trackingInfo.source_label || "FCC proxy";
  const trackingDetails = document.createElement("span");
  trackingDetails.textContent = [
    trackingInfo.account_labeling,
    trackingInfo.native_codex_usage,
  ]
    .filter(Boolean)
    .join(" · ");
  tracking.append(trackingLabel, trackingDetails);

  const chart = byId("usageChart");
  chart.innerHTML = "";
  const days = summary.daily || [];
  const maxTokens = Math.max(
    1,
    ...days.map((day) => Number(day.input_tokens || 0) + Number(day.output_tokens || 0)),
  );
  if (!days.some((day) => Number(day.requests || 0))) {
    chart.textContent = "No usage recorded in this range yet.";
    chart.classList.add("empty");
  } else {
    chart.classList.remove("empty");
    days.forEach((day) => {
      const total = Number(day.input_tokens || 0) + Number(day.output_tokens || 0);
      const column = document.createElement("div");
      column.className = "usage-bar-column";
      const bar = document.createElement("div");
      bar.className = "usage-bar";
      bar.style.height = `${Math.max(total ? 4 : 0, (total / maxTokens) * 100)}%`;
      bar.title = `${day.date}: ${formatTokens(total)} tokens; ${day.requests || 0} requests; ${day.failed_requests || 0} failed`;
      const label = document.createElement("span");
      label.textContent = day.date.slice(5);
      column.append(bar, label);
      chart.appendChild(column);
    });
  }

  const models = byId("usageModels");
  models.innerHTML = "<h3>Models</h3>";
  const rows = summary.models || [];
  const usageLabels = summary.model_labels || {};
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "usage-empty";
    empty.textContent = "No model usage recorded yet.";
    models.appendChild(empty);
    return;
  }
  const table = document.createElement("table");
  table.className = "usage-table";
  table.innerHTML = "<thead><tr><th>Model</th><th>Tracking</th><th>Requests</th><th>Failed</th><th>Input</th><th>Output</th><th>Cache read</th><th>Cache write</th></tr></thead>";
  const body = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const modelCell = document.createElement("td");
    const label = document.createElement("strong");
    label.textContent =
      usageLabels[row.model] || state.modelLabels[row.model] || row.model;
    const id = document.createElement("small");
    id.textContent = row.model;
    modelCell.append(label, id);
    const trackingCell = document.createElement("td");
    trackingCell.textContent = row.tracking_label || "FCC proxy · account not identified";
    tr.append(
      modelCell,
      trackingCell,
      usageCell(row.requests),
      usageCell(row.failed_requests),
      usageCell(formatTokens(row.input_tokens)),
      usageCell(formatTokens(row.output_tokens)),
      usageCell(formatTokens(row.cache_read_input_tokens)),
      usageCell(formatTokens(row.cache_creation_input_tokens)),
    );
    body.appendChild(tr);
  });
  table.appendChild(body);
  models.appendChild(table);
}

function usageCell(value) {
  const cell = document.createElement("td");
  cell.textContent = String(value ?? 0);
  return cell;
}

async function loadUsage(days = state.usageDays) {
  state.usageDays = days;
  try {
    renderUsage(await api(`/admin/api/usage?days=${days}`));
  } catch (error) {
    byId("usageChart").textContent = `Could not load usage: ${error.message}`;
    byId("usageChart").classList.add("empty");
  }
}

async function loadReviewer() {
  try {
    renderReviewer(await api("/admin/api/reviewer"));
  } catch (error) {
    byId("reviewerPackGrid").textContent = `Could not load reviewer state: ${error.message}`;
    byId("reviewerScarGrid").replaceChildren();
  }
}

function renderReviewer(status) {
  const packGrid = byId("reviewerPackGrid");
  const scarGrid = byId("reviewerScarGrid");
  const empty = byId("reviewerEmptyState");
  const profileLabel = byId("reviewerProfileLabel");
  packGrid.replaceChildren();
  scarGrid.replaceChildren();
  profileLabel.textContent = `Profile: ${status.profile || "default"}`;

  (status.packs || []).forEach((pack) => {
    const card = document.createElement("article");
    card.className = "reviewer-pack-card";
    const title = document.createElement("strong");
    title.textContent = pack.pack;
    const mode = document.createElement("span");
    mode.className = `status-pill ${pack.mode === "disabled" ? "neutral" : "ok"}`;
    mode.textContent = pack.mode;
    const actions = document.createElement("div");
    actions.className = "reviewer-actions";
    actions.append(
      reviewerActionButton("Enable", () => setReviewerPack(pack.pack, true), pack.mode === "enabled"),
      reviewerActionButton("Disable", () => setReviewerPack(pack.pack, false), pack.mode === "disabled"),
    );
    card.append(title, mode, actions);
    packGrid.appendChild(card);
  });

  const scars = status.scars || [];
  empty.hidden = scars.length !== 0;
  scars.forEach((scar) => {
    const card = document.createElement("article");
    card.className = "reviewer-scar-card";
    const heading = document.createElement("div");
    heading.className = "reviewer-scar-heading";
    const title = document.createElement("strong");
    title.textContent = `${scar.kind} · ${scar.scope}`;
    const state = document.createElement("span");
    state.className = `status-pill ${scarStateClass(scar.state)}`;
    state.textContent = scar.state;
    heading.append(title, state);
    const details = document.createElement("small");
    details.textContent = `${scar.scar_id} · ${scar.condition} · ${scar.rule}`;
    const actions = document.createElement("div");
    actions.className = "reviewer-actions";
    const active = ["OBSERVED", "REPRODUCED", "VERIFIED", "UPSTREAM_BUG", "MITIGATED"].includes(scar.state);
    actions.append(
      reviewerActionButton("Forget", () => updateReviewerScar(scar.scar_id, "forget"), !active),
      reviewerActionButton("Supersede", () => updateReviewerScar(scar.scar_id, "supersede"), !active),
    );
    card.append(heading, details, actions);
    scarGrid.appendChild(card);
  });
}

function reviewerActionButton(label, action, disabled = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = label;
  button.disabled = disabled;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await action();
    } catch (error) {
      showMessage(error.message, "error");
      button.disabled = false;
    }
  });
  return button;
}

function scarStateClass(state) {
  if (["VERIFIED", "MITIGATED", "UPSTREAM_BUG"].includes(state)) return "ok";
  if (["STALE", "SUPERSEDED", "DISPROVEN"].includes(state)) return "neutral";
  return "warn";
}

async function setReviewerPack(pack, enabled) {
  await api(`/admin/api/reviewer/packs/${encodeURIComponent(pack)}`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
  await loadReviewer();
  showMessage(`${pack}: ${enabled ? "enabled" : "disabled"}`, "ok");
}

async function updateReviewerScar(scarId, action) {
  const label = action === "forget" ? "stale" : "superseded";
  if (!window.confirm(`Mark this scar ${label}? Its audit record will remain.`)) return;
  await api(`/admin/api/reviewer/scars/${encodeURIComponent(scarId)}/${action}`, {
    method: "POST",
    body: "{}",
  });
  await loadReviewer();
  showMessage(`Scar marked ${label}`, "ok");
}

function showMessage(message, kind = "") {
  const area = byId("messageArea");
  area.textContent = message;
  area.className = `message-area ${kind}`.trim();
}

byId("validateButton").addEventListener("click", () => validate(true));
byId("applyButton").addEventListener("click", apply);
byId("usageRefreshButton").addEventListener("click", () => loadUsage());
byId("codexToolAccountAddButton").addEventListener("click", showToolAccountAddInstructions);
byId("codexToolAccountUsageButton").addEventListener("click", refreshAllToolAccountUsage);
byId("reviewerRefreshButton").addEventListener("click", () => loadReviewer());
byId("customProviderAddButton").addEventListener("click", () => showCustomProviderEditor());
byId("customProviderCancelButton").addEventListener("click", hideCustomProviderEditor);
byId("customProviderForm").addEventListener("submit", saveCustomProvider);
document.querySelectorAll("[data-usage-days]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-usage-days]").forEach((candidate) => {
      candidate.classList.toggle("active", candidate === button);
    });
    loadUsage(Number(button.dataset.usageDays));
  });
});
document.addEventListener("pointerdown", (event) => {
  state.modelComboboxes.forEach((combobox) => {
    if (combobox.isOpen && !combobox.element.contains(event.target)) combobox.close();
  });
});

load().catch((error) => {
  showMessage(error.message, "error");
});
