/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class HrmsDashboard extends Component {
    static template = "binaryaid_hrms_dashboard.Dashboard";
    static props = ["*"];
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, loading: true, error: false });
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
}
registry.category("actions").add("binaryaid_hrms_dashboard", HrmsDashboard);
