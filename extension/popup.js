/**
 * Cart Sniper — popup.js
 *
 * Queries the active tab to determine whether the extension is active
 * (i.e. the current page is a supported supermarket cart page).
 */

const SUPPORTED_DOMAINS = [
  "shufersal.co.il",
  "rami-levy.co.il",
  "yochananof.co.il",
  "hazi-hinam.co.il",
];

const CART_PATTERN = /cart|checkout|basket|dashboard|order|עגלה|קופה/i;

const CHAIN_NAMES = {
  "shufersal.co.il": "שופרסל",
  "rami-levy.co.il": "רמי לוי",
  "yochananof.co.il": "יוחננוף",
  "hazi-hinam.co.il": "חצי חינם",
};

function renderSupportedChains(activeDomain) {
  const ul = document.getElementById("store-list");
  if (!ul) return;
  ul.innerHTML = SUPPORTED_DOMAINS.map((domain) => {
    const name = CHAIN_NAMES[domain] || domain;
    const isActive = domain === activeDomain;
    const status = isActive ? "פעיל" : "נתמך";
    const itemClass = isActive ? "store-item store-item-active" : "store-item";
    return `<li class="${itemClass}"><span class="store-name">${name}</span><span class="store-status">${status}</span></li>`;
  }).join("");
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

  function setStatus({ state, dotClass, statusText, statusTone, siteLabel, statusDescription }) {
    card.dataset.state = state;
    dot.className = dotClass;
    text.textContent = statusText;
    tone.textContent = statusTone;
    label.textContent = siteLabel || "";
    description.textContent = statusDescription;
  }

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab || !tab.url) {
      setStatus({
        state: "error",
        dotClass: "dot-error",
        statusText: "לא ניתן לקרוא את הכרטיסייה",
        statusTone: "שגיאה",
        siteLabel: "",
        statusDescription: "הדפדפן לא סיפק כתובת ללשונית הפעילה כרגע.",
      });
      return;
    }

    const url = new URL(tab.url);
    const hostname = url.hostname;

    const matchedDomain = SUPPORTED_DOMAINS.find((d) => hostname.includes(d));

    // Re-render the supported list now that we know the active chain so we can
    // mark it פעיל.
    renderSupportedChains(matchedDomain);

    if (!matchedDomain) {
      setStatus({
        state: "inactive",
        dotClass: "dot-inactive",
        statusText: "לא פעיל באתר זה",
        statusTone: "לא נתמך",
        siteLabel: hostname,
        statusDescription: "סל קל פועל רק בעגלות הקניות של שופרסל, רמי לוי, יוחננוף וחצי חינם.",
      });
      return;
    }

    const chainName = CHAIN_NAMES[matchedDomain] || matchedDomain;
    const onCartPage = CART_PATTERN.test(url.pathname + url.hash + url.search);

    if (onCartPage) {
      setStatus({
        state: "active",
        dotClass: "dot-active",
        statusText: "פעיל בדף עגלה",
        statusTone: "מוכן",
        siteLabel: `${chainName} · ${hostname}`,
        statusDescription: "העמוד נתמך וההשוואה תופיע מתוך העגלה עצמה ברגע שהמוצרים יזוהו.",
      });
    } else {
      setStatus({
        state: "supported",
        dotClass: "dot-supported",
        statusText: "ממתין לדף עגלה",
        statusTone: "נתמך",
        siteLabel: `${chainName} · ${hostname}`,
        statusDescription: "האתר מזוהה. עבור לעגלת הקניות כדי להפעיל את ההשוואה האוטומטית.",
      });
    }
  } catch (err) {
    setStatus({
      state: "error",
      dotClass: "dot-error",
      statusText: "שגיאה בטעינת המצב",
      statusTone: "שגיאה",
      siteLabel: "",
      statusDescription: "אירעה בעיה בקריאת נתוני הלשונית הפעילה.",
    });
    console.error("[CartSniper popup]", err);
  }
}

init();
