/**
 * Cart Sniper — content.js
 *
 * Injected on all pages of the three supported supermarket domains.
 * Detects cart pages via URL, extracts barcodes + quantities from the DOM,
 * calls the backend API, and injects a floating comparison widget.
 *
 * Since all three sites are SPAs, we also watch for URL changes via
 * MutationObserver so we catch navigations that don't trigger a full reload.
 */

// ─── Config ───────────────────────────────────────────────────────────────────

const API_KEY   = "fepVCPso5nH44S"; // Must match API_KEY in .env and background.js
const WIDGET_ID = "cart-sniper-widget";

// ─── Chain registry ───────────────────────────────────────────────────────────

const CHAINS = {
  "shufersal.co.il": {
    chain_code: "7290027600007",
    chain_name: "שופרסל",
  },
  "rami-levy.co.il": {
    chain_code: "7290058140886",
    chain_name: "רמי לוי",
  },
  "yohananof.co.il": {
    chain_code: "7290803800003",
    chain_name: "יוחננוף",
  },
};

// ─── State ────────────────────────────────────────────────────────────────────
//
// A single enum-style state variable replaces all the scattered flags.
// Transitions:
//   IDLE  →  WAITING  (run() called, waiting for cart DOM)
//   WAITING → LOADING (cart items found, API call in flight)
//   LOADING → SHOWN   (widget rendered)
//   LOADING → IDLE    (API error — error widget shown, user can retry on nav)
//   SHOWN   → DISMISSED (user pressed ×)
//   any     → IDLE    (SPA navigation detected — full reset)

const State = { IDLE: "idle", WAITING: "waiting", LOADING: "loading", SHOWN: "shown", DISMISSED: "dismissed" };
let state = State.IDLE;

function setState(next) {
  console.log(`[CartSniper] ${state} → ${next}`);
  state = next;
}

// ─── Per-item metadata scraped from the DOM ───────────────────────────────────
//
// Both maps are keyed by barcode string and reset on each extractBarcodes() call.

let domNames = {};       // barcode → display name from cart page
let domQuantities = {};  // barcode → integer quantity (default 1)

// ─── Utilities ────────────────────────────────────────────────────────────────

function getCurrentChain() {
  const hostname = window.location.hostname;
  for (const [domain, meta] of Object.entries(CHAINS)) {
    if (hostname.includes(domain)) return meta;
  }
  return null;
}

function isCartPage() {
  const url = (window.location.pathname + window.location.hash + window.location.search).toLowerCase();
  return /cart|checkout|basket|dashboard|order|עגלה|קופה/.test(url);
}

// ─── DOM helpers ─────────────────────────────────────────────────────────────

/**
 * Try to extract a human-readable product name from a cart item container.
 */
function extractNameFromContainer(el) {
  if (!el) return null;
  const candidates = [
    ".miglog-prod-name",       // Shufersal
    ".product-name",
    ".item-name",
    ".cart-product-name",
    ".cart-item-name",
    "[class*='product-name']",
    "[class*='item-name']",
    "h3", "h4",
  ];
  for (const sel of candidates) {
    const node = el.querySelector(sel);
    if (node) {
      const text = node.textContent.trim();
      if (text.length > 1) return text;
    }
  }
  const full = el.textContent.trim().split("\n")[0].trim();
  return full.length > 1 ? full : null;
}

/**
 * Try to extract the item quantity from a cart item container element.
 * Returns an integer >= 1.
 *
 * Rami Levi: the button[id^="product-"] has aria-label="... כמות 4 יחידות ..."
 *            The actual counter span (.num-span span) is a sibling of the button,
 *            so we walk up to the listitem row first.
 * Shufersal: <input class="quantity-field" type="number" value="4">
 */
function extractQtyFromContainer(el) {
  if (!el) return 1;

  // 0. Rami Levi: aria-label on the button contains "כמות N יחידות"
  const ariaLabel = el.getAttribute("aria-label") || "";
  const ariaMatch = ariaLabel.match(/כמות\s+(\d+)\s+יחידות/);
  if (ariaMatch) {
    const v = parseInt(ariaMatch[1], 10);
    if (v > 0) return v;
  }

  // Walk up to the nearest listitem / row so sibling elements are reachable
  const row = el.closest('[role="listitem"], .cart-item, .cart-product, li') || el;

  // 1. Rami Levi counter: .num-span span (plain digit inside the stepper widget)
  const numSpan = row.querySelector(".num-span span, .num-span");
  if (numSpan) {
    const v = parseInt(numSpan.textContent.trim(), 10);
    if (v > 0) return v;
  }

  // 2. Explicit quantity input field (Shufersal and generic)
  const inputSels = [
    'input[type="number"]',
    'input[class*="qty"]',
    'input[class*="quantity"]',
    'input[name*="qty"]',
    'input[name*="quantity"]',
  ];
  for (const sel of inputSels) {
    const input = row.querySelector(sel);
    if (input) {
      const v = parseInt(input.value, 10);
      if (v > 0) return v;
    }
  }

  // 3. data-quantity / data-qty attribute anywhere in the row
  for (const attr of ["data-quantity", "data-qty", "data-count", "data-amount"]) {
    const node = row.matches(`[${attr}]`) ? row : row.querySelector(`[${attr}]`);
    if (node) {
      const v = parseInt(node.getAttribute(attr), 10);
      if (v > 0) return v;
    }
  }

  // 4. Class-name heuristics for quantity text nodes
  const textCandidates = row.querySelectorAll(
    '[class*="qty"], [class*="quantity"], [class*="count"], [class*="amount"], [class*="כמות"]'
  );
  for (const node of textCandidates) {
    const v = parseInt(node.textContent.trim(), 10);
    if (v > 0) return v;
  }

  return 1;
}

// ─── Barcode + name + quantity extraction ─────────────────────────────────────

function extractBarcodes() {
  const barcodes = new Set();
  domNames = {};
  domQuantities = {};

  function register(barcode, containerEl) {
    if (!barcode || !/^\d{4,14}$/.test(barcode)) return;
    // Quantities accumulate — if the same barcode appears in multiple rows, sum them
    const qty = extractQtyFromContainer(containerEl);
    domQuantities[barcode] = (domQuantities[barcode] || 0) + qty;
    barcodes.add(barcode);
    if (containerEl && !domNames[barcode]) {
      const name = extractNameFromContainer(containerEl);
      if (name) domNames[barcode] = name;
    }
  }

  function addCode(raw, containerEl) {
    if (!raw) return;
    const stripped = String(raw).replace(/^[^0-9]+/, "").trim();
    register(stripped, containerEl);
  }

  // Strategy 1 (Shufersal): article.miglog-incart[data-product-code]
  // The real EAN is embedded in the product image filename, not data-product-code.
  const cartArticles = document.querySelectorAll("article.miglog-incart[data-product-code]");
  const allArticles  = document.querySelectorAll("article[data-product-code]");
  const articles     = cartArticles.length > 0 ? cartArticles : allArticles;
  articles.forEach((el) => {
    const img = el.querySelector("img[src]");
    if (img) {
      const match = img.getAttribute("src").match(/_P_(\d{7,14})(?:_\d+)?\./);
      if (match) { register(match[1], el); return; }
    }
    addCode(el.getAttribute("data-product-code"), el);
  });

  // Strategy 2 (Rami Levi): button[id^="product-"]
  // Walk up to the listitem row so extractQtyFromContainer can reach the
  // sibling .checkout-cart-plus-minus counter (.num-span span).
  document.querySelectorAll('button[id^="product-"]').forEach((el) => {
    const raw = el.id.replace(/^product-/, "");
    const row = el.closest('[role="listitem"]') || el;
    register(raw, row);
  });

  // Strategies 3+ are only used when neither Shufersal nor Rami Levi patterns
  // matched anything — i.e. we're on Yohananof or an unknown site layout.
  // Running them unconditionally causes false positives on Shufersal/Rami Levi
  // where promotions, recommendations, and coupons also carry numeric IDs.
  if (barcodes.size === 0) {

    // Strategy 3 (Yohananof / generic): common data attributes
    for (const attr of [
      "data-barcode", "data-sku", "data-item-barcode", "data-product-barcode",
      "data-itemcode", "data-item-id", "data-product-id", "data-catalog-id",
      "data-item-code", "data-product-code-barcode",
    ]) {
      document.querySelectorAll(`[${attr}]`).forEach((el) => addCode(el.getAttribute(attr), el));
    }

    // Strategy 3a (Yohananof image fallback): _P_<EAN> in image filenames
    document.querySelectorAll(
      '.cart-item img[src], .cart-product img[src], [class*="cart"] img[src], [class*="basket"] img[src]'
    ).forEach((img) => {
      const match = (img.getAttribute("src") || "").match(/_P_(\d{7,14})(?:_\d+)?\./);
      if (match) {
        const container = img.closest('[class*="cart-item"], [class*="cart-product"], [class*="basket-item"]') || img.parentElement;
        register(match[1], container);
      }
    });

    // Strategy 4 (Shufersal fallback): hidden form inputs + data-product buttons
    document.querySelectorAll('input[name="productCodePost"]').forEach((el) => addCode(el.value, null));
    document.querySelectorAll("[data-product]").forEach((el) => addCode(el.getAttribute("data-product"), el));

    // Strategy 5: numeric barcode embedded in product URLs (last resort, no qty/name)
    document.querySelectorAll("a[href]").forEach((el) => {
      const match = (el.getAttribute("href") || "").match(/[/\-_](\d{4,14})(?:[/?#]|$)/);
      if (match) barcodes.add(match[1]);
    });

  }

  const result = Array.from(barcodes);
  console.log(`[CartSniper] extractBarcodes() found ${result.length} barcode(s):`, result);
  console.log("[CartSniper] quantities:", domQuantities);
  console.log("[CartSniper] DOM names:", domNames);
  if (result.length === 0) {
    console.warn(
      "[CartSniper] No barcodes found. Debug in DevTools:\n" +
      "  // Shufersal:\n" +
      "  document.querySelectorAll('article[data-product-code]')\n" +
      "  // Rami Levi:\n" +
      "  document.querySelectorAll('button[id^=\"product-\"]')\n" +
      "  // Yohananof — try:\n" +
      "  document.querySelectorAll('[data-barcode],[data-sku],[class*=\"cart-item\"]')\n" +
      "  // Also check img src for _P_<EAN> pattern"
    );
  }
  return result;
}

// ─── Cart DOM readiness ───────────────────────────────────────────────────────

function cartItemsPresent() {
  if (document.querySelectorAll("article.miglog-incart[data-product-code]").length > 0) return true;
  if (document.querySelectorAll("article[data-product-code]").length > 0) return true;
  if (document.querySelectorAll('input[name="productCodePost"]').length > 0) return true;
  if (document.querySelectorAll('button[id^="product-"]').length > 0) return true;
  if (document.querySelectorAll("[data-barcode]").length > 0) return true;
  if (document.querySelectorAll('[class*="cart-item"], [class*="cart-product"], [class*="basket-item"]').length > 0) return true;
  return false;
}

function waitForCartItems(timeoutMs) {
  return new Promise((resolve) => {
    if (cartItemsPresent()) { resolve(true); return; }
    const start = Date.now();
    const iv = setInterval(() => {
      if (cartItemsPresent()) {
        clearInterval(iv);
        setTimeout(() => resolve(true), 300);
      } else if (Date.now() - start >= timeoutMs) {
        clearInterval(iv);
        resolve(false);
      }
    }, 200);
  });
}

// ─── Widget ───────────────────────────────────────────────────────────────────

function removeWidget() {
  document.getElementById(WIDGET_ID)?.remove();
}

function showLoadingWidget() {
  removeWidget();
  const w = document.createElement("div");
  w.id = WIDGET_ID;
  w.className = "cart-sniper-widget cart-sniper-loading";
  w.innerHTML = `
    <div class="cs-header"><span class="cs-logo">Cart Sniper</span></div>
    <div class="cs-body"><span class="cs-spinner"></span> בודק מחירים...</div>
  `;
  document.body.appendChild(w);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Resolve the best display name for an item, in priority order:
 *   1. product_name from the backend (products table)
 *   2. domNames scraped from the cart page
 *   3. null → caller shows raw barcode
 */
function resolveItemName(item) {
  if (item.product_name) return item.product_name;
  if (domNames[item.barcode]) return domNames[item.barcode];
  return null;
}

function showResultWidget(data) {
  removeWidget();
  const w = document.createElement("div");
  w.id = WIDGET_ID;
  w.className = "cart-sniper-widget";

  if (!data.cheapest_chain) {
    w.innerHTML = `
      <div class="cs-header">
        <span class="cs-logo">Cart Sniper</span>
        <button class="cs-close" aria-label="סגור">&times;</button>
      </div>
      <div class="cs-body cs-nomatch">לא נמצאו מוצרים תואמים בשרשראות אחרות.</div>
    `;
  } else {
    const { cheapest_chain, source_chain, matched_count, total_count, items = [], chains = [] } = data;

    // ── Helper: render a single chain row ──────────────────────────────────
    const OPTION_LABEL = { delivery: "משלוח", pickup: "איסוף" };

    function renderChainRow(chain, extraClass) {
      const shippingHtml = chain.shipping.map((s) => {
        const label = OPTION_LABEL[s.option_type] || s.option_type;
        if (s.unavailable) {
          const feeStr = s.fee === 0 ? "חינם" : `&#x20AA;${s.fee.toFixed(0)}`;
          return `<span class="cs-ship-opt cs-ship-unavail">${label}: <span class="cs-ship-fee">${feeStr} (מינימום לא הושג)</span></span>`;
        }
        const feeStr = s.fee === 0 ? "חינם" : `+&#x20AA;${s.fee.toFixed(0)}`;
        const withFee = s.fee === 0
          ? chain.items_total.toFixed(2)
          : (chain.items_total + s.fee).toFixed(2);
        return `<span class="cs-ship-opt">${label}: <strong>&#x20AA;${withFee}</strong> <span class="cs-ship-fee">(${feeStr})</span></span>`;
      }).join("");

      return `
        <div class="cs-chain-row${extraClass ? ` ${extraClass}` : ""}">
          <div class="cs-chain-top">
            <span class="cs-chain-name">${escapeHtml(chain.chain_name)}</span>
            <span class="cs-chain-total">&#x20AA;${chain.items_total.toFixed(2)}</span>
          </div>
          ${shippingHtml ? `<div class="cs-chain-shipping">${shippingHtml}</div>` : ""}
        </div>`;
    }

    // ── Source chain row (current store, shown above competitors) ──────────
    const sourceRowHtml = source_chain
      ? renderChainRow(source_chain, "cs-chain-source")
      : "";

    // ── Per-chain comparison table ──────────────────────────────────────────
    // Sort chains by items_total ascending so cheapest is first
    const sortedChains = [...chains].sort((a, b) => a.items_total - b.items_total);
    const chainRowsHtml = sortedChains.map((chain, i) =>
      renderChainRow(chain, i === 0 ? "cs-chain-cheapest" : "")
    ).join("");

    // ── Per-item breakdown ──────────────────────────────────────────────────
    const itemRowsHtml = items.map((item) => {
      const name = resolveItemName(item);
      const nameHtml = name
        ? escapeHtml(name)
        : `<span class="cs-barcode">${escapeHtml(item.barcode)}</span>`;
      const qty = item.quantity || domQuantities[item.barcode] || 1;
      const qtyBadge = qty > 1 ? ` <span class="cs-qty">×${qty}</span>` : "";

      if (item.matched) {
        const lineTotal = item.competitor_price.toFixed(2);
        const unitNote  = qty > 1
          ? ` <span class="cs-unit-price">&#x20AA;${item.unit_price.toFixed(2)} ליח׳</span>`
          : "";
        return `
          <li class="cs-item cs-item-matched">
            <span class="cs-item-name">${nameHtml}${qtyBadge}</span>
            <span class="cs-item-price">&#x20AA;${lineTotal}${unitNote}</span>
          </li>`;
      } else {
        return `
          <li class="cs-item cs-item-unmatched">
            <span class="cs-item-name">${nameHtml}${qtyBadge}</span>
            <span class="cs-item-notfound">—</span>
          </li>`;
      }
    }).join("");

    w.innerHTML = `
      <div class="cs-header">
        <span class="cs-logo">Cart Sniper</span>
        <button class="cs-close" aria-label="סגור">&times;</button>
      </div>
      <div class="cs-body">
        <div class="cs-label">${matched_count}/${total_count} פריטים זוהו</div>
        ${sourceRowHtml ? `<div class="cs-chains">${sourceRowHtml}</div><div class="cs-chains-divider"></div>` : ""}
        <div class="cs-chains">${chainRowsHtml}</div>
        ${items.length > 0 ? `
        <details class="cs-details">
          <summary class="cs-details-toggle">פירוט פריטים</summary>
          <ul class="cs-item-list">${itemRowsHtml}</ul>
        </details>` : ""}
      </div>
    `;
  }

  document.body.appendChild(w);
  w.querySelector(".cs-close")?.addEventListener("click", () => {
    removeWidget();
    setState(State.DISMISSED);
  });
}

function showErrorWidget(message) {
  removeWidget();
  const w = document.createElement("div");
  w.id = WIDGET_ID;
  w.className = "cart-sniper-widget cs-error-widget";
  w.innerHTML = `
    <div class="cs-header">
      <span class="cs-logo">Cart Sniper</span>
      <button class="cs-close" aria-label="סגור">&times;</button>
    </div>
    <div class="cs-body cs-error">${message}</div>
  `;
  document.body.appendChild(w);
  w.querySelector(".cs-close")?.addEventListener("click", () => {
    removeWidget();
    setState(State.DISMISSED);
  });
}

// ─── API call (via background service worker to bypass mixed-content) ─────────

async function fetchComparison(chainCode, barcodes, quantities) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: "COMPARE_CART", source_chain_code: chainCode, barcodes, quantities },
      (response) => {
        if (chrome.runtime.lastError) { reject(new Error(chrome.runtime.lastError.message)); return; }
        if (!response?.ok) { reject(new Error(response?.error || "Unknown error from background")); return; }
        resolve(response.data);
      }
    );
  });
}

// ─── Main run logic ───────────────────────────────────────────────────────────

async function run() {
  if (state !== State.IDLE) return;

  const chain = getCurrentChain();
  if (!chain || !isCartPage()) { removeWidget(); return; }

  setState(State.WAITING);

  const ready = await waitForCartItems(8000);
  if (!ready) {
    console.warn("[CartSniper] Cart items did not appear within timeout.");
    setState(State.IDLE);
    return;
  }

  if (state !== State.WAITING) return;

  const barcodes = extractBarcodes(); // also populates domQuantities + domNames
  if (barcodes.length === 0) {
    setState(State.IDLE);
    return;
  }

  setState(State.LOADING);
  showLoadingWidget();

  try {
    const data = await fetchComparison(chain.chain_code, barcodes, domQuantities);
    if (state !== State.LOADING) return;
    showResultWidget(data);
    setState(State.SHOWN);
  } catch (err) {
    console.error("[CartSniper] API call failed:", err);
    if (state !== State.LOADING) return;
    showErrorWidget("שגיאה בטעינת הנתונים. האם השרת פועל?");
    setState(State.IDLE);
  }
}

// ─── SPA navigation detection ─────────────────────────────────────────────────

let debounceTimer = null;

function scheduleRun() {
  setState(State.IDLE);
  removeWidget();
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(run, 300);
}

(function patchHistory() {
  const _push    = history.pushState.bind(history);
  const _replace = history.replaceState.bind(history);
  history.pushState    = function (...args) { _push(...args);    scheduleRun(); };
  history.replaceState = function (...args) { _replace(...args); scheduleRun(); };
})();

window.addEventListener("popstate", scheduleRun);

let lastUrl = window.location.href;

const observer = new MutationObserver(() => {
  const currentUrl = window.location.href;
  if (currentUrl !== lastUrl) {
    lastUrl = currentUrl;
    scheduleRun();
    return;
  }
  if (state === State.IDLE && isCartPage() && cartItemsPresent()) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(run, 300);
  }
});

observer.observe(document.body, { childList: true, subtree: true });

// ─── Initial run ─────────────────────────────────────────────────────────────
run();
