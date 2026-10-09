/** @odoo-module **/

import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { user_menu_items } from "@web/webclient/user_menu/user_menu_items"; // eslint-disable-line no-unused-vars

const BRAND_TITLE = "BinaryAid HRMS";
const SKIP_TEXT_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT"]);
const TEXT_REPLACEMENTS = [
    [/\bOdooBot\b/g, "Assistant"],
    [/\bOdoo\.com\b/g, "Account"],
    [/\bOdoo\b/g, "System"],
    [/\bodoo\b/g, "system"],
];

patch(WebClient.prototype, {
    setup() {
        super.setup();
        this.title.setParts({ zopenerp: BRAND_TITLE });
        startBrandingSanitizer();
    },
});

const userMenuRegistry = registry.category("user_menuitems");

for (const itemName of ["documentation", "support", "odoo_account", "shortcuts"]) {
    if (userMenuRegistry.contains(itemName)) {
        userMenuRegistry.remove(itemName);
    }
}

function sanitizeText(value) {
    return TEXT_REPLACEMENTS.reduce(
        (result, [pattern, replacement]) => result.replace(pattern, replacement),
        value
    );
}

function sanitizeElementAttributes(element) {
    for (const attrName of ["title", "alt", "aria-label", "placeholder"]) {
        const value = element.getAttribute(attrName);
        if (value) {
            const sanitized = sanitizeText(value);
            if (sanitized !== value) {
                element.setAttribute(attrName, sanitized);
            }
        }
    }

    const href = element.getAttribute("href");
    if (href && /odoo/i.test(href)) {
        element.removeAttribute("href");
        element.setAttribute("role", "button");
    }
}

function sanitizeTextNode(node) {
    const parent = node.parentElement;
    if (!parent || SKIP_TEXT_TAGS.has(parent.tagName)) {
        return;
    }
    const sanitized = sanitizeText(node.nodeValue);
    if (sanitized !== node.nodeValue) {
        node.nodeValue = sanitized;
    }
}

function sanitizeTree(root) {
    if (!root) {
        return;
    }
    if (root.nodeType === Node.TEXT_NODE) {
        sanitizeTextNode(root);
        return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) {
        return;
    }
    if (root.nodeType === Node.ELEMENT_NODE) {
        sanitizeElementAttributes(root);
    }
    const walker = document.createTreeWalker(
        root,
        NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    while (walker.nextNode()) {
        const node = walker.currentNode;
        if (node.nodeType === Node.TEXT_NODE) {
            sanitizeTextNode(node);
        } else {
            sanitizeElementAttributes(node);
        }
    }
}

function startBrandingSanitizer() {
    if (window.__BrandingSanitizerStarted) {
        return;
    }
    window.__BrandingSanitizerStarted = true;

    const sanitize = () => sanitizeTree(document.body);
    queueMicrotask(sanitize);

    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            if (mutation.type === "characterData") {
                sanitizeTextNode(mutation.target);
            }
            for (const node of mutation.addedNodes) {
                sanitizeTree(node);
            }
            if (mutation.type === "attributes") {
                sanitizeTree(mutation.target);
            }
        }
    });
    observer.observe(document.body, {
        childList: true,
        characterData: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["title", "alt", "aria-label", "placeholder", "href"],
    });
}
