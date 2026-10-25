/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { serializeDateTime } from "@web/core/l10n/dates";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { HrmsDashboard } from "@binaryaid_hrms_dashboard/dashboard";

const { DateTime } = luxon;

/** One position reading per tap. No watchPosition: there is no continuous tracking. */
function readPosition() {
    return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject(new Error(_t("This device cannot share its location.")));
            return;
        }
        navigator.geolocation.getCurrentPosition(
            (position) => resolve(position.coords),
            (error) => reject(new Error(
                error.code === 1
                    ? _t("Location permission is blocked. Allow location for this site, or report an exception.")
                    : _t("Your location could not be read. Try again, or report an exception.")
            )),
            { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
        );
    });
}

function errorText(error) {
    return error?.data?.message || error?.message || _t("Something went wrong. Please try again.");
}

function newToken() {
    return window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export class CareExceptionForm extends Component {
    static template = "binaryaid_care_attendance.ExceptionForm";
    static props = ["kinds", "state"];
}

export class CareNoteDialog extends Component {
    static template = "binaryaid_care_attendance.NoteDialog";
    static components = { Dialog, CareExceptionForm };
    static props = ["clock", "close", "onDone"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.token = newToken();
        this.state = useState({
            loading: true, busy: false, error: "", form: null, answers: {}, mode: "note",
            exception: { kind: "gps_failure", reason: "", time: DateTime.now().toFormat("yyyy-MM-dd'T'HH:mm") },
        });
        onWillStart(async () => {
            try {
                const form = await this.orm.call("binaryaid.hrms.dashboard", "care_note_form", [this.props.clock.shift_id]);
                this.state.form = form;
                for (const question of form.questions) {
                    this.state.answers[question.id] = question.value || "";
                }
            } catch (error) {
                this.state.error = errorText(error);
            } finally {
                this.state.loading = false;
            }
        });
    }
    missingRequired() {
        return this.state.form.questions.filter((q) => q.required && !String(this.state.answers[q.id] || "").trim());
    }
    async saveDraft() {
        await this.orm.call("binaryaid.hrms.dashboard", "care_save_note_draft", [this.props.clock.shift_id, this.state.answers]);
        this.notification.add(_t("Draft saved. You can finish it later."), { type: "info" });
    }
    async saveDraftAndClose() {
        await this.saveDraft();
        this.props.close();
    }
    showException() {
        this.state.mode = "exception";
        this.state.error = "";
    }
    async submit() {
        const missing = this.missingRequired();
        if (missing.length) {
            this.state.error = _t("Answer the required questions: %s", missing.map((q) => q.label).join(", "));
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        let coords;
        try {
            coords = await readPosition();
        } catch (error) {
            await this.saveDraft();
            this.state.error = error.message;
            this.state.busy = false;
            return;
        }
        try {
            const result = await this.orm.call("binaryaid.hrms.dashboard", "care_clock_out", [
                this.props.clock.shift_id, this.state.answers, coords.latitude, coords.longitude, coords.accuracy, this.token,
            ]);
            if (result.status === "error") {
                // The draft was kept on the server; the worker can retry or report an exception.
                this.state.error = result.message;
                return;
            }
            this.notification.add(result.message, { type: "success" });
            this.props.onDone();
            this.props.close();
        } catch (error) {
            this.state.error = errorText(error);
        } finally {
            this.state.busy = false;
        }
    }
    async submitException() {
        const missing = this.missingRequired();
        if (missing.length) {
            this.state.mode = "note";
            this.state.error = _t("Complete the required note questions first.");
            return;
        }
        await submitException(this, "out", this.state.answers);
    }
}

export class CareExceptionDialog extends Component {
    static template = "binaryaid_care_attendance.ExceptionDialog";
    static components = { Dialog, CareExceptionForm };
    static props = ["clock", "clockType", "close", "onDone"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            busy: false, error: "",
            exception: { kind: this.props.clockType === "in" ? "gps_failure" : "missed_clock_out", reason: "",
                         time: DateTime.now().toFormat("yyyy-MM-dd'T'HH:mm") },
        });
    }
    submit() {
        return submitException(this, this.props.clockType, null);
    }
}

async function submitException(component, clockType, answers) {
    const exception = component.state.exception;
    if (!exception.reason.trim()) {
        component.state.error = _t("Explain what happened so your coordinator can approve it.");
        return;
    }
    component.state.busy = true;
    component.state.error = "";
    let coords = {};
    try {
        coords = await readPosition();
    } catch {
        // An exception can be sent without a position.
    }
    try {
        const when = serializeDateTime(DateTime.fromISO(exception.time));
        const result = await component.orm.call("binaryaid.hrms.dashboard", "care_report_exception", [
            component.props.clock.shift_id, exception.kind, exception.reason, clockType, when,
            coords.latitude ?? null, coords.longitude ?? null, coords.accuracy || 0, answers,
        ]);
        component.notification.add(result.message, { type: "success" });
        component.props.onDone();
        component.props.close();
    } catch (error) {
        component.state.error = errorText(error);
    } finally {
        component.state.busy = false;
    }
}

patch(HrmsDashboard.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialogService = useService("dialog");
        this.clockState = useState({ busy: false, error: "" });
    },
    async clockIn() {
        const clock = this.state.data.clock;
        this.clockState.busy = true;
        this.clockState.error = "";
        try {
            const coords = await readPosition();
            const result = await this.orm.call("binaryaid.hrms.dashboard", "care_clock_in", [
                clock.shift_id, coords.latitude, coords.longitude, coords.accuracy,
            ]);
            this.notification.add(result.message, { type: result.status === "ok" ? "success" : "info" });
            await this.load();
        } catch (error) {
            this.clockState.error = errorText(error);
        } finally {
            this.clockState.busy = false;
        }
    },
    clockOut() {
        this.clockState.error = "";
        this.dialogService.add(CareNoteDialog, { clock: this.state.data.clock, onDone: () => this.load() });
    },
    reportClockException(clockType) {
        this.dialogService.add(CareExceptionDialog, { clock: this.state.data.clock, clockType, onDone: () => this.load() });
    },
});
