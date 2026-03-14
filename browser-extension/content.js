/**
 * J.A.R.V.I.S Browser Extension — Content Script
 *
 * Extracts visible page text and sends to the local server.
 * Works alongside UIAutomation: this handles web page content,
 * UIAutomation handles native apps (SAP, Excel, KakaoTalk).
 *
 * Together they read everything visible on screen.
 */

const CONFIG = {
  serverUrl: "http://localhost:8000/api/v1/push/screen-text",
  intervalMs: 30000,
  maxTextLength: 2000,
  // Domains that are ALWAYS excluded (banking, payment, security)
  defaultExcludeDomains: [
    "banking", "bank.", "kbstar", "shinhan", "woori", "hana", "ibk",
    "toss.im", "kakaopay", "naverpay", "paypal", "stripe",
    "accounts.google", "login.microsoftonline", "auth0",
    "1password", "lastpass", "bitwarden",
  ],
};

let lastHash = 0;
let excludeDomains = [];

// ── Hash ──────────────────────────────────────────────────────────────
function simpleHash(str) {
  let hash = 0;
  const s = str.slice(0, 1000);
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash + s.charCodeAt(i)) | 0;
  }
  return hash;
}

// ── Safety checks ─────────────────────────────────────────────────────
function hasPasswordField() {
  return document.querySelectorAll('input[type="password"]').length > 0;
}

function isDomainExcluded(hostname) {
  const all = [...CONFIG.defaultExcludeDomains, ...excludeDomains];
  return all.some((d) => hostname.includes(d));
}

function isLoginPage() {
  const url = location.href.toLowerCase();
  const keywords = ["login", "signin", "sign-in", "auth", "sso", "oauth", "2fa"];
  return keywords.some((k) => url.includes(k));
}

// ── Domain label ──────────────────────────────────────────────────────
function domainLabel(hostname) {
  const map = {
    "mail.worksmobile.com": "네이버 웍스",
    "mail.google.com": "Gmail",
    "calendar.google.com": "Google Calendar",
    "docs.google.com": "Google Docs",
    "github.com": "GitHub",
    "notion.so": "Notion",
    "slack.com": "Slack",
    "web.whatsapp.com": "WhatsApp",
    "www.youtube.com": "YouTube",
    "claude.ai": "Claude",
  };
  for (const [domain, label] of Object.entries(map)) {
    if (hostname.includes(domain)) return label;
  }
  return hostname;
}

// ── Text extraction ───────────────────────────────────────────────────
function extractPageText() {
  const hostname = location.hostname;

  // Safety: skip excluded domains, password pages, login pages
  if (isDomainExcluded(hostname)) return null;
  if (hasPasswordField()) return null;
  if (isLoginPage()) return null;

  // Get visible text
  let text = document.body?.innerText || "";
  if (text.length < 10) return null;

  // Truncate
  if (text.length > CONFIG.maxTextLength) {
    text = text.slice(0, CONFIG.maxTextLength) + "...";
  }

  // Clean up excessive whitespace
  text = text.replace(/\n{3,}/g, "\n\n").replace(/ {2,}/g, " ").trim();

  return {
    app_name: domainLabel(hostname),
    window_title: document.title,
    extracted_text: text,
    text_length: text.length,
    timestamp: new Date().toISOString(),
  };
}

// ── Send to server ────────────────────────────────────────────────────
async function sendToServer(record) {
  try {
    const resp = await fetch(CONFIG.serverUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ records: [record] }),
    });
    if (resp.ok) {
      console.debug("[JARVIS] Screen text sent:", record.app_name, record.text_length, "chars");
    }
  } catch {
    // Server not running — silently ignore
  }
}

// ── Main loop ─────────────────────────────────────────────────────────
function tick() {
  const record = extractPageText();
  if (!record) return;

  const hash = simpleHash(record.extracted_text);

  // Skip if content unchanged
  if (hash === lastHash) return;
  lastHash = hash;

  sendToServer(record);
}

// ── Init ──────────────────────────────────────────────────────────────
function init() {
  // Load user-configured exclude domains
  if (chrome?.storage?.sync) {
    chrome.storage.sync.get({ excludeDomains: [] }, (data) => {
      excludeDomains = data.excludeDomains || [];
    });
  }

  // First extraction after page settles
  setTimeout(tick, 3000);

  // Periodic extraction
  setInterval(tick, CONFIG.intervalMs);
}

init();
