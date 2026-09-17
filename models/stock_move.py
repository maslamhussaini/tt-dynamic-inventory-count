from collections import defaultdict

from odoo import fields, models

COUNTABLE_USAGES = ('internal', 'transit')


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        moves_todo = super()._action_done(cancel_backorder=cancel_backorder)
        moves_todo._tt_register_dynamic_count_activity()
        return moves_todo

    def _tt_register_dynamic_count_activity(self):
        """Increment dynamic-count counters for every (product, internal/
        transit location) pair actually touched by these completed moves,
        then request a native physical count wherever a rule's threshold
        is newly crossed.

        Only moves in state 'done' are considered, and moves created by
        applying a physical inventory count (``is_inventory``) are always
        excluded: that is Odoo's own marker for a reconciliation move, and
        counting it here would create an immediate re-trigger loop right
        after a count was just applied.
        """
        qualifying_moves = self.filtered(
            lambda m: m.state == 'done' and not m.is_inventory)
        if not qualifying_moves:
            return

        # Pass 1: for each move, find the distinct countable (location)
        # set it actually touched, deduplicated at the move level so that
        # several move lines (lots/packages) for the same product/location
        # on one move only count once. Aggregate across all moves in this
        # batch into a per (product, location) occurrence count.
        occurrences = defaultdict(int)
        quantities = defaultdict(float)
        for move in qualifying_moves:
            done_lines = move.move_line_ids.filtered(lambda ml: ml.state == 'done')
            locations = (done_lines.location_id | done_lines.location_dest_id) \
                .filtered(lambda loc: loc.usage in COUNTABLE_USAGES)
            for location in locations:
                occurrences[(move.product_id, location)] += 1

            # In Odoo 19, move.quantity is the sum of line quantities in
            # move.product_uom. Use the completed lines for attribution:
            # a move may touch several different actual source/destinations.
            # Convert exactly as native quantity_product_uom does, never
            # charge the whole move's quantity to every touched location.
            # After super(), unpicked/zero lines have been removed and a
            # backorder's remaining demand belongs to a separate move.
            for line in done_lines:
                quantity = abs(line.product_uom_id._compute_quantity(
                    line.quantity, move.product_id.uom_id,
                    rounding_method='HALF-UP'))
                line_locations = (line.location_id | line.location_dest_id).filtered(
                    lambda loc: loc.usage in COUNTABLE_USAGES)
                for location in line_locations:
                    quantities[(move.product_id, location)] += quantity

        if not occurrences:
            return

        products = self.env['product.product']
        locations = self.env['stock.location']
        for product, location in occurrences:
            products |= product
            locations |= location
        companies = locations.mapped('company_id')

        rules = self.env['tt.dynamic.count.rule'].sudo().search([
            ('active', '=', True),
            ('company_id', 'in', companies.ids),
            '|', ('product_id', '=', False), ('product_id', 'in', products.ids),
            '|', ('product_categ_id', '=', False),
                 ('product_categ_id', 'in', products.mapped('categ_id').ids),
            '|', ('location_id', '=', False), ('location_id', 'in', locations.ids),
        ])
        if not rules:
            return

        Counter = self.env['tt.dynamic.count.counter'].sudo()
        newly_requested_pairs = set()

        for (product, location), increment in occurrences.items():
            matching_rules = rules.filtered(lambda r:
                r.company_id == location.company_id
                and (not r.product_id or r.product_id == product)
                and (not r.product_categ_id or r.product_categ_id == product.categ_id)
                and (not r.location_id or r.location_id == location)
            )
            for rule in matching_rules:
                counter = Counter._get_or_create_locked(rule, product, location)
                if rule.trigger_type == 'cumulative_qty':
                    requested = counter._register_quantity(quantities[(product, location)])
                else:
                    requested = counter._register_movements(increment)
                if requested:
                    newly_requested_pairs.add((product, location))

        if newly_requested_pairs:
            self._tt_request_native_count(newly_requested_pairs)

    def _tt_request_native_count(self, pairs):
        """Make native Odoo Inventory consider (product, location) due for
        counting, reusing stock.quant.inventory_date as native cyclic
        counting already does. An existing earlier (or equal) native due
        date is always preserved; a missing quant (real zero on-hand
        stock, or already cleaned up by Odoo) is not artificially created
        - the dynamic-count counter itself remains the source of truth for
        the "count is due" state in that case, surfaced via this module's
        own Dynamic Counts view.
        """
        Quant = self.env['stock.quant'].sudo()
        today = fields.Date.context_today(self)
        for product, location in pairs:
            quants = Quant._gather(product, location, strict=False)
            for quant in quants:
                if not quant.inventory_date or quant.inventory_date > today:
                    quant.inventory_date = today
