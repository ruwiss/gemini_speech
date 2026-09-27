const HOST = "com.gemini.speech";
const NAMES = new Set([
  "HSID", "SSID", "APISID", "SAPISID", "SID", "SIDCC", "NID", "AEC", "COMPASS",
  "__Secure-1PSID", "__Secure-1PSIDTS", "__Secure-1PSIDRTS", "__Secure-1PSIDCC",
  "__Secure-3PSID", "__Secure-3PSIDTS", "__Secure-3PSIDRTS", "__Secure-3PSIDCC",
  "__Secure-1PAPISID", "__Secure-3PAPISID",
]);

function rank(domain) {
  if (domain === ".google.com") return 0;
  if (domain === ".gemini.google.com") return 1;
  return 2;
}

async function push() {
  const rows = await chrome.cookies.getAll({});
  rows.sort((a, b) => rank(a.domain) - rank(b.domain));
  const seen = new Set();
  const parts = [];
  for (const row of rows) {
    if (!NAMES.has(row.name) || seen.has(row.name) || !row.value) continue;
    if (rank(row.domain) === 2) continue;
    seen.add(row.name);
    parts.push(row.name + "=" + row.value);
  }
  const header = parts.join("; ");
  if (!header.includes("SAPISID=") || !header.includes("__Secure-1PSID=")) return;
  chrome.runtime.sendNativeMessage(HOST, {cookie: header});
}

chrome.runtime.onStartup.addListener(push);
chrome.runtime.onInstalled.addListener(push);
chrome.alarms.create("push", {periodInMinutes: 1});
chrome.alarms.onAlarm.addListener(push);
push();
