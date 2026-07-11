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
const MAX_COMPARE_BARCODES = 100;

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
  "hazi-hinam.co.il": {
    chain_code: "7290700100008",
    chain_name: "חצי חינם",
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
let lastCartSignature = null;
let runVersion = 0;

// ─── Utilities ────────────────────────────────────────────────────────────────

function getCurrentChain() {
  const hostname = window.location.hostname;
  for (const [domain, meta] of Object.entries(CHAINS)) {
    if (hostname.includes(domain)) return meta;
  }
  return null;
}

function getOpenPopupNames() {
  return new Set(
    new URLSearchParams(window.location.search)
      .getAll("openPopups")
      .map((value) => String(value).split(";")[0])
      .filter(Boolean)
  );
}

function isYochananofCheckoutView() {
  if (!window.location.hostname.includes("yochananof.co.il")) return false;
  if (window.location.pathname.toLowerCase().startsWith("/checkout")) return true;
  return Boolean(document.querySelector('[data-aria-desc="dialog_order_summary"]'));
}

function isYochananofCartView() {
  if (!window.location.hostname.includes("yochananof.co.il")) return false;
  if (isYochananofCheckoutView()) return false;

  const openPopups = getOpenPopupNames();
  return openPopups.has("cart") || document.querySelectorAll('[data-aria-desc="cart_item"]').length > 0;
}

function isHaziHinamCartView() {
  if (!window.location.hostname.includes("hazi-hinam.co.il")) return false;
  if (window.location.pathname.toLowerCase().startsWith("/checkout/cart")) return true;

  const drawer = document.querySelector("app-my-cart");
  if (!drawer) return false;
  const rows = drawer.querySelectorAll("app-product-strip-new");
  return Array.from(rows).some((row) => {
    const rect = row.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });
}

function isCartPage() {
  if (window.location.hostname.includes("yochananof.co.il")) {
    return isYochananofCartView();
  }
  if (window.location.hostname.includes("hazi-hinam.co.il")) {
    return isHaziHinamCartView();
  }
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

  // Prefer Yohananof's explicit cart row wrapper when present, otherwise fall
  // back to the generic list/cart row containers.
  const yohananofRow = el.matches?.('[data-aria-desc="cart_item"]')
    ? el
    : el.closest('[data-aria-desc="cart_item"]');
  const row = yohananofRow || el.closest('[role="listitem"], .cart-item, .cart-product, li') || el;

  function extractYohananofReactQty(node) {
    const reactInternals = Object.getOwnPropertyNames(node)
      .filter((key) => key.startsWith("__reactFiber$") || key.startsWith("__reactProps$"))
      .map((key) => node[key])
      .filter(Boolean);
    if (reactInternals.length === 0) return null;

    function getCartItemQuantity(candidate) {
      if (!candidate || typeof candidate !== "object") return null;

      const item = candidate.item && typeof candidate.item === "object"
        ? candidate.item
        : candidate;
      const quantity = Number(item.quantity);
      if (!Number.isInteger(quantity) || quantity < 1) return null;

      const product = item.product;
      if (!product || typeof product !== "object") return null;

      const sku = String(product.sku || "").trim();
      const imageUrl = String(product.image?.url || "").trim();
      const name = String(product.name || "").trim();
      const hasCartIdentity =
        /^\d{4,14}$/.test(sku) ||
        /\d{6,14}_s\d+_/i.test(imageUrl) ||
        name.length > 1;

      return hasCartIdentity ? quantity : null;
    }

    const queue = [...reactInternals];
    const seen = new WeakSet();
    let inspected = 0;

    while (queue.length > 0 && inspected < 40) {
      const current = queue.shift();
      if (!current || typeof current !== "object" || seen.has(current)) continue;

      seen.add(current);
      inspected += 1;

      for (const candidate of [current.memoizedProps, current.pendingProps, current]) {
        const quantity = getCartItemQuantity(candidate);
        if (quantity) return quantity;
      }

      if (current.return && typeof current.return === "object") queue.push(current.return);
      if (current.alternate && typeof current.alternate === "object") queue.push(current.alternate);
    }

    return null;
  }

  // 1. Yohananof cart counter: explicit amount button inside cart row
  const yohananofCounters = Array.from(
    row.querySelectorAll('[data-aria-desc="button_product_counter_amount"]')
  );
  if (yohananofCounters.length > 0) {
    const visibleCounters = yohananofCounters.filter((node) => {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    });
    const quantityNodes = visibleCounters.length > 0 ? visibleCounters : yohananofCounters;
    const values = quantityNodes
      .map((node) => parseInt(node.textContent.trim(), 10))
      .filter((value) => value > 0);
    if (values.length > 0) return Math.max(...values);
  }

  // 1a. Yohananof React props/fiber fallback: the live row component carries
  // the cart item object with `quantity` even when the visible DOM does not.
  if (yohananofRow) {
    const reactQty = extractYohananofReactQty(row);
    if (reactQty) return reactQty;
  }

  // 2. Rami Levi counter: .num-span span (plain digit inside the stepper widget)
  const numSpan = row.querySelector(".num-span span, .num-span");
  if (numSpan) {
    const v = parseInt(numSpan.textContent.trim(), 10);
    if (v > 0) return v;
  }

  // 3. Explicit quantity input field (Shufersal and generic)
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

  // 4. data-quantity / data-qty attribute anywhere in the row
  for (const attr of ["data-quantity", "data-qty", "data-count", "data-amount"]) {
    const node = row.matches(`[${attr}]`) ? row : row.querySelector(`[${attr}]`);
    if (node) {
      const v = parseInt(node.getAttribute(attr), 10);
      if (v > 0) return v;
    }
  }

  // 5. Class-name heuristics for quantity text nodes
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

function buildCartSignature(barcodes, quantities) {
  return [...barcodes]
    .sort()
    .map((barcode) => `${barcode}:${quantities[barcode] || 1}`)
    .join("|");
}

async function collectCartSnapshot({ log = true } = {}) {
  const barcodes = new Set();
  const names = {};
  const quantities = {};
  const hostname = window.location.hostname;

  function register(barcode, containerEl) {
    if (!barcode || !/^\d{4,14}$/.test(barcode)) return;
    // Quantities accumulate — if the same barcode appears in multiple rows, sum them
    const qty = extractQtyFromContainer(containerEl);
    quantities[barcode] = (quantities[barcode] || 0) + qty;
    barcodes.add(barcode);
    if (containerEl && !names[barcode]) {
      const name = extractNameFromContainer(containerEl);
      if (name) names[barcode] = name;
    }
  }

  function addCode(raw, containerEl) {
    if (!raw) return;
    const stripped = String(raw).replace(/^[^0-9]+/, "").trim();
    register(stripped, containerEl);
  }

  function extractCodeFromImageSource(source) {
    if (!source) return null;

    const decoded = decodeURIComponent(source);
    const patterns = [
      /(?:^|\/)(\d{6,14})_s\d+_[^/?#]+\.(?:jpg|jpeg|png|webp)/i,
      /_P_(\d{7,14})(?:_\d+)?\./i,
    ];

    for (const pattern of patterns) {
      const match = decoded.match(pattern);
      if (match) return match[1];
    }

    return null;
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

  // Strategy 2a (Yohananof cart drawer): use the live cart row itself, which
  // already exposes both the barcode image and the working quantity sources.
  if (hostname.includes("yochananof.co.il") && barcodes.size === 0) {
    document.querySelectorAll('[data-aria-desc="cart_item"]').forEach((row) => {
      const images = row.querySelectorAll('img[src], img[srcset]');
      for (const img of images) {
        const candidates = [img.currentSrc, img.getAttribute("src"), img.getAttribute("srcset")];
        const code = candidates.map(extractCodeFromImageSource).find(Boolean);
        if (code) {
          register(code, row);
          break;
        }
      }
    });
  }

  // Strategy 2b (Hazi Hinam): scope to checkout-cart or my-cart wrapper to
  // exclude category recommendations (app-product-cube-new outside cart).
  // EAN sits in the Cloudinary image URL: /Production/<EAN>/<EAN>_P...jpg
  if (hostname.includes("hazi-hinam.co.il") && barcodes.size === 0) {
    const cartScopes = document.querySelectorAll("app-checkout-cart, app-my-cart");
    cartScopes.forEach((scope) => {
      scope.querySelectorAll("app-product-strip-new").forEach((row) => {
        const images = row.querySelectorAll("img[src]");
        for (const img of images) {
          const src = img.getAttribute("src") || "";
          const match = src.match(/\/Production\/(\d{7,14})\//);
          if (match) {
            register(match[1], row);
            break;
          }
        }
      });
    });
  }

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

  const snapshot = {
    barcodes: Array.from(barcodes),
    names,
    quantities,
  };
  snapshot.signature = buildCartSignature(snapshot.barcodes, snapshot.quantities);

  if (log) {
    console.log(`[CartSniper] extractBarcodes() found ${snapshot.barcodes.length} barcode(s):`, snapshot.barcodes);
    console.log("[CartSniper] quantities:", snapshot.quantities);
    console.log("[CartSniper] DOM names:", snapshot.names);
  }
  if (log && snapshot.barcodes.length === 0) {
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
  return snapshot;
}

function applyCartSnapshot(snapshot) {
  domNames = snapshot.names;
  domQuantities = snapshot.quantities;
}

async function extractBarcodes() {
  const snapshot = await collectCartSnapshot();
  applyCartSnapshot(snapshot);
  return snapshot.barcodes;
}

// ─── Cart DOM readiness ───────────────────────────────────────────────────────

function cartItemsPresent() {
  if (window.location.hostname.includes("yochananof.co.il")) {
    return isYochananofCartView();
  }
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
    <div class="cs-header">${getLogoMarkup()}</div>
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
  "Hazi Hinam": "חצי חינם",
  Carrefour: "קרפור",
};

function getLogoMarkup() {
  return `<img class="cs-logo" src="${chrome.runtime.getURL("icons/sal_kal_v1-cropped.png")}" alt="סל קל">`;
}

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

function getOptionGapText(chain, option) {
  if (!option?.unavailable || option.min_order == null) return null;

  const gap = Number((option.min_order - chain.items_total).toFixed(2));
  if (gap <= 0) return null;
  return `חסרים ${formatCurrencyText(gap)} למינימום`;
}

function getOptionGapBadgeText(chain, option) {
  if (!option?.unavailable || option.min_order == null) return null;

  const gap = Number((option.min_order - chain.items_total).toFixed(2));
  if (gap <= 0) return null;
  return `חסרים ${formatCurrencyText(gap)}`;
}

function getDisplayTotal(chain) {
  return chain.order_total ?? chain.items_total;
}

function getOrderBreakdown(chain, optionType) {
  if (!optionType) return null;

  const option = chain.shipping.find((shippingOption) => shippingOption.option_type === optionType);
  if (!option || option.unavailable || chain.order_total == null) return null;

  return {
    optionType,
    fee: option.fee,
    total: chain.order_total,
    feeLabel: option.fee === 0 ? "חינם" : formatCurrencyHtml(option.fee),
  };
}

function getOptionTotal(chain, option) {
  if (!option) return null;
  return Number((chain.items_total + option.fee).toFixed(2));
}

function getBestAvailableAlternateOption(chain, optionType) {
  const alternateOptions = optionType
    ? chain.shipping.filter((option) => option.option_type !== optionType)
    : chain.shipping;

  const availableOption = alternateOptions.find((option) => !option.unavailable);
  if (availableOption) return availableOption;

  return alternateOptions.find((option) => option.min_order != null) || alternateOptions[0] || null;
}

function getAlternateOptionTotal(chain, option) {
  return getOptionTotal(chain, option);
}

function getAlternateOptionInfo(chain, optionType) {
  const option = getBestAvailableAlternateOption(chain, optionType);
  if (!option) return null;

  return {
    option,
    total: getAlternateOptionTotal(chain, option),
    gapText: getOptionGapText(chain, option),
  };
}

function getCheapestOverallChain(sourceChain, chains) {
  const eligibleChains = [sourceChain, ...chains].filter((chain) => chain?.order_total != null);
  if (eligibleChains.length === 0) return null;

  return eligibleChains.sort((a, b) => a.order_total - b.order_total)[0];
}

function getLowestItemsChain(sourceChain, chains) {
  const comparableChains = [sourceChain, ...chains].filter(Boolean);
  if (comparableChains.length === 0) return null;

  return comparableChains.sort((a, b) => a.items_total - b.items_total)[0];
}

function getComparisonModeLabel(optionType) {
  if (optionType === "delivery") return "משלוח";
  if (optionType === "pickup") return "איסוף";
  return "הזמנה";
}

function isPartialComparison(matchedCount, totalCount) {
  return Boolean(totalCount) && matchedCount < totalCount;
}

function getComparisonScopeText(matchedCount, totalCount) {
  if (!totalCount) return "לא נמצאו פריטים להשוואה.";
  if (!isPartialComparison(matchedCount, totalCount)) return `כל ${totalCount} הפריטים הושוו.`;
  return `השוואה חלקית: ${matchedCount} מתוך ${totalCount} פריטים בעגלה נכללו בהשוואה.`;
}

function getComparisonScopeShortText(matchedCount, totalCount) {
  if (!totalCount) return null;
  return `${matchedCount}/${totalCount} פריטים בהשוואה`;
}

function formatDateTime(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("he-IL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatShortDateTime(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("he-IL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getFreshnessText(lastUpdated) {
  const formatted = formatDateTime(lastUpdated);
  return formatted ? `המחירים עודכנו לאחרונה: ${formatted}` : "אין מידע על עדכון המחירים האחרון.";
}

function getFreshnessShortText(lastUpdated) {
  const formatted = formatShortDateTime(lastUpdated);
  return formatted ? `עודכן ${formatted}` : "אין תאריך עדכון";
}

function getFreshnessClass(chains) {
  if (chains.some((chain) => chain.status === "stale_strong_warning")) return "cs-summary-freshness cs-summary-freshness-strong";
  if (chains.some((chain) => chain.status === "stale_warning")) return "cs-summary-freshness cs-summary-freshness-warn";
  return "cs-summary-freshness";
}

function getFreshnessPillClass(chains, lastUpdated) {
  if (!lastUpdated) return "cs-header-freshness cs-header-freshness-missing";
  if (chains.some((chain) => chain.status === "stale_strong_warning")) return "cs-header-freshness cs-header-freshness-strong";
  if (chains.some((chain) => chain.status === "stale_warning")) return "cs-header-freshness cs-header-freshness-warn";
  return "cs-header-freshness";
}

function getBlockedChainText(chain) {
  if (chain.status === "blocked_stale") return "נתוני המחירים ישנים מדי ולכן הרשת לא נכללה בהשוואה.";
  return "אין כרגע נתוני מחירים עדכניים ולכן הרשת לא נכללה בהשוואה.";
}

function getRecommendationBlockMarkup(status, matchedCount, totalCount) {
  if (status === "low_coverage") {
    return `
      <div class="cs-summary cs-summary-muted cs-summary-blocked">
        <div class="cs-summary-kicker">אין מספיק מידע להשוואה אמינה</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">לא מוצגת המלצה</span>
        </div>
        <div class="cs-summary-copy">רק ${matchedCount} מתוך ${totalCount} פריטים נמצאו להשוואה בין הרשתות.</div>
      </div>`;
  }
  if (status === "stale_blocked") {
    return `
      <div class="cs-summary cs-summary-muted cs-summary-blocked">
        <div class="cs-summary-kicker">בעיה בעדכון המחירים</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">לא ניתן להשוות כרגע</span>
        </div>
        <div class="cs-summary-copy">לא הצלחנו להגיע לנתוני מחירים עדכניים מספיק לרשת הנוכחית.</div>
      </div>`;
  }
  if (status === "no_comparison") {
    return `
      <div class="cs-summary cs-summary-muted cs-summary-blocked">
        <div class="cs-summary-kicker">לא נמצאו מוצרים להשוואה</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">לא מוצגת השוואה</span>
        </div>
        <div class="cs-summary-copy">לא נמצאו מספיק מוצרים משותפים בין הרשתות כדי לחשב סל אמין.</div>
      </div>`;
  }
  if (status === "not_enough_chains") {
    return `
      <div class="cs-summary cs-summary-muted cs-summary-blocked">
        <div class="cs-summary-kicker">אין מספיק רשתות זמינות</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">לא מוצגת השוואה</span>
        </div>
        <div class="cs-summary-copy">צריך לפחות שתי רשתות עם מחירים עדכניים כדי להציג השוואה.</div>
      </div>`;
  }
  return null;
}

function getUnavailablePrimaryDisplay(chain, optionType) {
  // When the primary option (e.g. delivery) has a minimum order gap, always
  // show the cart total with the gap — even if an alternate option (e.g.
  // pickup) is available.  This keeps the display consistent across all
  // chains that can't meet the delivery minimum.
  const selectedOption = chain.shipping.find((option) => option.option_type === optionType);
  if (selectedOption && getOptionGapText(chain, selectedOption)) {
    return {
      label: "סל ההשוואה",
      total: chain.items_total,
    };
  }

  const alternateInfo = getAlternateOptionInfo(chain, optionType);

  if (alternateInfo?.total != null) {
    const modeLabel = getComparisonModeLabel(alternateInfo.option.option_type);
    return {
      label: `סה"כ ${modeLabel}`,
      total: alternateInfo.total,
    };
  }

  return {
    label: "סל ההשוואה",
    total: chain.items_total,
  };
}

function makeUnavailableSourceChain(activeChain) {
  return {
    chain_code: activeChain.chain_code,
    chain_name: activeChain.chain_name,
    items_total: 0,
    order_total: null,
    matched_count: 0,
    shipping: [],
    _unavailable_reason: "no_prices",
  };
}

function getChainDisplayModel(chain, optionType, isSource = false, matchedCount = 0, totalCount = 0) {
  // Active chain has no price data at all — render a minimal "no data" row
  // with the agreed reason text. No total, no badge, no shipping breakdown.
  if (chain._unavailable_reason === "no_prices") {
    return {
      isUnavailable: true,
      label: "",
      total: null,
      supportingText: "לא נמצאו מחירים תואמים לפריטים שנבחרו",
      badgeText: null,
    };
  }

  if (chain.status === "blocked_stale" || chain.status === "no_data") {
    return {
      isUnavailable: true,
      label: "",
      total: null,
      supportingText: chain.status === "blocked_stale"
        ? "נתוני המחירים של הרשת ישנים מדי להשוואה."
        : "אין כרגע נתוני מחירים עדכניים לרשת הזו.",
      badgeText: chain.status === "blocked_stale" ? "מחירים חסומים" : "אין נתונים",
    };
  }

  const isUnavailable = chain.order_total == null;
  const modeLabel = getComparisonModeLabel(optionType);
  const primaryLabel = `סה"כ ${modeLabel}`;
  const label = isPartialComparison(matchedCount, totalCount)
    ? `${primaryLabel} להשוואה`
    : isSource
      ? `${primaryLabel} לעגלה שלך`
      : primaryLabel;

  if (!isUnavailable) {
    return {
      isUnavailable: false,
      label,
      total: getDisplayTotal(chain),
      supportingText: getRowSupportingText(chain, optionType, matchedCount, totalCount),
      badgeText: null,
    };
  }

  const unavailablePrimaryDisplay = getUnavailablePrimaryDisplay(chain, optionType);
  const unavailableLabel = isPartialComparison(matchedCount, totalCount) && unavailablePrimaryDisplay.label.startsWith("סה\"כ ")
    ? `${unavailablePrimaryDisplay.label} להשוואה`
    : unavailablePrimaryDisplay.label;

  return {
    isUnavailable: true,
    label: unavailableLabel,
    total: unavailablePrimaryDisplay.total,
    supportingText: getRowSupportingText(chain, optionType, matchedCount, totalCount),
    badgeText: getUnavailableBadgeText(chain, optionType),
  };
}

function getUnavailableSecondaryText(chain, optionType) {
  if (!optionType) return null;

  const selectedOption = chain.shipping.find((option) => option.option_type === optionType);
  if (!selectedOption) return `אין ${getComparisonModeLabel(optionType)}`;

  const gapText = getOptionGapText(chain, selectedOption);
  return gapText || `${getComparisonModeLabel(optionType)} לא זמין כרגע`;
}

function getRowSupportingText(chain, optionType, matchedCount = 0, totalCount = 0) {
  if (!optionType) {
    return `סל ההשוואה ${formatCurrencyHtml(chain.items_total)}`;
  }

  const modeLabel = getComparisonModeLabel(optionType);
  const selectedOption = chain.shipping.find((option) => option.option_type === optionType);
  const orderBreakdown = getOrderBreakdown(chain, optionType);
  if (orderBreakdown) {
    return `סל ${formatCurrencyHtml(chain.items_total)} + ${modeLabel} ${orderBreakdown.feeLabel}`;
  }

  const parts = [];
  const alternateInfo = getAlternateOptionInfo(chain, optionType);
  const selectedModeLabel = getComparisonModeLabel(optionType);

  // When the primary option has a minimum order gap, show its breakdown
  // consistently — even if an alternate option is available.  This keeps
  // Carrefour (delivery + pickup) looking the same as Hazi Hinam
  // (delivery only) when both are below the delivery minimum.
  if (selectedOption && getOptionGapText(chain, selectedOption)) {
    parts.push(`סל ${formatCurrencyHtml(chain.items_total)} + ${modeLabel} ${selectedOption.fee === 0 ? "חינם" : formatCurrencyHtml(selectedOption.fee)}`);
    parts.push(getOptionGapText(chain, selectedOption));
    return parts.join(" · ");
  }

  if (alternateInfo?.total != null) {
    const alternateModeLabel = getComparisonModeLabel(alternateInfo.option.option_type);
    parts.push(`סל ${formatCurrencyHtml(chain.items_total)} + ${alternateModeLabel} ${alternateInfo.option.fee === 0 ? "חינם" : formatCurrencyHtml(alternateInfo.option.fee)}`);

    const unavailableSecondaryText = getUnavailableSecondaryText(chain, optionType);
    if (unavailableSecondaryText) parts.push(unavailableSecondaryText);

    return parts.join(" · ");
  }

  if (selectedOption) {
    parts.push(`סל ${formatCurrencyHtml(chain.items_total)} + ${modeLabel} ${selectedOption.fee === 0 ? "חינם" : formatCurrencyHtml(selectedOption.fee)}`);

    const unavailableSecondaryText = getUnavailableSecondaryText(chain, optionType);
    if (unavailableSecondaryText) parts.push(unavailableSecondaryText);
  } else {
    parts.push(`אין ${modeLabel}`);
  }

  if (alternateInfo?.total != null) {
    parts.push(`ב${getComparisonModeLabel(alternateInfo.option.option_type)} ${formatCurrencyHtml(alternateInfo.total)}${alternateInfo.gapText ? `, ${alternateInfo.gapText}` : ""}`);
  }

  return parts.join(" · ");
}

function getAlternateModeNote(chain, optionType) {
  const alternateInfo = getAlternateOptionInfo(chain, optionType);
  if (!alternateInfo) return null;

  if (!alternateInfo.option.unavailable) {
    return `זמין רק ב${getComparisonModeLabel(alternateInfo.option.option_type)}.`;
  }

  return alternateInfo.gapText
    ? `ב${getComparisonModeLabel(alternateInfo.option.option_type)} ${alternateInfo.gapText}.`
    : "הרשת זמינה רק באפשרויות אחרות.";
}

function getUnavailableBadgeText(chain, optionType) {
  if (!optionType) return "לא זמין להזמנה";

  // Prioritize showing the minimum-order gap for the primary option (e.g.
  // delivery) so all chains below the minimum look the same, regardless of
  // whether an alternate option like pickup exists.
  const selectedOption = chain.shipping.find((option) => option.option_type === optionType);
  if (selectedOption && getOptionGapText(chain, selectedOption)) {
    return getOptionGapBadgeText(chain, selectedOption) || "מינימום לא הושג";
  }

  const alternateInfo = getAlternateOptionInfo(chain, optionType);
  if (alternateInfo?.gapText) return getOptionGapBadgeText(chain, alternateInfo.option) || "מינימום לא הושג";
  if (alternateInfo?.total != null && !alternateInfo.option.unavailable) return `${getComparisonModeLabel(alternateInfo.option.option_type)} בלבד`;

  if (!selectedOption) return `אין ${getComparisonModeLabel(optionType)}`;
  return `לא זמין ב${getComparisonModeLabel(optionType)}`;
}

function getUnavailableNoteText(chain, optionType) {
  if (!optionType) return "לא זמין כרגע להזמנה.";

  const selectedModeLabel = getComparisonModeLabel(optionType);
  const selectedOption = chain.shipping.find((option) => option.option_type === optionType);

  if (!selectedOption) {
    const alternateModeNote = getAlternateModeNote(chain, optionType);
    return alternateModeNote
      ? `אין ${selectedModeLabel} ברשת הזו. ${alternateModeNote}`
      : `אין ${selectedModeLabel} ברשת הזו.`;
  }

  const gapText = getOptionGapText(chain, selectedOption);
  if (gapText) return `לא זמין כרגע ב${selectedModeLabel}. ${gapText}.`;

  return `לא זמין כרגע ב${selectedModeLabel}.`;
}

function getSummaryMarkup(lowestItemsChain, cheapestOverallChain, cheapestCompetitor, sourceChain, comparisonOptionType, matchedCount, totalCount) {
  const sourceTotal = sourceChain?.order_total ?? null;
  const winnerName = escapeHtml(toDisplayChainName(cheapestOverallChain.chain_name));
  const winnerTotal = formatCurrencyHtml(cheapestOverallChain.order_total ?? cheapestOverallChain.total_price);
  const comparisonModeLabel = getComparisonModeLabel(comparisonOptionType);
  const comparisonScopeText = getComparisonScopeText(matchedCount, totalCount);
  const rawLowestHtml = lowestItemsChain && lowestItemsChain.chain_code !== cheapestOverallChain.chain_code
    ? `<div class="cs-summary-raw">סל ההשוואה הזול ביותר: <strong>${escapeHtml(toDisplayChainName(lowestItemsChain.chain_name))}</strong> ${formatCurrencyHtml(lowestItemsChain.items_total)}</div>`
    : "";
  const scopeHtml = comparisonScopeText ? `<div class="cs-summary-scope">${comparisonScopeText}</div>` : "";

  if (!sourceChain || sourceTotal == null) {
    return `
      <div class="cs-summary">
        <div class="cs-summary-kicker">הכי זול ב${comparisonModeLabel}</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">${winnerName}</span>
          <span class="cs-summary-total">${winnerTotal}</span>
        </div>
        ${scopeHtml}
        ${rawLowestHtml}
      </div>`;
  }

  const compareTarget = cheapestOverallChain.chain_code === sourceChain.chain_code
    ? cheapestCompetitor
    : cheapestOverallChain;

  if (!compareTarget) {
    return `
      <div class="cs-summary cs-summary-win">
        <div class="cs-summary-kicker">העגלה שלך עדיפה</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">${escapeHtml(toDisplayChainName(sourceChain.chain_name))}</span>
          <span class="cs-summary-total">${formatCurrencyHtml(sourceTotal)}</span>
        </div>
        <div class="cs-summary-copy">העגלה שלך היא האפשרות היחידה שזמינה כרגע ב${comparisonModeLabel}.</div>
        ${scopeHtml}
        ${rawLowestHtml}
      </div>`;
  }

  const compareTargetTotal = compareTarget.order_total ?? compareTarget.total_price;
  const compareTargetName = escapeHtml(toDisplayChainName(compareTarget.chain_name));
  const delta = Number((sourceTotal - compareTargetTotal).toFixed(2));

  if (Math.abs(delta) < 0.005) {
    return `
      <div class="cs-summary cs-summary-neutral">
        <div class="cs-summary-kicker">השוואת ${comparisonModeLabel}</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">אין פער כרגע</span>
          <span class="cs-summary-total">${formatCurrencyHtml(compareTargetTotal)}</span>
        </div>
        <div class="cs-summary-copy">העגלה שלך ו-${compareTargetName} באותו מחיר ב${comparisonModeLabel}.</div>
        ${scopeHtml}
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
        <div class="cs-summary-copy">${compareTargetName} יקר יותר ב${comparisonModeLabel} ב-${formatCurrencyHtml(Math.abs(delta))}.</div>
        ${scopeHtml}
        ${rawLowestHtml}
      </div>`;
  }

  return `
    <div class="cs-summary">
      <div class="cs-summary-kicker">הכי זול ב${comparisonModeLabel}</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">${compareTargetName}</span>
          <span class="cs-summary-total">${formatCurrencyHtml(compareTargetTotal)}</span>
        </div>
        <div class="cs-summary-copy">חוסך ${formatCurrencyHtml(delta)} מול ${escapeHtml(toDisplayChainName(sourceChain.chain_name))} ב${comparisonModeLabel}.</div>
        ${scopeHtml}
        ${rawLowestHtml}
      </div>`;
}

function getUnavailableSummaryMarkup(lowestItemsChain, comparisonOptionType, matchedCount, totalCount) {
  const comparisonModeLabel = getComparisonModeLabel(comparisonOptionType);
  const comparisonScopeText = getComparisonScopeText(matchedCount, totalCount);
  const scopeHtml = comparisonScopeText ? `<div class="cs-summary-scope">${comparisonScopeText}</div>` : "";
  if (!lowestItemsChain) {
    return `
      <div class="cs-summary cs-summary-muted">
        <div class="cs-summary-kicker">זמינות ${comparisonModeLabel}</div>
        <div class="cs-summary-main">
          <span class="cs-summary-title">אין כרגע רשת זמינה</span>
        </div>
        <div class="cs-summary-copy">מצאנו מחירים, אבל אין כרגע רשת שניתן להשוות בה ${comparisonModeLabel}.</div>
        ${scopeHtml}
      </div>`;
  }

  return `
    <div class="cs-summary cs-summary-muted">
      <div class="cs-summary-kicker">סל ההשוואה הזול ביותר כרגע</div>
      <div class="cs-summary-main">
        <span class="cs-summary-title">${escapeHtml(toDisplayChainName(lowestItemsChain.chain_name))}</span>
        <span class="cs-summary-total cs-summary-total-muted">${formatCurrencyHtml(lowestItemsChain.items_total)}</span>
      </div>
      <div class="cs-summary-copy">${escapeHtml(getUnavailableNoteText(lowestItemsChain, comparisonOptionType))}</div>
      ${scopeHtml}
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
    recommendation_status = "available",
    overall_last_updated,
    items = [],
    chains = [],
    blocked_chains = [],
  } = data;

  // Always present the active chain in the widget. When the API returns no
  // source data (chain has no matching prices in our DB), synthesize a stub
  // row that displays the agreed reason text, so the user never sees a
  // recommendation without seeing where their current chain stands.
  const activeChain = getCurrentChain();
  const effectiveSourceChain =
    source_chain || (activeChain ? makeUnavailableSourceChain(activeChain) : null);
  const sourceIsUnavailable =
    effectiveSourceChain?._unavailable_reason === "no_prices";

  if (!cheapest_chain && chains.length === 0 && !effectiveSourceChain) {
    w.innerHTML = `
      <div class="cs-header">
        ${getLogoMarkup()}
        <button class="cs-close" aria-label="סגור">&times;</button>
      </div>
      <div class="cs-body cs-nomatch">
        <div class="cs-state-title">לא נמצאה השוואה זמינה</div>
        <div class="cs-state-copy">זיהינו את העגלה, אבל לא נמצאו כרגע מוצרים תואמים ברשתות האחרות.</div>
      </div>
    `;
  } else {
    const lowestItemsChain = getLowestItemsChain(effectiveSourceChain, chains);
    const lowestOrderableChain = chains.length > 0
      ? [...chains]
        .filter((chain) => chain.order_total != null)
        .sort((a, b) => a.order_total - b.order_total)[0] || null
      : null;
    const cheapestOverallChain = sourceIsUnavailable
      ? null
      : getCheapestOverallChain(effectiveSourceChain, chains);
    const visibleChains = [effectiveSourceChain, ...chains].filter(Boolean);
    const blockedSummaryHtml = getRecommendationBlockMarkup(recommendation_status, matched_count, total_count);
    const summaryHtml = blockedSummaryHtml || (cheapestOverallChain
      ? getSummaryMarkup(lowestItemsChain, cheapestOverallChain, cheapest_chain, effectiveSourceChain, comparison_option_type, matched_count, total_count)
      : getUnavailableSummaryMarkup(lowestItemsChain, comparison_option_type, matched_count, total_count));
    const freshnessPillHtml = `<span class="${getFreshnessPillClass(visibleChains, overall_last_updated)}" title="${escapeHtml(getFreshnessText(overall_last_updated))}">${escapeHtml(getFreshnessShortText(overall_last_updated))}</span>`;

    function renderChainRow(chain, options = {}) {
      const { isSource = false, isOverallCheapest = false } = options;
      const displayModel = getChainDisplayModel(
        chain,
        comparison_option_type,
        isSource,
        matched_count,
        total_count,
      );
      const { isUnavailable, supportingText } = displayModel;
      const rowClass = [
        "cs-chain-row",
        isOverallCheapest ? "cs-chain-cheapest" : "",
        isSource ? "cs-chain-source" : "",
        isUnavailable ? "cs-chain-unavailable" : "",
      ].filter(Boolean).join(" ");
      const isBlockedChain = chain.status === "blocked_stale" || chain.status === "no_data";
      const badges = [
        isOverallCheapest
          ? '<span class="cs-chain-badge cs-chain-badge-cheapest">הכי זול להזמנה</span>'
          : "",
        chain.status === "stale_strong_warning" ? '<span class="cs-chain-badge cs-chain-badge-unavailable">מחירים ישנים</span>' : "",
        chain.status === "stale_warning" ? '<span class="cs-chain-badge">מחירים לא מהיום</span>' : "",
        isBlockedChain ? `<span class="cs-chain-badge cs-chain-badge-unavailable">${displayModel.badgeText}</span>` : "",
        !isBlockedChain && !isSource && displayModel.badgeText ? `<span class="cs-chain-badge cs-chain-badge-unavailable">${displayModel.badgeText}</span>` : "",
      ].filter(Boolean).join("");
      const badgesHtml = badges ? `<div class="cs-chain-badges">${badges}</div>` : "";
      const supportingHtml = supportingText
        ? `<div class="cs-chain-supporting">${supportingText}</div>`
        : "";

      const totalWrapHtml = displayModel.total != null
        ? `
            <div class="cs-chain-total-wrap">
              <span class="cs-chain-total-label">${displayModel.label}</span>
              <span class="cs-chain-total">${formatCurrencyHtml(displayModel.total)}</span>
            </div>`
        : "";

      return `
        <div class="${rowClass}">
          <div class="cs-chain-top">
            <div class="cs-chain-heading">
              <span class="cs-chain-name">${escapeHtml(toDisplayChainName(chain.chain_name))}</span>
              ${badgesHtml}
            </div>${totalWrapHtml}
          </div>
          ${supportingHtml}
        </div>`;
    }

    // ── Source chain row (current store, shown above competitors) ──────────
    const sourceRowHtml = effectiveSourceChain
      ? renderChainRow(effectiveSourceChain, {
        isSource: true,
        isOverallCheapest: cheapestOverallChain?.chain_code === effectiveSourceChain.chain_code,
      })
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
      renderChainRow(chain, {
        isOverallCheapest: cheapestOverallChain?.chain_code === chain.chain_code,
      })
    ).join("");
    const blockedRowsHtml = blocked_chains.map((chain) => {
      const updatedText = formatDateTime(chain.last_updated);
      return `
        <div class="cs-chain-row cs-chain-unavailable">
          <div class="cs-chain-top">
            <div class="cs-chain-heading">
              <span class="cs-chain-name">${escapeHtml(toDisplayChainName(chain.chain_name))}</span>
              <div class="cs-chain-badges"><span class="cs-chain-badge cs-chain-badge-unavailable">לא נכללה</span></div>
            </div>
          </div>
          <div class="cs-chain-supporting">${getBlockedChainText(chain)}${updatedText ? ` עדכון אחרון: ${escapeHtml(updatedText)}` : ""}</div>
        </div>`;
    }).join("");
    const detailsChainName = cheapest_chain?.chain_name || lowestItemsChain?.chain_name;
    const detailsLabel = detailsChainName
      ? `פריטים מול ${escapeHtml(toDisplayChainName(detailsChainName))}`
      : "פירוט פריטים";

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

    const comparisonScopeShortText = getComparisonScopeShortText(matched_count, total_count);
    const headerMetaHtml = comparisonScopeShortText
      ? `<div class="cs-header-meta"><span class="cs-header-scope">${comparisonScopeShortText}</span>${freshnessPillHtml}</div>`
      : `<div class="cs-header-meta">${freshnessPillHtml}</div>`;

    w.innerHTML = `
      <div class="cs-header">
        ${getLogoMarkup()}
        ${headerMetaHtml}
        <button class="cs-close" aria-label="סגור">&times;</button>
      </div>
      <div class="cs-body">
        ${summaryHtml}
        ${sourceRowHtml ? `<div class="cs-section-label">העגלה שלך</div><div class="cs-chains">${sourceRowHtml}</div>` : ""}
        ${chains.length > 0 ? `<div class="cs-section-label">רשתות להשוואה</div>
        <div class="cs-chains">${chainRowsHtml}</div>` : ""}
        ${blockedRowsHtml ? `<div class="cs-section-label">רשתות שלא נכללו</div><div class="cs-chains">${blockedRowsHtml}</div>` : ""}
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
      ${getLogoMarkup()}
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
    const timeout = setTimeout(() => {
      reject(new Error("Extension background request timed out."));
    }, 20000);

    console.log("[CartSniper] Sending compare request:", {
      source_chain_code: chainCode,
      barcodes,
      quantities,
      item_names: domNames,
    });

    chrome.runtime.sendMessage(
      {
        type: "COMPARE_CART",
        source_chain_code: chainCode,
        barcodes,
        quantities,
        item_names: domNames,
      },
      (response) => {
        clearTimeout(timeout);
        if (chrome.runtime.lastError) {
          console.error("[CartSniper] Background message failed:", chrome.runtime.lastError.message);
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (!response?.ok) {
          console.error("[CartSniper] Background compare failed:", response);
          reject(new Error(response?.error || "Unknown error from background"));
          return;
        }
        console.log("[CartSniper] Compare response:", response.data);
        resolve(response.data);
      }
    );
  });
}

// ─── Main run logic ───────────────────────────────────────────────────────────

async function run() {
  if (state !== State.IDLE) return;

  const runId = ++runVersion;

  const chain = getCurrentChain();
  if (!chain || !isCartPage()) {
    lastCartSignature = null;
    removeWidget();
    return;
  }

  setState(State.WAITING);

  const ready = await waitForCartItems(8000);
  if (runId !== runVersion) return;
  if (!ready) {
    console.warn("[CartSniper] Cart items did not appear within timeout.");
    lastCartSignature = null;
    setState(State.IDLE);
    return;
  }

  if (state !== State.WAITING || runId !== runVersion) return;

  const snapshot = await collectCartSnapshot();
  applyCartSnapshot(snapshot);
  lastCartSignature = snapshot.signature;

  if (snapshot.barcodes.length === 0) {
    setState(State.IDLE);
    return;
  }
  if (snapshot.barcodes.length > MAX_COMPARE_BARCODES) {
    showErrorWidget("זוהו יותר מדי פריטים בעגלה. נסו לרענן את העמוד ולפתוח את העגלה בלבד.");
    setState(State.IDLE);
    return;
  }

  setState(State.LOADING);
  showLoadingWidget();

  try {
    const data = await fetchComparison(
      chain.chain_code,
      snapshot.barcodes,
      snapshot.quantities,
    );
    if (runId !== runVersion || state !== State.LOADING) return;

    const latestSnapshot = await collectCartSnapshot({ log: false });
    if (latestSnapshot.signature !== snapshot.signature) {
      lastCartSignature = latestSnapshot.signature;
      scheduleRun();
      return;
    }

    applyCartSnapshot(latestSnapshot);
    showResultWidget(data);
    setState(State.SHOWN);
  } catch (err) {
    console.error("[CartSniper] API call failed:", err);
    if (runId !== runVersion || state !== State.LOADING) return;
    showErrorWidget(
      err instanceof Error
        ? err.message
        : "שגיאה בטעינת הנתונים. נסו שוב בעוד רגע."
    );
    setState(State.SHOWN);
  }
}

// ─── SPA navigation detection ─────────────────────────────────────────────────

let debounceTimer = null;
let cartCheckTimer = null;
let lastUrl = window.location.href;

function scheduleRun() {
  runVersion += 1;
  setState(State.IDLE);
  removeWidget();
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(run, 300);
}

function scheduleRunIfUrlChanged() {
  const currentUrl = window.location.href;
  if (currentUrl === lastUrl) return;
  lastUrl = currentUrl;
  lastCartSignature = null;
  scheduleRun();
}

function scheduleCartCheck() {
  if (state === State.DISMISSED) return;

  clearTimeout(cartCheckTimer);
  cartCheckTimer = setTimeout(async () => {
    if (state === State.DISMISSED || state === State.LOADING || !isCartPage()) return;

    if (!cartItemsPresent()) {
      if (lastCartSignature !== null) {
        lastCartSignature = null;
        scheduleRun();
      }
      return;
    }

    const snapshot = await collectCartSnapshot({ log: false });
    if (snapshot.signature !== lastCartSignature) {
      lastCartSignature = snapshot.signature;
      scheduleRun();
      return;
    }
  }, 300);
}

(function patchHistory() {
  const _push    = history.pushState.bind(history);
  const _replace = history.replaceState.bind(history);
  history.pushState    = function (...args) { _push(...args);    scheduleRunIfUrlChanged(); };
  history.replaceState = function (...args) { _replace(...args); scheduleRunIfUrlChanged(); };
})();

window.addEventListener("popstate", scheduleRunIfUrlChanged);

const observer = new MutationObserver((mutations) => {
  if (mutations.every((mutation) => {
    const target = mutation.target instanceof Element ? mutation.target : mutation.target?.parentElement;
    return target?.closest?.(`#${WIDGET_ID}`);
  })) {
    return;
  }

  const currentUrl = window.location.href;
  if (currentUrl !== lastUrl) {
    lastUrl = currentUrl;
    lastCartSignature = null;
    scheduleRun();
    return;
  }
  scheduleCartCheck();
});

observer.observe(document.body, { childList: true, subtree: true });

// ─── Initial run ─────────────────────────────────────────────────────────────
run();
