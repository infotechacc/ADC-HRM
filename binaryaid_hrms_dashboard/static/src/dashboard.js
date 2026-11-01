/** @odoo-module **/
import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const TODAY_FILTERS = [
    { key: "all", label: _t("All") },
    { key: "attention", label: _t("Attention"), statuses: ["late", "signed_out", "draft", "unfilled"] },
    { key: "working", label: _t("Working"), statuses: ["on_shift", "running"] },
    { key: "upcoming", label: _t("Upcoming"), statuses: ["upcoming"] },
    { key: "done", label: _t("Finished"), statuses: ["completed", "ended"] },
];
const CALENDAR_ITEMS_PER_DAY = 3;
// Friendly, distinguishable colours: each worker keeps the same colour everywhere.
const PALETTE = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#14b8a6", "#6366f1", "#f97316", "#0ea5e9", "#84cc16"];
const NAV_TONES = { work_schedule: "blue", my_incidents: "red", team_messages: "purple", my_leave: "teal", profile: "amber", discuss: "green", my_work: "indigo" };

export class HrmsDashboard extends Component {
    static template = "binaryaid_hrms_dashboard.Dashboard";
    static props = ["*"];
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.todayRef = useRef("today");
        this.todayFilters = TODAY_FILTERS;
        this.calendarLimit = CALENDAR_ITEMS_PER_DAY;
        this.state = useState({ data: null, loading: true, error: false, todayFilter: "all", busy: null });
        onWillStart(() => this.load());
    }
    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call("binaryaid.hrms.dashboard", "get_overview", []);
        } catch {
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }
    errorMessage(error, fallback) {
        return error?.data?.message || error?.message || fallback;
    }
    async run(action) {
        // Dialog actions refresh the dashboard once closed, so counts follow the change.
        await this.action.doAction(action, { onClose: () => this.load() });
    }
    async navigate(method, value) {
        try {
            const action = await this.orm.call("binaryaid.hrms.dashboard", method, [value]);
            await this.action.doAction(action);
        } catch {
            this.notification.add(_t("This section could not be opened. Please refresh or check your access."), { type: "warning" });
        }
    }
    openSection(key) { return this.navigate("open_section", key); }
    async quick(key, date = false) {
        try {
            await this.run(await this.orm.call("binaryaid.hrms.dashboard", "quick_action", [key, date]));
        } catch (error) {
            this.notification.add(this.errorMessage(error, _t("This action is not available.")), { type: "warning" });
        }
    }
    async itemAction(item, action) {
        if (this.state.busy) {
            return;
        }
        this.state.busy = `${item.source}-${item.id}-${action.name}`;
        try {
            const result = await this.orm.call("binaryaid.hrms.dashboard", "item_action", [item.source, item.id, action.name]);
            if (result && typeof result === "object") {
                await this.run(result);
            } else {
                this.notification.add(_t("%(action)s: %(item)s", { action: action.label, item: item.title }), { type: "success" });
                await this.load();
            }
        } catch (error) {
            this.notification.add(this.errorMessage(error, _t("The action could not be completed.")), {
                type: "danger", title: _t("%(action)s not completed", { action: action.label }),
            });
            await this.load();
        } finally {
            this.state.busy = null;
        }
    }
    isBusy(item, action) {
        return this.state.busy === `${item.source}-${item.id}-${action.name}`;
    }

    openCard(card) {
        if (card.key === "shifts_today" && this.todayRef.el) {
            this.state.todayFilter = "all";
            this.todayRef.el.scrollIntoView({ behavior: "smooth", block: "nearest" });
            return;
        }
        return this.openSection(card.key);
    }

    // Today and calendar -----------------------------------------------------------
    get todayRows() {
        const rows = this.state.data?.today?.rows || [];
        const filter = TODAY_FILTERS.find((f) => f.key === this.state.todayFilter);
        return filter?.statuses ? rows.filter((row) => filter.statuses.includes(row.status)) : rows;
    }
    filterCount(filter) {
        const rows = this.state.data?.today?.rows || [];
        return filter.statuses ? rows.filter((row) => filter.statuses.includes(row.status)).length : rows.length;
    }
    openShift(id, title) {
        return this.itemAction({ source: "shift", id, title }, { name: "open", label: _t("Open") });
    }
    onDayClick(day) {
        if (!day.past) {
            return this.quick("create_shift", day.date);
        }
    }

    // Worker ---------------------------------------------------------------------
    get upcomingShifts() {
        return (this.state.data?.schedule?.shifts || []).filter((shift) => !shift.past);
    }
    noop() {}
    colorFor(name) {
        let hash = 0;
        for (const char of name || "") {
            hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
        }
        return PALETTE[hash % PALETTE.length];
    }
    navTone(key) {
        return NAV_TONES[key] || "blue";
    }
    cancelLeave(leave) {
        return this.itemAction({ source: "my_leave", id: leave.id, title: leave.type }, { name: "cancel", label: _t("Cancel") });
    }
}
registry.category("actions").add("binaryaid_hrms_dashboard", HrmsDashboard);
