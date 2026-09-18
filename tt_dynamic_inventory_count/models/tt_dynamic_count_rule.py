from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TtDynamicCountRule(models.Model):
    _name = 'tt.dynamic.count.rule'
    _description = 'Dynamic Inventory Count Rule'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)
    trigger_type = fields.Selection(
        [('move_count', "Completed Movements"),
         ('cumulative_qty', "Cumulative Quantity")],
        required=True, default='move_count',
        help="Count completed movements or total absolute stock activity "
             "in each product's base unit of measure (not net stock change).")
    threshold = fields.Float(
        required=True, default=1, digits='Product Unit',
        help="For Completed Movements, use a whole number of movements. "
             "For Cumulative Quantity, use the total absolute quantity of "
             "stock activity in each matching product's base unit of measure.")

    product_id = fields.Many2one(
        'product.product', string="Product", index=True,
        check_company=True,
        help="Restrict this rule to a single product. Leave empty to match "
             "all products (subject to the category/location scopes).")
    product_categ_id = fields.Many2one(
        'product.category', string="Product Category", index=True,
        help="Restrict this rule to products in this category. Leave empty "
             "to match all categories.")
    location_id = fields.Many2one(
        'stock.location', string="Location", index=True,
        check_company=True,
        domain="[('usage', 'in', ('internal', 'transit'))]",
        help="Restrict this rule to a single internal/transit location. "
             "Leave empty to match all internal/transit locations of the "
             "company.")

    counter_ids = fields.One2many(
        'tt.dynamic.count.counter', 'rule_id', string="Counters")
    counter_count = fields.Integer(compute='_compute_counter_count')

    _threshold_positive = models.Constraint(
        'CHECK(threshold > 0)',
        "The threshold must be strictly positive.",
    )
    _movement_threshold_whole = models.Constraint(
        "CHECK(trigger_type != 'move_count' OR threshold = FLOOR(threshold))",
        "A completed-movements threshold must be a whole number.",
    )

    @api.depends('counter_ids')
    def _compute_counter_count(self):
        for rule in self:
            rule.counter_count = len(rule.counter_ids)

    @api.constrains('product_id', 'product_categ_id')
    def _check_product_scope_not_ambiguous(self):
        for rule in self:
            if rule.product_id and rule.product_categ_id:
                raise ValidationError(_(
                    "Rule '%s' cannot restrict both a specific product and "
                    "a product category at the same time. Choose one scope "
                    "to keep the matching behavior unambiguous.",
                    rule.name,
                ))

    def action_view_counters(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'tt_dynamic_inventory_count.tt_dynamic_count_counter_action')
        action['domain'] = [('rule_id', '=', self.id)]
        action['context'] = {'default_rule_id': self.id}
        return action

    @api.constrains('location_id', 'company_id')
    def _check_location_company(self):
        for rule in self:
            if rule.location_id and rule.location_id.company_id and \
                    rule.location_id.company_id != rule.company_id:
                raise ValidationError(_(
                    "The location of rule '%s' does not belong to the "
                    "rule's company.", rule.name,
                ))
