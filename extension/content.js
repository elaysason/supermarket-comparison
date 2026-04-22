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
//   IDLE  →  WAITING  (run() called, waiting for carWDt DOM)
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
    <div class="cs-body">
      <div class="cs-loading-shell">
        <span class="cs-spinner"></span>
        <div>
          <div class="cs-state-title">בודק מחירים...</div>
          <div class="cs-state-copy">משווה את העגלה מול הרשתות הנתמכות.</div>
        </div>
      </div>
    </div>
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

function formatCurrencyHtml(value) {
  return `&#x20AA;${Number(value).toFixed(2)}`;
}

function formatCurrencyText(value) {
  return `₪${Number(value).toFixed(2)}`;
}

const HEBREW_CHAIN_NAMES = {
  Shufersal: "שופרסל",
  "Rami Levi": "רמי לוי",
  Yohananof: "יוחננוף",
};

function toDisplayChainName(name) {
  return HEBREW_CHAIN_NAMES[name] || name;
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

function getOrderGapText(chain, optionType = null) {
  if (!chain?.shipping?.length) return null;

  const relevantOptions = optionType
    ? chain.shipping.filter((option) => option.option_type === optionType)
    : chain.shipping;

  let smallestGap = null;
  for (const option of relevantOptions) {
    if (!option.unavailable || option.min_order == null) continue;
    const gap = Number((option.min_order - chain.items_total).toFixed(2));
    if (gap <= 0) continue;
    if (smallestGap == null || gap < smallestGap) smallestGap = gap;
  }

  return smallestGap == null ? null : `חסרים ${formatCurrencyText(smallestGap)} למינימום`;
}

function getDisplayTotal(chain) {
  return chain.order_total ?? chain.items_total;
}

function getComparisonModeLabel(optionType) {
  if (optionType === "delivery") return "משלוח";
  if (optionType === "pickup") return "איסוף";
  return "הזמנה";
}

function getUnavailableBadgeText(optionType) {
  if (!optionType) return "לא זמין להזמנה";
  return `לא זמין ב${getComparisonModeLabel(optionType)}`;
}

function getUnavailableNoteText(optionType) {
  if (!optionType) return "לא זמין כרגע להזמנה";
  return `לא זמין כרגע ב${getComparisonModeLabel(optionType)}`;
}

function getSummaryMarkup(lowestItemsChain, cheapestChain, sourceChain, comparisonOptionType) {
  const sourceTotal = sourceChain?.order_total ?? null;
  const competitorName = escapeHtml(toDisplayChainName(cheapestChain.chain_name));
  const competitorTotal = formatCurrencyHtml(cheapestChain.total_price);
  const comparisonModeLabel = getComparisonModeLabel(comparisonOptionType);
  const rawLowestHtml = lowestItemsChain && lowestItemsChain.chain_code !== cheapestChain.chain_code
    ? `<div class="cs-summary-raw">סל המוצרים הזול ביותר: <strong>${escapeHtml(toDisplayChainName(lowestItemsChain.chain_name))}</strong> ${formatCurrencyHtml(lowestItemsChain.items_total)}</div>`
    : "";

  if (!sourceChain || sourceTotal == null) {
    return `
      <div class="cs-summary">
        <div class="cs-summary-kicker">הכי זול ב${comparisonModeLabel}</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">${competitorName}</span>
          <span class="cs-summary-total">${competitorTotal}</span>
        </div>
        ${rawLowestHtml}
      </div>`;
  }

  const delta = Number((sourceTotal - cheapestChain.total_price).toFixed(2));

  if (Math.abs(delta) < 0.005) {
    return `
      <div class="cs-summary cs-summary-neutral">
        <div class="cs-summary-kicker">השוואת ${comparisonModeLabel}</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">אין פער כרגע</span>
          <span class="cs-summary-total">${competitorTotal}</span>
        </div>
        <div class="cs-summary-copy">העגלה שלך ו-${competitorName} באותו מחיר ב${comparisonModeLabel}.</div>
        ${rawLowestHtml}
      </div>`;
  }

  if (delta < 0) {
    return `
      <div class="cs-summary cs-summary-win">
        <div class="cs-summary-kicker">העגלה שלך עדיפה</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">${escapeHtml(toDisplayChainName(sourceChain.chain_name))}</span>
          <span class="cs-summary-total">${formatCurrencyHtml(sourceTotal)}</span>
        </div>
        <div class="cs-summary-copy">${competitorName} יקר יותר ב${comparisonModeLabel} ב-${formatCurrencyHtml(Math.abs(delta))}.</div>
        ${rawLowestHtml}
      </div>`;
  }

  return `
    <div class="cs-summary">
      <div class="cs-summary-kicker">הכי זול ב${comparisonModeLabel}</div>
      <div class="cs-summary-main">
        <span class="cs-summary-title">${competitorName}</span>
        <span class="cs-summary-total">${competitorTotal}</span>
      </div>
      <div class="cs-summary-copy">חוסך ${formatCurrencyHtml(delta)} מול ${escapeHtml(toDisplayChainName(sourceChain.chain_name))} ב${comparisonModeLabel}.</div>
      ${rawLowestHtml}
    </div>`;
}

function getUnavailableSummaryMarkup(lowestItemsChain, comparisonOptionType) {
  const comparisonModeLabel = getComparisonModeLabel(comparisonOptionType);
  if (!lowestItemsChain) {
    return `
      <div class="cs-summary cs-summary-muted">
        <div class="cs-summary-kicker">זמינות ${comparisonModeLabel}</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">אין כרגע רשת זמינה</span>
        </div>
        <div class="cs-summary-copy">מצאנו מחירים, אבל אין כרגע רשת שניתן להשוות בה ${comparisonModeLabel}.</div>
      </div>`;
  }

  const gapText = getOrderGapText(lowestItemsChain, comparisonOptionType);
  return `
    <div class="cs-summary cs-summary-muted">
      <div class="cs-summary-kicker">סל המוצרים הזול ביותר כרגע</div>
      <div class="cs-summary-main">
        <span class="cs-summary-title">${escapeHtml(toDisplayChainName(lowestItemsChain.chain_name))}</span>
        <span class="cs-summary-total cs-summary-total-muted">${formatCurrencyHtml(lowestItemsChain.items_total)}</span>
      </div>
      <div class="cs-summary-copy">אי אפשר להזמין כרגע ב${comparisonModeLabel}.${gapText ? ` ${escapeHtml(gapText)}.` : ""}</div>
    </div>`;
}

function showResultWidget(data) {
  removeWidget();
  const w = document.createElement("div");
  w.id = WIDGET_ID;
  w.className = "cart-sniper-widget";
  const {
    comparison_option_type,
    cheapest_chain,
    source_chain,
    matched_count,
    total_count,
    items = [],
    chains = [],
  } = data;

  if (!cheapest_chain && chains.length === 0) {
    w.innerHTML = `
      <div class="cs-header">
        <span class="cs-logo">Cart Sniper</span>
        <button class="cs-close" aria-label="סגור">&times;</button>
      </div>
      <div class="cs-body cs-nomatch">
        <div class="cs-state-title">לא נמצאה השוואה זמינה</div>
        <div class="cs-state-copy">זיהינו את העגלה, אבל לא נמצאו כרגע מוצרים תואמים ברשתות האחרות.</div>
      </div>
    `;
  } else {
    const lowestItemsChain = chains.length > 0
      ? [...chains].sort((a, b) => a.items_total - b.items_total)[0]
      : null;
    const lowestOrderableChain = chains.length > 0
      ? [...chains]
        .filter((chain) => chain.order_total != null)
        .sort((a, b) => a.order_total - b.order_total)[0] || null
      : null;
    const summaryHtml = cheapest_chain
      ? getSummaryMarkup(lowestItemsChain, cheapest_chain, source_chain, comparison_option_type)
      : getUnavailableSummaryMarkup(lowestItemsChain, comparison_option_type);

    // ── Helper: render a single chain row ──────────────────────────────────
    const OPTION_LABEL = { delivery: "משלוח", pickup: "איסוף" };

    function renderChainRow(chain, options = {}) {
      const { isCheapest = false, isSource = false } = options;
      const isUnavailable = chain.order_total == null;
      const orderGapText = getOrderGapText(chain, comparison_option_type);
      const primaryOption = comparison_option_type
        ? chain.shipping.find((option) => option.option_type === comparison_option_type)
        : null;
      const alternateOptions = comparison_option_type
        ? chain.shipping.filter((option) => option.option_type !== comparison_option_type)
        : chain.shipping;
      const rowClass = [
        "cs-chain-row",
        isCheapest ? "cs-chain-cheapest" : "",
        isSource ? "cs-chain-source" : "",
        isUnavailable ? "cs-chain-unavailable" : "",
      ].filter(Boolean).join(" ");
      const badges = [
        isSource ? '<span class="cs-chain-badge cs-chain-badge-source">העגלה שלך</span>' : "",
        isCheapest && !isSource ? '<span class="cs-chain-badge cs-chain-badge-cheapest">הכי זול להזמנה</span>' : "",
        !isCheapest && !isSource && lowestItemsChain?.chain_code === chain.chain_code
          ? '<span class="cs-chain-badge cs-chain-badge-lowest">סל המוצרים הזול ביותר</span>'
          : "",
        !isSource && isUnavailable ? `<span class="cs-chain-badge cs-chain-badge-unavailable">${getUnavailableBadgeText(comparison_option_type)}</span>` : "",
      ].filter(Boolean).join("");
      const badgesHtml = badges ? `<div class="cs-chain-badges">${badges}</div>` : "";
      function renderOption(s, isPrimary = false) {
        const label = OPTION_LABEL[s.option_type] || s.option_type;
        if (s.unavailable) {
          const feeStr = s.fee === 0 ? "חינם" : formatCurrencyHtml(s.fee);
          const gap = s.min_order != null ? Number((s.min_order - chain.items_total).toFixed(2)) : null;
          const gapHtml = gap && gap > 0 ? ` <span class="cs-ship-gap">חסרים ${formatCurrencyHtml(gap)}</span>` : "";
          return `<span class="cs-ship-opt${isPrimary ? " cs-ship-opt-primary" : ""} cs-ship-unavail">${label}: <span class="cs-ship-fee">${feeStr} (מינימום לא הושג)</span>${gapHtml}</span>`;
        }
        const feeStr = s.fee === 0 ? "חינם" : `+${formatCurrencyHtml(s.fee)}`;
        const withFee = s.fee === 0 ? chain.items_total : chain.items_total + s.fee;
        return `<span class="cs-ship-opt${isPrimary ? " cs-ship-opt-primary" : ""}">${label}: <strong>${formatCurrencyHtml(withFee)}</strong> <span class="cs-ship-fee">(${feeStr})</span></span>`;
      }

      const unavailableNoteHtml = isUnavailable
        ? `<div class="cs-chain-unavailable-note">${getUnavailableNoteText(comparison_option_type)}.${orderGapText ? ` ${escapeHtml(orderGapText)}.` : ""}</div>`
        : "";
      const primaryModeHtml = !isUnavailable && primaryOption
        ? `<div class="cs-chain-primary-mode">${renderOption(primaryOption, true)}</div>`
        : "";
      const alternateHtml = !isUnavailable && alternateOptions.length > 0
        ? `<div class="cs-chain-alt-modes">${alternateOptions.map((option) => renderOption(option)).join("")}</div>`
        : "";

      return `
        <div class="${rowClass}">
          <div class="cs-chain-top">
            <div class="cs-chain-heading">
              <span class="cs-chain-name">${escapeHtml(toDisplayChainName(chain.chain_name))}</span>
              ${badgesHtml}
            </div>
            <div class="cs-chain-total-wrap">
              <span class="cs-chain-total-label">${isUnavailable ? (isSource ? "סל מוצרים בעגלה שלך" : "סל מוצרים") : isSource ? `סה"כ ${getComparisonModeLabel(comparison_option_type)} לעגלה שלך` : `סה"כ ${getComparisonModeLabel(comparison_option_type)}`}</span>
              <span class="cs-chain-total">${formatCurrencyHtml(getDisplayTotal(chain))}</span>
            </div>
          </div>
          ${unavailableNoteHtml}
          ${primaryModeHtml}
          ${alternateHtml}
        </div>`;
    }

    // ── Source chain row (current store, shown above competitors) ──────────
    const sourceRowHtml = source_chain
      ? renderChainRow(source_chain, { isSource: true })
      : "";

    // ── Per-chain comparison table ──────────────────────────────────────────
    // Keep the selected cheapest available chain first, then other orderable
    // chains, then chains whose minimum order has not been reached.
    const sortedChains = [...chains].sort((a, b) => {
      const aIsLowestItems = lowestItemsChain?.chain_code === a.chain_code;
      const bIsLowestItems = lowestItemsChain?.chain_code === b.chain_code;
      const aIsCheapest = cheapest_chain?.chain_code === a.chain_code;
      const bIsCheapest = cheapest_chain?.chain_code === b.chain_code;
      if (aIsCheapest !== bIsCheapest) return aIsCheapest ? -1 : 1;

      const aAvailable = a.order_total != null;
      const bAvailable = b.order_total != null;
      if (aAvailable !== bAvailable) return aAvailable ? -1 : 1;

      const aIsLowestOrderable = lowestOrderableChain?.chain_code === a.chain_code;
      const bIsLowestOrderable = lowestOrderableChain?.chain_code === b.chain_code;
      if (aIsLowestOrderable !== bIsLowestOrderable) return aIsLowestOrderable ? -1 : 1;
      if (aIsLowestItems !== bIsLowestItems) return aIsLowestItems ? -1 : 1;

      return getDisplayTotal(a) - getDisplayTotal(b);
    });
    const chainRowsHtml = sortedChains.map((chain) =>
      renderChainRow(chain, { isCheapest: cheapest_chain?.chain_code === chain.chain_code })
    ).join("");
    const detailsChainName = cheapest_chain?.chain_name || lowestItemsChain?.chain_name;
    const detailsLabel = detailsChainName
      ? `פריטים מול ${escapeHtml(toDisplayChainName(detailsChainName))} (${matched_count}/${total_count} נמצאו)`
      : `פירוט פריטים (${matched_count}/${total_count} נמצאו)`;

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
        ${summaryHtml}
        ${sourceRowHtml ? `<div class="cs-section-label">העגלה שלך</div><div class="cs-chains">${sourceRowHtml}</div>` : ""}
        <div class="cs-section-label">רשתות להשוואה</div>
        <div class="cs-chains">${chainRowsHtml}</div>
        ${items.length > 0 ? `
        <details class="cs-details">
          <summary class="cs-details-toggle">${detailsLabel}</summary>
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
    <div class="cs-body cs-error">
      <div class="cs-state-title">טעינת ההשוואה נכשלה</div>
      <div class="cs-state-copy">${escapeHtml(message)}</div>
    </div>
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
