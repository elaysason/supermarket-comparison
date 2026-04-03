/**
 * Cart Sniper — background.js (Service Worker)
 *
 * Acts as a fetch proxy for the content script.
 * Content scripts injected into HTTPS pages cannot call http://127.0.0.1
 * due to mixed-content restrictions. Background service workers are exempt
 * from this rule, so we relay the API call through here.
 */

const API_BASE = "http://127.0.0.1:8001";
const API_KEY  = "fepVCPso5nH44S"; // Must match API_KEY in .env

chrome.runtime.onInstalled.addListener(() => {
  console.log("[CartSniper] Extension installed.");
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "COMPARE_CART") return false;

  fetch(`${API_BASE}/api/compare`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify({
      source_chain_code: message.source_chain_code,
      barcodes: message.barcodes,
      quantities: message.quantities || {},
    }),
  })
    .then((res) => {
      if (!res.ok) {
        return res.text().then((t) => {
          throw new Error(`API error ${res.status}: ${t}`);
        });
      }
      return res.json();
    })
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) => sendResponse({ ok: false, error: err.message }));

  // Return true to keep the message channel open for the async response
  return true;
});
