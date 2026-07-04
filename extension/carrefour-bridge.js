(function () {
  if (window.__cartSniperCarrefourBridgeLoaded) return;
  window.__cartSniperCarrefourBridgeLoaded = true;

  const SOURCE = "cart-sniper-carrefour-bridge";
  const REQUEST_SOURCE = "cart-sniper-content";

  function asBarcode(value) {
    const rawValue = value && typeof value === "object" ? value.raw || value.value : value;
    const barcode = String(rawValue || "").trim();
    return /^\d{8,14}$/.test(barcode) ? barcode : null;
  }

  function findBarcodeDeep(value, parentKey = "", depth = 0, seen = new WeakSet()) {
    if (value == null || depth > 4) return null;

    const barcodeKeyPattern = /barcode|bar.?code|ean|upc|sku|gs1|external.?id|item.?code/i;
    const keyLooksLikeBarcode = barcodeKeyPattern.test(parentKey);
    if (typeof value !== "object") {
      return keyLooksLikeBarcode ? asBarcode(value) : null;
    }

    if (seen.has(value)) return null;
    seen.add(value);

    if (Array.isArray(value)) {
      for (const item of value) {
        const barcode = findBarcodeDeep(item, parentKey, depth + 1, seen);
        if (barcode) return barcode;
      }
      return null;
    }

    for (const key of [
      "localBarcode",
      "barcode",
      "barCode",
      "ean",
      "eanCode",
      "gs1ProductId",
      "externalId",
      "upc",
      "sku",
      "itemCode",
      "productCode",
    ]) {
      const barcode = asBarcode(value[key]);
      if (barcode) return barcode;
    }

    for (const [key, nestedValue] of Object.entries(value)) {
      const barcode = findBarcodeDeep(nestedValue, key, depth + 1, seen);
      if (barcode) return barcode;
    }

    return null;
  }

  function getProductName(product) {
    if (!product || typeof product !== "object") return null;
    if (typeof product.localName === "string" && product.localName.trim()) {
      return product.localName.trim();
    }
    const names = product.names;
    if (typeof names === "string" && names.trim()) return names.trim();
    if (names && typeof names === "object") {
      for (const value of Object.values(names)) {
        if (typeof value === "string" && value.trim()) return value.trim();
        if (value && typeof value === "object") {
          const candidate = value.short || value.long || value.name;
          if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
          }
        }
      }
    }
    return null;
  }

  function getInjector() {
    const angular = window.angular;
    if (!angular) return null;
    const root = document.querySelector('[ng-app="ZuZ"]') || document.documentElement;
    try {
      return angular.element(root).injector();
    } catch (_err) {
      return null;
    }
  }

  function getCartService() {
    try {
      return getInjector()?.get("Cart") || null;
    } catch (_err) {
      return null;
    }
  }

  function getLocalStorageService() {
    try {
      return getInjector()?.get("LocalStorage") || null;
    } catch (_err) {
      return null;
    }
  }

  function getCartLines(cart) {
    if (!cart) return [];
    const rawLines = typeof cart.getLines === "function"
      ? cart.getLines()
      : cart.lines || {};
    return Array.isArray(rawLines) ? rawLines : Object.values(rawLines || {});
  }

  function getLocalStorageLines() {
    const localStorageService = getLocalStorageService();
    let rawLines = null;
    try {
      rawLines = localStorageService?.getItem?.("cart") || null;
    } catch (_err) {
      rawLines = null;
    }

    if (!rawLines) {
      try {
        rawLines = JSON.parse(localStorage.getItem("cart") || "null");
      } catch (_err) {
        rawLines = null;
      }
    }

    return Array.isArray(rawLines) ? rawLines : Object.values(rawLines || {});
  }

  function getScopedLines() {
    const angular = window.angular;
    if (!angular) return [];

    const scopes = Array.from(document.querySelectorAll(
      'main tr, main [ng-repeat*="line"], main [class*="product"], main [class*="cart-line"], main [class*="line-item"]'
    ));
    const lines = [];
    const seen = new Set();

    scopes.forEach((node) => {
      let scope = null;
      try {
        scope = angular.element(node).scope?.();
      } catch (_err) {
        scope = null;
      }

      let depth = 0;
      while (scope && depth < 8) {
        for (const candidate of [scope.line, scope.item]) {
          if (!candidate || !candidate.product) continue;
          const key = candidate.id || candidate.product.id || candidate.product.localBarcode || candidate.product.barcode;
          if (key && seen.has(String(key))) continue;
          if (key) seen.add(String(key));
          lines.push(candidate);
        }
        scope = scope.$parent;
        depth += 1;
      }
    });

    return lines;
  }

  function lineToItem(line, enrichedProductById = {}) {
    if (!line || line.removed || line.isHideFromCart) return null;
    const product = line.product || {};
    const enriched = enrichedProductById[product.id] || product;
    const barcode = findBarcodeDeep(line)
      || findBarcodeDeep(product)
      || findBarcodeDeep(enriched);
    const name = getProductName(product) || getProductName(enriched);
    const fallbackId = String(
      product.gs1ProductId
      || product.externalId
      || product.id
      || product.productId
      || line.id
      || ""
    ).trim();
    if (!barcode && (!fallbackId || !name)) return null;

    const quantity = Math.max(1, parseInt(line.quantity, 10) || 1);
    return {
      barcode: barcode || fallbackId,
      quantity,
      name,
      resolved: Boolean(barcode),
    };
  }

  function getBranchInfo() {
    let frontend = {};
    try {
      frontend = JSON.parse(localStorage.getItem("frontend") || "{}");
    } catch (_err) {
      frontend = {};
    }

    const frontendData = window.sp?.frontendData || {};
    return {
      retailerId: frontendData.retailer?.id || frontendData.retailerId || 1540,
      branchId: frontend.branchId || frontendData.branch?.id || 3003,
    };
  }

  async function enrichProducts(lines) {
    const ids = Array.from(new Set(
      lines
        .map((line) => line?.product?.id)
        .filter((id) => id && !asBarcode(lineByProductId(lines, id)?.product?.localBarcode) && !asBarcode(lineByProductId(lines, id)?.product?.barcode))
    ));
    if (!ids.length) return {};

    const { retailerId, branchId } = getBranchInfo();
    const filters = {
      must: {
        exists: ["family.id", "family.categoriesPaths.id", "branch.regularPrice"],
        term: {
          "branch.isActive": true,
          "branch.isVisible": true,
          id: ids,
        },
      },
      mustNot: {
        term: {
          "branch.regularPrice": 0,
          "branch.isOutOfStock": true,
        },
      },
    };
    const params = new URLSearchParams({
      appId: "4",
      filters: JSON.stringify(filters),
      from: "0",
      size: String(ids.length),
    });

    try {
      const response = await fetch(
        `/v2/retailers/${retailerId}/branches/${branchId}/products?${params}`,
        { credentials: "same-origin" }
      );
      if (!response.ok) return {};
      const data = await response.json();
      const products = Array.isArray(data.products) ? data.products : [];
      return Object.fromEntries(products.map((product) => [product.id, product]));
    } catch (_err) {
      return {};
    }
  }

  function lineByProductId(lines, id) {
    return lines.find((line) => line?.product?.id === id);
  }

  function getCandidateLines(cart) {
    const lines = getCartLines(cart);
    if (lines.length) return { source: "cart-service", lines };

    const storedLines = getLocalStorageLines();
    if (storedLines.length) return { source: "local-storage", lines: storedLines };

    const scopedLines = getScopedLines();
    if (scopedLines.length) return { source: "angular-scope", lines: scopedLines };

    return { source: "none", lines: [] };
  }

  async function waitForCandidateLines(cart) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < 8000) {
      const result = getCandidateLines(cart);
      if (result.lines.length) return result;
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
    return getCandidateLines(cart);
  }

  async function extractCartItems() {
    const cart = getCartService();
    let result = getCandidateLines(cart);

    if (!result.lines.length && cart && typeof cart.forceUpdate === "function") {
      try {
        Promise.resolve(cart.forceUpdate()).catch(() => {});
        result = await waitForCandidateLines(cart);
      } catch (_err) {
        result = getCandidateLines(cart);
      }
    }

    if (!result.lines.length) {
      result = await waitForCandidateLines(cart);
    }

    const lines = result.lines;
    const enrichedProductById = {};
    const items = lines
      .filter((line) => line && !line.removed && !line.isHideFromCart)
      .map((line) => lineToItem(line, enrichedProductById))
      .filter(Boolean);

    return items;
  }

  window.addEventListener("message", async (event) => {
    if (event.source !== window) return;
    const message = event.data;
    if (!message || message.source !== REQUEST_SOURCE) return;
    if (message.type !== "GET_CARREFOUR_CART") return;

    window.postMessage({
      source: SOURCE,
      type: "CARREFOUR_CART",
      requestId: message.requestId,
      items: await extractCartItems(),
    }, "*");
  });
})();
