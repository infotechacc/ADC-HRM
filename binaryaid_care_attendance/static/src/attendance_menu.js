/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";

/**
 * Odoo's top bar check in is hidden: it has no shift location check (the server refuses it too).
 * Employees check in and out from the HRMS dashboard, at their assigned shift location.
 */
patch(ActivityMenu.prototype, {
    _searchReadEmployeeFill() {
        super._searchReadEmployeeFill(...arguments);
        this.state.isDisplayed = false;
    },
});
