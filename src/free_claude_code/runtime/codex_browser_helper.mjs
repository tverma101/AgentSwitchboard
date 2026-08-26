// Bounded bridge to the installed Codex Chrome/Edge browser plugin.
// Adapted from deepcoldy/botmux@eff1953a66fe6054f47d9311c719ab73c4ed6f1d (MIT).

import { existsSync, readdirSync, realpathSync } from "node:fs";
import { createConnection } from "node:net";
import { homedir, platform, tmpdir } from "node:os";
import { basename, isAbsolute, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { pathToFileURL } from "node:url";

const MAX_TEXT_BYTES = 512 * 1024;
const MAX_SCREENSHOT_BYTES = 16 * 1024 * 1024;
const MAX_URL_BYTES = 16 * 1024;
const MAX_VALUE_BYTES = 100 * 1024;
const FAMILY = process.env.FCC_CODEX_BROWSER_FAMILY || "chrome";
const EXPLICIT_PLUGIN_ROOT = process.env.FCC_CODEX_BROWSER_PLUGIN_ROOT || undefined;
const SESSION_ID = process.env.FCC_CODEX_BROWSER_SESSION_ID || "fcc-browser";

if (FAMILY !== "chrome" && FAMILY !== "edge") {
  throw new Error("FCC_CODEX_BROWSER_FAMILY must be chrome or edge");
}

function isCompletePluginRoot(root) {
  return existsSync(join(root, "scripts/browser-client.mjs"))
    && existsSync(join(root, "scripts/browser-service.mjs"));
}

function compareVersionNames(left, right) {
  const leftParts = basename(left).split(".").map(Number);
  const rightParts = basename(right).split(".").map(Number);
  for (let index = 0; index < Math.max(leftParts.length, rightParts.length); index += 1) {
    const delta = (leftParts[index] || 0) - (rightParts[index] || 0);
    if (delta) return delta;
  }
  return left.localeCompare(right);
}

function resolvePluginRoot() {
  if (EXPLICIT_PLUGIN_ROOT && !isAbsolute(EXPLICIT_PLUGIN_ROOT)) {
    throw new Error("Codex browser plugin root must be absolute");
  }
  const codexHome = process.env.CODEX_HOME?.trim() || join(homedir(), ".codex");
  const cache = join(codexHome, "plugins", "cache", "openai-bundled", "chrome");
  const explicit = EXPLICIT_PLUGIN_ROOT ? resolve(EXPLICIT_PLUGIN_ROOT) : undefined;
  if (explicit) {
    const root = realpathSync(explicit);
    if (!isCompletePluginRoot(root)) throw new Error("Codex browser plugin is incomplete");
    return root;
  }
  const latest = join(cache, "latest");
  if (isCompletePluginRoot(latest)) return realpathSync(latest);
  let entries;
  try {
    entries = readdirSync(cache, { withFileTypes: true });
  } catch {
    throw new Error(`Codex browser plugin is not installed under ${cache}`);
  }
  const candidates = entries
    .filter((entry) => entry.isDirectory() || entry.isSymbolicLink())
    .map((entry) => join(cache, entry.name))
    .filter(isCompletePluginRoot)
    .sort((left, right) => compareVersionNames(right, left));
  if (!candidates[0]) throw new Error(`Codex browser plugin is not installed under ${cache}`);
  return realpathSync(candidates[0]);
}

function connectNativePipe(path) {
  return new Promise((resolveConnection, reject) => {
    const socket = createConnection(path);
    const onError = (error) => reject(error);
    socket.once("error", onError);
    socket.once("connect", () => {
      socket.off("error", onError);
      resolveConnection(socket);
    });
  });
}

function requireString(value, field, maxBytes) {
  if (typeof value !== "string" || Buffer.byteLength(value, "utf8") > maxBytes) {
    throw new Error(`${field} must be a string no larger than ${maxBytes} bytes`);
  }
  return value;
}

function requireNonEmptyString(value, field, maxBytes) {
  const text = requireString(value, field, maxBytes);
  if (!text) throw new Error(`${field} must not be empty`);
  return text;
}

function requireIndex(value, field) {
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`${field} must be a non-negative integer`);
  }
  return value;
}

function requireFinite(value, field) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${field} must be finite`);
  }
  return value;
}

function boundedText(value) {
  let text = typeof value === "string" ? value : JSON.stringify(value);
  if (Buffer.byteLength(text, "utf8") > MAX_TEXT_BYTES) {
    text = `${Buffer.from(text, "utf8").subarray(0, MAX_TEXT_BYTES).toString("utf8")}\n[truncated by FCC]`;
  }
  return { text };
}

let browser;
let initialization;
const claimedTabs = new Map();
const configStore = new Map();
let runtimeShim;

function withRequestMetadata(request) {
  if (request.method !== "execute" || runtimeShim == null) return request;
  const params = request.params;
  if (params == null || typeof params !== "object" || Array.isArray(params)) {
    return request;
  }
  return {
    ...request,
    params: { ...params, requestMeta: runtimeShim.requestMeta },
  };
}

async function initialize(initialRequest) {
  const root = resolvePluginRoot();
  const service = await import(pathToFileURL(join(root, "scripts/browser-service.mjs")).href);
  const client = await import(pathToFileURL(join(root, "scripts/browser-client.mjs")).href);
  runtimeShim = {
    env: { ...process.env },
    cwd: process.cwd(),
    homeDir: homedir(),
    tmpDir: tmpdir(),
    platform: platform(),
    requestMeta: {},
    nativePipe: { createConnection: connectNativePipe },
    config: {
      read: async () => ({}),
      readRequirements: async () => ({}),
      readToml: async (path) => configStore.get(path) ?? {},
      writeToml: async (path, value) => configStore.set(path, value),
    },
    createElicitation: async () => ({ action: "cancel" }),
    setResponseMeta: () => {},
    addAfterSubmittedCodeHook: () => {},
    emitContentItem: () => {},
    emitImage: () => {},
    write: () => {},
    fetch: globalThis.fetch,
    rpc: undefined,
  };
  updateMetadata(initialRequest);
  globalThis.nodeRepl = runtimeShim;
  runtimeShim.rpc = async (name, request) => {
    if (name !== "browser") throw new Error(`unsupported trusted service: ${name}`);
    return service.handleRpc(withRequestMetadata(request));
  };
  const agent = await client.setupBrowserRuntime();
  browser = await agent.browsers.get(FAMILY);
  await browser.nameSession(`fcc-${SESSION_ID.slice(0, 24)}`).catch(() => {});
  return browser;
}

async function getBrowser(initialRequest) {
  if (browser) return browser;
  initialization ??= initialize(initialRequest);
  return initialization;
}

function updateMetadata(request) {
  if (!runtimeShim) return;
  runtimeShim.requestMeta = {
    "x-codex-turn-metadata": JSON.stringify({
      session_id: SESSION_ID,
      thread_id: request.thread_id || SESSION_ID,
      turn_id: request.turn_id || String(request.id ?? "fcc"),
      thread_source: "fcc",
    }),
  };
}

async function describeTab(tab) {
  const [title, url] = await Promise.all([tab.title(), tab.url()]);
  return { id: tab.id, ...(title ? { title } : {}), ...(url ? { url } : {}) };
}

async function getTab(tabId) {
  const cached = claimedTabs.get(tabId);
  if (cached) return cached;
  const activeBrowser = await getBrowser();
  const tab = await activeBrowser.tabs.get(tabId);
  claimedTabs.set(tab.id, tab);
  return tab;
}

async function execute(request) {
  const input = request.arguments;
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new Error("arguments must be an object");
  }
  const operation = requireNonEmptyString(request.operation, "operation", 64);
  const activeBrowser = await getBrowser(request);
  updateMetadata(request);

  if (operation === "list_tabs") {
    return { family: FAMILY, tabs: await activeBrowser.user.openTabs() };
  }
  if (operation === "claim_tab") {
    const tabId = requireNonEmptyString(input.tab_id, "tab_id", 256);
    const info = (await activeBrowser.user.openTabs()).find((tab) => tab.id === tabId);
    if (!info) throw new Error(`user tab is no longer available: ${tabId}`);
    const tab = await activeBrowser.user.claimTab(info);
    claimedTabs.set(tabId, tab);
    claimedTabs.set(tab.id, tab);
    return describeTab(tab);
  }
  if (operation === "new_tab") {
    const tab = await activeBrowser.tabs.new();
    claimedTabs.set(tab.id, tab);
    return describeTab(tab);
  }
  if (operation === "selected_tab") {
    const tab = await activeBrowser.tabs.selected();
    if (!tab) return { tab: null };
    claimedTabs.set(tab.id, tab);
    return describeTab(tab);
  }

  const tab = await getTab(requireNonEmptyString(input.tab_id, "tab_id", 256));
  switch (operation) {
    case "tab_info":
      return describeTab(tab);
    case "goto":
      await tab.goto(requireNonEmptyString(input.url, "url", MAX_URL_BYTES));
      return describeTab(tab);
    case "snapshot":
      return boundedText(await tab.ax.get("state", { disableDiffing: input.disable_diffing === true }));
    case "click":
      await tab.ax.click(requireIndex(input.element_index, "element_index"));
      return { ok: true };
    case "set_value":
      await tab.ax.setValue(
        requireIndex(input.element_index, "element_index"),
        requireString(input.value, "value", MAX_VALUE_BYTES),
      );
      return { ok: true };
    case "type_text":
      await tab.ax.typeText(requireString(input.value, "value", MAX_VALUE_BYTES));
      return { ok: true };
    case "press_key":
      await tab.ax.pressKey(requireNonEmptyString(input.key, "key", 256));
      return { ok: true };
    case "scroll": {
      if (!["up", "down", "left", "right"].includes(input.direction)) {
        throw new Error("direction must be up, down, left, or right");
      }
      const target = input.element_index !== undefined
        ? requireIndex(input.element_index, "element_index")
        : [requireFinite(input.x, "x"), requireFinite(input.y, "y")];
      const pages = input.pages === undefined ? undefined : requireFinite(input.pages, "pages");
      if (pages !== undefined && (pages <= 0 || pages > 20)) {
        throw new Error("pages must be > 0 and <= 20");
      }
      await tab.ax.scroll(target, input.direction, pages);
      return { ok: true };
    }
    case "screenshot": {
      const bytes = await tab.screenshot({ fullPage: input.full_page === true });
      if (bytes.byteLength > MAX_SCREENSHOT_BYTES) {
        throw new Error(`screenshot exceeds ${MAX_SCREENSHOT_BYTES} bytes`);
      }
      return { media_type: "image/jpeg", image_base64: Buffer.from(bytes).toString("base64") };
    }
    case "reload":
      await tab.reload(); return { ok: true };
    case "back":
      await tab.back(); return { ok: true };
    case "forward":
      await tab.forward(); return { ok: true };
    case "mark_handoff":
      await tab.markHandoff(); return { ok: true };
    case "mark_deliverable":
      await tab.markDeliverable(); return { ok: true };
    case "close_tab":
      await tab.close(); claimedTabs.delete(tab.id); return { ok: true };
    default:
      throw new Error(`unsupported browser operation: ${operation}`);
  }
}

function reply(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", async (line) => {
  if (Buffer.byteLength(line, "utf8") > MAX_VALUE_BYTES * 2) {
    reply({ id: null, ok: false, error: "request exceeds input bound" });
    return;
  }
  let request;
  try {
    request = JSON.parse(line);
    const result = await execute(request);
    reply({ id: request.id ?? null, ok: true, result });
  } catch (error) {
    reply({ id: request?.id ?? null, ok: false, error: error instanceof Error ? error.message : String(error) });
  }
});
