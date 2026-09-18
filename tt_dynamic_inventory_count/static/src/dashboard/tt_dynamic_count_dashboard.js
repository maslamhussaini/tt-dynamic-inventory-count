/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { Component, useState, onWillStart, useRef, onMounted, onWillUnmount } from "@odoo/owl";

const TRIGGER_LABELS = {
    move_count: "Completed Movements",
    cumulative_qty: "Cumulative Quantity",
};

const TRIGGER_COLORS = ["#4361ee", "#2fb886", "#8c6fd8", "#f7a440", "#ee5f7a"];

export class TtDynamicCountDashboard extends Component {
    static template = "tt_dynamic_inventory_count.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.locationChartRef = useRef("locationChart");
        this.triggerChartRef = useRef("triggerChart");
        this.locationChartInstance = null;
        this.triggerChartInstance = null;

        this.state = useState({
            loading: true,
            kpis: {
                active_rules: 0,
                due_items: 0,
                due_move_count: 0,
                due_cumulative_qty: 0,
                active_counters: 0,
            },
            byLocation: [],
            byTrigger: [],
            triggerLegend: [],
            topDueItems: [],
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
        });

        onMounted(() => {
            this.renderCharts();
        });

        onWillUnmount(() => {
            this.locationChartInstance?.destroy();
            this.triggerChartInstance?.destroy();
        });
    }

    async loadData() {
        const [kpis, byLocation, byTrigger, topDueItems] = await Promise.all([
            this.orm.call("tt.dynamic.count.dashboard", "get_kpis", []),
            this.orm.call("tt.dynamic.count.dashboard", "get_due_by_location", []),
            this.orm.call("tt.dynamic.count.dashboard", "get_due_by_trigger", []),
            this.orm.call("tt.dynamic.count.dashboard", "get_top_due_items", [], { limit: 10 }),
        ]);
        this.state.kpis = kpis;
        this.state.byLocation = byLocation;
        this.state.byTrigger = byTrigger;
        // Computed here (never hardcoded) so the legend always matches
        // whatever real due-item data the server returned, including the
        // zero-due-items case (no NaN%, no division by zero).
        const totalTrigger = byTrigger.reduce((sum, r) => sum + r.value, 0);
        this.state.triggerLegend = byTrigger.map((r, index) => ({
            label: r.label,
            value: r.value,
            pct: totalTrigger > 0 ? Math.round((r.value / totalTrigger) * 100) : 0,
            color: TRIGGER_COLORS[index % TRIGGER_COLORS.length],
        }));
        this.state.topDueItems = topDueItems.map((item) => ({
            ...item,
            trigger_label: TRIGGER_LABELS[item.trigger_type] || item.trigger_type,
        }));
        this.state.loading = false;
    }

    renderCharts() {
        if (this.locationChartRef.el) {
            this.locationChartInstance?.destroy();
            this.locationChartInstance = new Chart(this.locationChartRef.el, {
                type: "bar",
                data: {
                    labels: this.state.byLocation.map((r) => r.label),
                    datasets: [{
                        label: "Due Items",
                        data: this.state.byLocation.map((r) => r.value),
                        backgroundColor: "#6c8ef5",
                        borderRadius: 6,
                        maxBarThickness: 56,
                        categoryPercentage: 0.5,
                        barPercentage: 0.7,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: { padding: { top: 8, right: 8, bottom: 0, left: 0 } },
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0 } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }
        if (this.triggerChartRef.el) {
            this.triggerChartInstance?.destroy();
            this.triggerChartInstance = new Chart(this.triggerChartRef.el, {
                type: "doughnut",
                data: {
                    labels: this.state.byTrigger.map((r) => r.label),
                    datasets: [{
                        data: this.state.byTrigger.map((r) => r.value),
                        backgroundColor: this.state.byTrigger.map(
                            (r, i) => TRIGGER_COLORS[i % TRIGGER_COLORS.length]
                        ),
                        borderWidth: 2,
                        borderColor: "#fff",
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "68%",
                    plugins: { legend: { display: false } },
                },
            });
        }
    }

    async openAction(xmlid, extraDomain, extraContext) {
        // Odoo 19 blocks direct RPC to private methods (leading underscore)
        // such as "_for_xml_id", so the action definition is resolved via
        // the public action service instead (which performs the same
        // server-side xmlid resolution internally) and only then executed.
        const action = await this.action.loadAction(xmlid);
        if (extraDomain) {
            action.domain = extraDomain;
        }
        if (extraContext) {
            action.context = { ...(action.context || {}), ...extraContext };
        }
        this.action.doAction(action);
    }

    onActiveRulesClick() {
        this.openAction("tt_dynamic_inventory_count.tt_dynamic_count_rule_action");
    }

    onDueItemsClick() {
        this.openAction(
            "tt_dynamic_inventory_count.tt_dynamic_count_counter_action",
            [["count_requested", "=", true]]
        );
    }

    onMoveCountClick() {
        this.openAction(
            "tt_dynamic_inventory_count.tt_dynamic_count_counter_action",
            [["count_requested", "=", true], ["trigger_type", "=", "move_count"]]
        );
    }

    onQuantityClick() {
        this.openAction(
            "tt_dynamic_inventory_count.tt_dynamic_count_counter_action",
            [["count_requested", "=", true], ["trigger_type", "=", "cumulative_qty"]]
        );
    }

    onViewAllClick() {
        this.openAction(
            "tt_dynamic_inventory_count.tt_dynamic_count_counter_action",
            [["count_requested", "=", true]]
        );
    }
}

registry.category("actions").add("tt_dynamic_count_dashboard", TtDynamicCountDashboard);
