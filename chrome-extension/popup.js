const TEXT = {
  connected: "Connected to Cipher",
  connecting: "Connecting…",
  disconnected: "Not connected.",
  unreachable: "Can't reach the Cipher app.",
  needs_code: "Paste the pairing code to connect",
};
const statusEl = document.getElementById("status");
const statusText = document.getElementById("statusText");
const codeEl = document.getElementById("code");

function render(status, detail) {
  statusEl.dataset.s = status || "needs_code";
  statusText.textContent = (TEXT[status] || TEXT.needs_code) + (detail && status !== "connected" ? ` ${detail}` : "");
}

chrome.storage.local.get(["code", "status", "detail"]).then(({ code, status, detail }) => {
  codeEl.value = code || "";
  render(status, detail);
});
chrome.storage.onChanged.addListener(async () => {
  const { status, detail } = await chrome.storage.local.get(["status", "detail"]);
  render(status, detail);
});
// Opening the popup also nudges a reconnect.
chrome.runtime.sendMessage({ type: "reconnect" }).catch(() => {});

document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ code: codeEl.value.trim() });
  chrome.runtime.sendMessage({ type: "reconnect" }).catch(() => {});
});
