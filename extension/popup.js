/**
 * Cart Sniper — popup.js
 *
 * Queries the active tab to determine whether the extension is active
 * (i.e. the current page is a supported supermarket cart page).
 */

const SUPPORTED_DOMAINS = [
  "shufersal.co.il",
  "rami-levy.co.il",
  "yohananof.co.il",
];

const CART_PATTERN = /cart|checkout|basket|dashboard|order|עגלה|קופה/i;

const CHAIN_NAMES = {
  "shufersal.co.il": "שופרסל",
  "rami-levy.co.il": "רמי לוי",
  "yohananof.co.il": "יוחננוף",
};

async function init() {
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  const label = document.getElementById("site-label");

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab || !tab.url) {
      text.textContent = "לא ניתן לקרוא את הכרטיסייה";
      return;
    }

    const url = new URL(tab.url);
    const hostname = url.hostname;

    const matchedDomain = SUPPORTED_DOMAINS.find((d) => hostname.includes(d));

    if (!matchedDomain) {
      dot.className = "dot-inactive";
      text.textContent = "לא פעיל באתר זה";
      label.textContent = hostname;
      return;
    }

    const chainName = CHAIN_NAMES[matchedDomain] || matchedDomain;
    const onCartPage = CART_PATTERN.test(url.pathname + url.hash + url.search);

    if (onCartPage) {
      dot.className = "dot-active";
      text.textContent = "פעיל — עגלת קניות";
    } else {
      dot.className = "dot-inactive";
      text.textContent = "ממתין לדף עגלה";
    }

    label.textContent = `${chainName} · ${hostname}`;
  } catch (err) {
    text.textContent = "שגיאה";
    console.error("[CartSniper popup]", err);
  }
}

init();
