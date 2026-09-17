from psycopg2.errors import UniqueViolation

from odoo import api, fields, models


class TtDynamicCountCounter(models.Model):
    _name = 'tt.dynamic.count.counter'
    _description = 'Dynamic Inventory Count Counter'
    _order = 'count_requested desc, move_count desc'

    rule_id = fields.Many2one(
        'tt.dynamic.count.rule', required=True, index=True,
        ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', required=True, index=True, ondelete='cascade')
    location_id = fields.Many2one(
        'stock.location', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', related='location_id.company_id', store=True,
        index=True, readonly=True)

    move_count = fields.Integer(default=0, readonly=True)
    trigger_type = fields.Selection(related='rule_id.trigger_type', readonly=True)
    cumulative_qty = fields.Float(
        string="Cumulative Activity", default=0, digits='Product Unit', readonly=True,
        help="Total absolute completed stock activity in the product's base UoM.")
    product_uom_id = fields.Many2one(related='product_id.uom_id', readonly=True)
    threshold = fields.Float(related='rule_id.threshold', readonly=True)
    count_requested = fields.Boolean(default=False, readonly=True)
    last_reset_date = fields.Datetime(readonly=True)

    _rule_product_location_unique = models.Constraint(
        'UNIQUE(rule_id, product_id, location_id)',
        "A counter already exists for this rule/product/location "
        "combination.",
    )

    @api.model
    def _get_or_create_locked(self, rule, product, location):
        """Return the counter for (rule, product, location), creating it if
        needed, and take a row-level lock so concurrent movement validations
        cannot both read/increment the same counter unsafely.

        The unique DB constraint on (rule_id, product_id, location_id) is
        the source of truth for correctness; the explicit ``SELECT ...
        FOR UPDATE`` below only serializes concurrent increments so a read
        -modify-write on activity/``count_requested`` is atomic. Plain
        ORM ``search`` + ``write`` cannot guarantee that on their own.
        """
        counter = self.search([
            ('rule_id', '=', rule.id),
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ], limit=1)
        if counter:
            self.env.cr.execute(
                "SELECT id FROM tt_dynamic_count_counter WHERE id = %s FOR UPDATE",
                (counter.id,),
            )
            return counter

        try:
            with self.env.cr.savepoint():
                counter = self.create({
                    'rule_id': rule.id,
                    'product_id': product.id,
                    'location_id': location.id,
                })
        except UniqueViolation:
            # Another concurrent transaction created it first; fetch and
            # lock the row it inserted.
            counter = self.search([
                ('rule_id', '=', rule.id),
                ('product_id', '=', product.id),
                ('location_id', '=', location.id),
            ], limit=1)
            self.env.cr.execute(
                "SELECT id FROM tt_dynamic_count_counter WHERE id = %s FOR UPDATE",
                (counter.id,),
            )
        return counter

    def _register_movements(self, increment):
        """Increment this (locked) counter and flag a count request the
        first time its threshold is crossed. The counter keeps counting
        past the threshold (see module documentation); only the boolean
        flag gates duplicate count requests.
        """
        self.ensure_one()
        vals = {'move_count': self.move_count + increment}
        newly_requested = False
        if not self.count_requested and vals['move_count'] >= self.rule_id.threshold:
            vals['count_requested'] = True
            newly_requested = True
        self.write(vals)
        return newly_requested

    def _register_quantity(self, increment):
        """Accumulate normalized activity on a locked quantity counter.

        Compare at the product UoM's precision, as native stock does, and
        continue accumulating while a request is pending.
        """
        self.ensure_one()
        quantity = self.cumulative_qty + increment
        vals = {'cumulative_qty': quantity}
        newly_requested = (
            not self.count_requested
            and self.product_id.uom_id.compare(quantity, self.rule_id.threshold) >= 0
        )
        if newly_requested:
            vals['count_requested'] = True
        self.write(vals)
        return newly_requested

    def _reset(self):
        self.write({
            'move_count': 0,
            'cumulative_qty': 0,
            'count_requested': False,
            'last_reset_date': fields.Datetime.now(),
        })

    @api.model
    def _tt_reset_for_pairs(self, pairs):
        """Reset every counter tracking one of the given (product, location)
        pairs. A genuine applied physical count supersedes any activity
        accumulated so far for that pair, whether or not it had already
        crossed its rule's threshold.
        """
        domain = ['|'] * (len(pairs) - 1)
        for product, location in pairs:
            domain += ['&', ('product_id', '=', product.id), ('location_id', '=', location.id)]
        counters = self.search(domain) if pairs else self.browse()
        counters._reset()
