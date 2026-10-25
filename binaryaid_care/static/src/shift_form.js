/** @odoo-module **/
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";

/**
 * Concurrent edit protection: every save of an existing shift carries the revision
 * that was loaded. The server rejects the save if someone else changed the shift.
 */
export class CareShiftFormController extends FormController {
    async onWillSaveRecord(record, changes) {
        if (record.resId && "binaryaid_revision" in record.data && changes) {
            changes.binaryaid_revision_token = String(record.data.binaryaid_revision);
        }
        return super.onWillSaveRecord(...arguments);
    }
}

registry.category("views").add("binaryaid_shift_form", { ...formView, Controller: CareShiftFormController });
