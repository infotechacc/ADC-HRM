/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";

/** No "Proceed Anyway": a check in or check out without a location is not recorded. */
patch(ActivityMenu.prototype, {
    confirmChecking() {
        this.state.gettingPosition = false;
        this.notification.add(
            _t("Your location could not be read. Allow location access for this site and try again."),
            { title: _t("Check in not recorded"), type: "danger" }
        );
    },
});
