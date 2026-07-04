/**
 * Sal Kal — popup.js
 *
 * Queries the active tab to determine whether the extension is active
 * (i.e. the current page is a supported supermarket cart page).
 */

const SUPPORTED_STORES = [
  {
    domain: "shufersal.co.il",
    name: "שופרסל",
    url: "https://www.shufersal.co.il/",
    cartUrl: "https://www.shufersal.co.il/online/he/cart",
  },
  {
    domain: "rami-levy.co.il",
    name: "רמי לוי",
    url: "https://www.rami-levy.co.il/",
    cartUrl: "https://www.rami-levy.co.il/he/online/cart",
  },
  {
    domain: "yochananof.co.il",
    name: "יוחננוף",
    url: "https://www.yochananof.co.il/",
    cartUrl: "https://www.yochananof.co.il/?openPopups=cart",
  },
  {
    domain: "hazi-hinam.co.il",
    name: "חצי חינם",
    url: "https://shop.hazi-hinam.co.il/",
    cartUrl: "https://shop.hazi-hinam.co.il/checkout/cart",
  },
  {
    domain: "carrefour.co.il",
    name: "קרפור",
    url: "https://www.carrefour.co.il/",
    cartUrl: "https://www.carrefour.co.il/cart",
  },
];

const SUPPORTED_DOMAINS = SUPPORTED_STORES.map((store) => store.domain);

const CART_PATTERN = /cart|checkout|basket|dashboard|order|עגלה|קופה/i;

let primaryAction = null;
let secondaryAction = null;

function getStore(domain) {
  return SUPPORTED_STORES.find((store) => store.domain === domain) || null;
}

function hostnameMatchesDomain(hostname, domain) {
  return hostname === domain || hostname.endsWith(`.${domain}`);
}

function getPageLabel(url) {
  if (url.protocol === "chrome:") return "דף פנימי של Chrome";
  if (url.protocol === "edge:") return "דף פנימי של Edge";
  if (url.protocol === "about:") return "דף פנימי של הדפדפן";
  return url.hostname || "לשונית נוכחית";
}

function isBrowserPage(url) {
  return ["chrome:", "edge:", "about:"].includes(url.protocol);
}

function renderSupportedChains(activeDomain) {
  const ul = document.getElementById("store-list");
  if (!ul) return;
  ul.innerHTML = SUPPORTED_STORES.map((store) => {
    const isActive = store.domain === activeDomain;
    const status = isActive ? "כאן" : "פתח";
    const itemClass = isActive ? "store-item store-item-active" : "store-item";
    return `<li class="${itemClass}"><button class="store-button" type="button" data-store-url="${store.url}"><span class="store-name">${store.name}</span><span class="store-status">${status}</span></button></li>`;
  }).join("");
}

function configureButton(button, action) {
  if (!button) return;

  if (!action) {
    button.hidden = true;
    button.disabled = true;
    button.textContent = "";
    return;
  }

  button.hidden = false;
  button.disabled = Boolean(action.disabled);
  button.textContent = action.label;
}

async function runAction(action) {
  if (!action || action.disabled) return;

  if (action.type === "retry") {
    await init();
    return;
  }

  if (action.type === "reload") {
    await chrome.tabs.reload(action.tabId);
    window.close();
    return;
  }

  if (action.type === "open-url") {
    await chrome.tabs.create({ url: action.url });
    window.close();
    return;
  }

  if (action.type === "go-cart") {
    if (action.tabId) {
      await chrome.tabs.update(action.tabId, { url: action.url });
    } else {
      await chrome.tabs.create({ url: action.url });
    }
    window.close();
  }
}

async function init() {
  // Render the supported-chains list immediately so it stays populated even if
  // the tab query below throws.
  renderSupportedChains(null);

  const card = document.getElementById("status-card");
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  const tone = document.getElementById("status-tone");
  const label = document.getElementById("site-label");
  const description = document.getElementById("status-description");
  const actions = document.querySelector(".status-actions");
  const primaryButton = document.getElementById("primary-action");
  const secondaryButton = document.getElementById("secondary-action");
  let activeTabId = null;

  function setStatus({ state, dotClass, statusText, statusTone, siteLabel, statusDescription, primary, secondary }) {
    card.dataset.state = state;
    card.setAttribute("role", state === "error" ? "alert" : "status");
    dot.className = dotClass;
    text.textContent = statusText;
    tone.textContent = statusTone;
    label.textContent = siteLabel || "";
    description.textContent = statusDescription;
    primaryAction = primary || null;
    secondaryAction = secondary || null;
    configureButton(primaryButton, primaryAction);
    configureButton(secondaryButton, secondaryAction);
    actions?.toggleAttribute("hidden", !primaryAction && !secondaryAction);
  }

  setStatus({
    state: "checking",
    dotClass: "dot-supported",
    statusText: "בודק את העמוד...",
    statusTone: "בדיקה",
    siteLabel: "",
    statusDescription: "אנחנו בודקים אם הלשונית הפעילה היא עגלת קניות נתמכת.",
    primary: { type: "checking", label: "בודק...", disabled: true },
  });

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    activeTabId = tab?.id || null;

    if (!tab || !tab.url) {
      setStatus({
        state: "error",
        dotClass: "dot-error",
        statusText: "לא ניתן לקרוא את הכרטיסייה",
        statusTone: "שגיאה",
        siteLabel: "",
        statusDescription: "לא הצלחנו לזהות את הלשונית הפעילה. נסה לפתוח מחדש את הפופאפ.",
        primary: { type: "retry", label: "נסה שוב" },
      });
      return;
    }

    const url = new URL(tab.url);
    const hostname = url.hostname;

    const matchedDomain = SUPPORTED_DOMAINS.find((domain) => hostnameMatchesDomain(hostname, domain));

    // Re-render the supported list now that we know the active chain so we can
    // mark it פעיל.
    renderSupportedChains(matchedDomain);

    if (!matchedDomain) {
      const browserPage = isBrowserPage(url);
      setStatus({
        state: "inactive",
        dotClass: "dot-inactive",
        statusText: browserPage ? "לא באתר קניות" : "לא באתר קניות נתמך",
        statusTone: "לא פעיל",
        siteLabel: getPageLabel(url),
        statusDescription: browserPage
          ? "זה דף של הדפדפן, לא עגלת קניות. פתח אחת מהרשתות הנתמכות מהרשימה למטה."
          : "סל קל פועל כרגע רק בעגלות של הרשתות הנתמכות. אפשר לפתוח אחת מהרשימה למטה.",
      });
      return;
    }

    const store = getStore(matchedDomain);
    const chainName = store?.name || matchedDomain;
    const onCartPage = CART_PATTERN.test(url.pathname + url.hash + url.search);

    if (onCartPage) {
      setStatus({
        state: "active",
        dotClass: "dot-active",
        statusText: "העגלה מזוהה",
        statusTone: "מוכן",
        siteLabel: `${chainName} · ${hostname}`,
        statusDescription: "ההשוואה אמורה להופיע בתוך עמוד העגלה. אם היא לא מופיעה, רענן את העמוד.",
        primary: { type: "reload", label: "רענן עמוד", tabId: tab.id },
      });
    } else {
      setStatus({
        state: "supported",
        dotClass: "dot-supported",
        statusText: "האתר נתמך",
        statusTone: "צריך עגלה",
        siteLabel: `${chainName} · ${hostname}`,
        statusDescription: "כדי להשוות מחירים, פתח את עגלת הקניות באתר זה. ננסה להעביר אותך לעמוד העגלה.",
        primary: store?.cartUrl
          ? { type: "go-cart", label: "פתח עגלה", tabId: tab.id, url: store.cartUrl }
          : { type: "reload", label: "בדוק שוב", tabId: tab.id },
        secondary: { type: "reload", label: "רענן עמוד", tabId: tab.id },
      });
    }
  } catch (err) {
    setStatus({
      state: "error",
      dotClass: "dot-error",
      statusText: "שגיאה בטעינת המצב",
      statusTone: "שגיאה",
      siteLabel: "",
      statusDescription: "לא הצלחנו לבדוק את העמוד הנוכחי. נסה שוב או רענן את הלשונית.",
      primary: { type: "retry", label: "נסה שוב" },
      secondary: activeTabId ? { type: "reload", label: "רענן עמוד", tabId: activeTabId } : null,
    });
    console.error("[SalKal popup]", err);
  }
}

document.getElementById("primary-action")?.addEventListener("click", () => {
  runAction(primaryAction).catch((err) => {
    console.error("[SalKal popup action]", err);
  });
});

document.getElementById("secondary-action")?.addEventListener("click", () => {
  runAction(secondaryAction).catch((err) => {
    console.error("[SalKal popup action]", err);
  });
});

document.getElementById("store-list")?.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest(".store-button");
  if (!button?.dataset.storeUrl) return;
  runAction({ type: "open-url", url: button.dataset.storeUrl }).catch((err) => {
    console.error("[SalKal popup store]", err);
  });
});

init();
