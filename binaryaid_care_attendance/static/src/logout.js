/** @odoo-module **/
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const userMenu = registry.category("user_menuitems");
const nativeLogout = userMenu.get("log_out");

/** Warn that logging out does not end an active shift (the worker must still Clock Out). */
userMenu.add("log_out", (env) => {
    const item = nativeLogout(env);
    const proceed = item.callback;
    return {
        ...item,
        callback: async () => {
            let active = false;
            try {
                active = await env.services.orm.call("binaryaid.hrms.dashboard", "care_is_signed_in", []);
            } catch {
                active = false;
            }
            if (!active) {
                return proceed();
            }
            env.services.dialog.add(ConfirmationDialog, {
                title: _t("You are still signed in to a shift"),
                body: _t("Logging out does not end your shift. Clock Out from your dashboard when you finish, or your coordinator will see a missing sign out."),
                confirmLabel: _t("Log out anyway"),
                cancelLabel: _t("Stay"),
                confirm: () => proceed(),
                cancel: () => {},
            });
        },
    };
}, { force: true });
