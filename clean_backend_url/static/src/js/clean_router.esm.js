/** @odoo-module **/

import { router } from "@web/core/browser/router";

const LEGACY_PREFIX = "/odoo";
const CLEAN_PREFIX = "/app";
const originalStateToUrl = router.stateToUrl.bind(router);
const originalUrlToState = router.urlToState.bind(router);

function replacePrefix(path, source, target) {
    if (path === source) {
        return target;
    }
    return path.startsWith(`${source}/`) ? `${target}${path.slice(source.length)}` : path;
}

function cleanUrl(url) {
    return replacePrefix(url, LEGACY_PREFIX, CLEAN_PREFIX);
}

function legacyUrl(url) {
    const converted = new URL(url);
    converted.pathname = replacePrefix(converted.pathname, CLEAN_PREFIX, LEGACY_PREFIX);
    return converted;
}

router.stateToUrl = (state) => cleanUrl(originalStateToUrl(state));
router.urlToState = (url) => originalUrlToState(legacyUrl(url));

function setRouterState(nextState) {
    for (const key of Object.keys(router.current)) {
        delete router.current[key];
    }
    Object.assign(router.current, nextState);
}

if (
    window.location.pathname === CLEAN_PREFIX ||
    window.location.pathname.startsWith(`${CLEAN_PREFIX}/`)
) {
    setRouterState(router.urlToState(new URL(window.location.href)));
} else if (
    window.location.pathname === LEGACY_PREFIX ||
    window.location.pathname.startsWith(`${LEGACY_PREFIX}/`)
) {
    const cleanLocation = new URL(window.location.href);
    cleanLocation.pathname = replacePrefix(
        cleanLocation.pathname,
        LEGACY_PREFIX,
        CLEAN_PREFIX
    );
    window.history.replaceState(window.history.state, "", cleanLocation.href);
}

function cleanAnchor(anchor) {
    const href = anchor.getAttribute("href");
    if (!href) {
        return;
    }
    try {
        const url = new URL(href, window.location.origin);
        if (url.origin === window.location.origin) {
            const cleanPath = replacePrefix(url.pathname, LEGACY_PREFIX, CLEAN_PREFIX);
            if (cleanPath !== url.pathname) {
                url.pathname = cleanPath;
                anchor.setAttribute("href", `${url.pathname}${url.search}${url.hash}`);
            }
        }
    } catch {
        // Leave malformed or non-HTTP links unchanged.
    }
}

function cleanLinks(root) {
    if (root instanceof HTMLAnchorElement) {
        cleanAnchor(root);
    }
    root.querySelectorAll?.("a[href]").forEach(cleanAnchor);
}

cleanLinks(document);
new MutationObserver((mutations) => {
    for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
            if (node instanceof Element) {
                cleanLinks(node);
            }
        });
        if (mutation.type === "attributes" && mutation.target instanceof HTMLAnchorElement) {
            cleanAnchor(mutation.target);
        }
    }
}).observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["href"],
});
