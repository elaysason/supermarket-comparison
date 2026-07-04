/**
 * Cart Sniper — background.js (Service Worker)
 *
 * Acts as a fetch proxy for the content script.
 */

const API_BASES = [
  "https://supermarket-comparison-api-649951889970.europe-west1.run.app",
];
const REQUEST_TIMEOUT_MS = 30000;

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
    const url = `${base}/api/compare`;
    try {
      console.log("[CartSniper] Calling API:", url);
      const response = await withTimeoutFetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`API error ${response.status}: ${text}`);
      }

      return await response.json();
    } catch (error) {
      console.error("[CartSniper] API request failed:", url, error);
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
  if (!message || message.type !== "COMPARE_CART") return false;

  let didRespond = false;
  const respond = (payload) => {
    if (didRespond) return;
    didRespond = true;
    sendResponse(payload);
  };

  try {
    compareCart({
      source_chain_code: message.source_chain_code,
      barcodes: message.barcodes || [],
      quantities: message.quantities || {},
      item_names: message.item_names || {},
    })
      .then((data) => respond({ ok: true, data }))
      .catch((err) =>
        respond({
          ok: false,
          error: err instanceof Error ? err.message : String(err),
        })
      );
  } catch (err) {
    respond({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }

  // Return true to keep the message channel open for the async response.
  return true;
});
