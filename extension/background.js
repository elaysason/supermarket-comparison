/**
 * Cart Sniper — background.js (Service Worker)
 *
 * Acts as a fetch proxy for the content script.
 * Content scripts injected into HTTPS pages cannot call http://127.0.0.1
 * due to mixed-content restrictions. Background service workers are exempt
 * from this rule, so we relay the API call through here.
 */

const API_BASES = [
  "http://127.0.0.1:8001",
  "http://127.0.0.1:8000",
];
const API_KEY = "fepVCPso5nH44S"; // Must match API_KEY in .env
const REQUEST_TIMEOUT_MS = 12000;

function withTimeoutFetch(url, options, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal }).finally(() => {
    clearTimeout(timer);
  });
}

async function compareCart(payload) {
  let lastError = null;

  for (const base of API_BASES) {
    try {
      const response = await withTimeoutFetch(`${base}/api/compare`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": API_KEY,
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`API error ${response.status}: ${text}`);
      }

      return await response.json();
    } catch (error) {
      lastError = error;
      const isTimeout = error?.name === "AbortError";
      const isNetworkFailure = /failed to fetch|networkerror|connection/i.test(
        String(error?.message || "")
      );

      if (!isTimeout && !isNetworkFailure) {
        break;
      }
    }
  }

  if (lastError?.name === "AbortError") {
    throw new Error(
      `API request timed out after ${REQUEST_TIMEOUT_MS / 1000}s.`
    );
  }

  throw lastError || new Error("Unknown API failure.");
}

chrome.runtime.onInstalled.addListener(() => {
  console.log("[CartSniper] Extension installed.");
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "COMPARE_CART") return false;

  compareCart({
    source_chain_code: message.source_chain_code,
    barcodes: message.barcodes,
    quantities: message.quantities || {},
  })
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) => sendResponse({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    }));

  // Return true to keep the message channel open for the async response
  return true;
});
