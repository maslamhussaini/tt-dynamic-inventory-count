from odoo import api, models


class TtDynamicCountDashboard(models.AbstractModel):
    """Read-only aggregator for the Dynamic Inventory Count dashboard.

    Every method below relies exclusively on ``search_count``/``read_group``
    over ``tt.dynamic.count.rule``/``tt.dynamic.count.counter`` in the
    current user's environment (no ``sudo()``), so existing ``ir.rule``
    (company scoping) and ACLs apply automatically, exactly as they do for
    the existing list views.
    """
    _name = 'tt.dynamic.count.dashboard'
    _description = 'Dynamic Inventory Count Dashboard'

    @api.model
    def get_kpis(self):
        rule_model = self.env['tt.dynamic.count.rule']
        counter_model = self.env['tt.dynamic.count.counter']
        return {
            'active_rules': rule_model.search_count([('active', '=', True)]),
            'due_items': counter_model.search_count(
                [('count_requested', '=', True)]),
            'due_move_count': counter_model.search_count([
                ('count_requested', '=', True),
                ('trigger_type', '=', 'move_count'),
            ]),
            'due_cumulative_qty': counter_model.search_count([
                ('count_requested', '=', True),
                ('trigger_type', '=', 'cumulative_qty'),
            ]),
            # Fallback 5th KPI (see module dashboard docs): counters tied to
            # an active rule. Native stock.quant.inventory_date is also
            # driven by native cyclic counting / company inventory dates /
            # manual edits, so a naive "physical inventory due" count would
            # misattribute due-ness that this module never caused. This
            # metric only ever reflects this module's own data.
            'active_counters': counter_model.search_count(
                [('rule_id.active', '=', True)]),
        }

    @api.model
    def get_due_by_location(self):
        groups = self.env['tt.dynamic.count.counter']._read_group(
            [('count_requested', '=', True)],
            groupby=['location_id'],
            aggregates=['__count'],
        )
        return [
            {'label': location.display_name if location else 'Unknown', 'value': count}
            for location, count in groups
        ]

    @api.model
    def get_due_by_trigger(self):
        selection = dict(
            self.env['tt.dynamic.count.counter']
            .fields_get(['trigger_type'])['trigger_type']['selection']
        )
        groups = self.env['tt.dynamic.count.counter']._read_group(
            [('count_requested', '=', True)],
            groupby=['trigger_type'],
            aggregates=['__count'],
        )
        return [
            {'label': selection.get(trigger_type, trigger_type or 'Unknown'), 'value': count}
            for trigger_type, count in groups
        ]

    @api.model
    def get_top_due_items(self, limit=10):
        counters = self.env['tt.dynamic.count.counter'].search(
            [('count_requested', '=', True)], limit=limit,
            order='move_count desc, cumulative_qty desc')
        result = []
        for counter in counters:
            if counter.trigger_type == 'move_count':
                current_activity = "%d movements" % counter.move_count
                threshold = "%d movements" % counter.threshold
            else:
                uom_name = counter.product_uom_id.display_name or ''
                current_activity = ("%.2f %s" % (counter.cumulative_qty, uom_name)).strip()
                threshold = ("%.2f %s" % (counter.threshold, uom_name)).strip()
            result.append({
                'id': counter.id,
                'product': counter.product_id.display_name,
                'location': counter.location_id.display_name,
                'trigger_type': counter.trigger_type,
                'current_activity': current_activity,
                'threshold': threshold,
                'count_requested': counter.count_requested,
            })
        return result
