/** @odoo-module **/
import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const TODAY_FILTERS = [
    { key: "all", label: _t("All") },
    { key: "attention", label: _t("Needs attention"), statuses: ["late", "signed_out", "draft"] },
    { key: "working", label: _t("Working"), statuses: ["on_shift", "running"] },
    { key: "upcoming", label: _t("Upcoming"), statuses: ["upcoming"] },
    { key: "done", label: _t("Done"), statuses: ["completed", "ended"] },
];

export class HrmsDashboard extends Component {
    static template = "binaryaid_hrms_dashboard.Dashboard";
    static props = ["*"];
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.todayRef = useRef("today");
        this.attentionRef = useRef("attention");
        this.todayFilters = TODAY_FILTERS;
        this.state = useState({ data: null, loading: true, error: false, tab: null, todayFilter: "all", busy: null });
        onWillStart(() => this.load());
    }
    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call("binaryaid.hrms.dashboard", "get_overview", []);
            const tabs = data.attention || [];
            if (!tabs.some((tab) => tab.key === this.state.tab)) {
                // Open the first tab that has work waiting, so the inbox starts on something actionable.
                this.state.tab = (tabs.find((tab) => tab.count) || tabs[0] || {}).key || null;
            }
            this.state.data = data;
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
    openWork(id) { return this.navigate("open_work", id); }
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
    get activeTab() {
        return (this.state.data?.attention || []).find((tab) => tab.key === this.state.tab);
    }
    get attentionTotal() {
        return (this.state.data?.attention || []).reduce((total, tab) => total + tab.count, 0);
    }
    selectTab(key) {
        this.state.tab = key;
    }
    onTabKeydown(ev, index) {
        const tabs = this.state.data.attention;
        const step = { ArrowRight: 1, ArrowLeft: -1 }[ev.key];
        if (!step) {
            return;
        }
        const next = tabs[(index + step + tabs.length) % tabs.length];
        this.selectTab(next.key);
        ev.currentTarget.parentElement.querySelector(`[data-tab="${next.key}"]`)?.focus();
    }
    openCard(card) {
        const tabs = this.state.data.attention || [];
        if (tabs.some((tab) => tab.key === card.key)) {
            this.selectTab(card.key);
            this.attentionRef.el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
            return;
        }
        if (card.key === "shifts_today" && this.todayRef.el) {
            this.state.todayFilter = "all";
            this.todayRef.el.scrollIntoView({ behavior: "smooth", block: "nearest" });
            return;
        }
        return this.openSection(card.key);
    }
    get todayRows() {
        const rows = this.state.data?.today?.rows || [];
        const filter = TODAY_FILTERS.find((f) => f.key === this.state.todayFilter);
        return filter?.statuses ? rows.filter((row) => filter.statuses.includes(row.status)) : rows;
    }
    filterCount(filter) {
        const rows = this.state.data?.today?.rows || [];
        return filter.statuses ? rows.filter((row) => filter.statuses.includes(row.status)).length : rows.length;
    }
    openShiftRow(row) {
        return this.itemAction({ source: "shift", id: row.id, title: row.employee }, { name: "open", label: _t("Open") });
    }
    onDayClick(day) {
        if (!day.past) {
            return this.quick("create_shift", day.date);
        }
    }
    dayTitle(day) {
        return _t("%(date)s: %(published)s published, %(draft)s draft", day);
    }
}
registry.category("actions").add("binaryaid_hrms_dashboard", HrmsDashboard);
