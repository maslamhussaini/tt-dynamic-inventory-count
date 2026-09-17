from datetime import timedelta

from odoo.addons.stock.tests.common import TestStockCommon
from odoo.fields import Date
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestDynamicCount(TestStockCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env['tt.dynamic.count.rule']
        cls.Counter = cls.env['tt.dynamic.count.counter']
        cls.company = cls.env.company

        cls.location_b = cls.env['stock.location'].create({
            'name': 'Internal B',
            'usage': 'internal',
            'location_id': cls.warehouse_1.view_location_id.id,
        })

    def _make_move(self, product, src, dst, qty=1.0):
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'state': 'confirmed',
        })
        move._action_assign()
        move.move_line_ids.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def _make_split_move(self, product, src, dst, qty_per_line=1.0, lines=2):
        """One stock.move, several move lines for the same product/location."""
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty_per_line * lines,
            'product_uom': product.uom_id.id,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'state': 'confirmed',
        })
        for _i in range(lines):
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'location_id': src.id,
                'location_dest_id': dst.id,
                'quantity': qty_per_line,
            })
        move.picked = True
        move._action_done()
        return move

    def _counter(self, rule, product, location):
        return self.Counter.search([
            ('rule_id', '=', rule.id),
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ])

    # 1 & 2 & 3 - below threshold / threshold reached / no duplicate
    def test_threshold_lifecycle(self):
        rule = self.Rule.create({
            'name': 'Rule A',
            'company_id': self.company.id,
            'threshold': 3,
            'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 100)

        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(counter.move_count, 2)
        self.assertFalse(counter.count_requested)

        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(counter.move_count, 3)
        self.assertTrue(counter.count_requested)
        quants = self.env['stock.quant']._gather(self.productA, self.stock_location, strict=False)
        self.assertTrue(any(q.inventory_date and q.inventory_date <= Date.today() for q in quants))

        # 4th movement: no duplicate request, counter keeps counting
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(counter.move_count, 4)
        self.assertTrue(counter.count_requested)

    # 4 - count completion resets the counter
    def test_count_completion_resets_counter(self):
        rule = self.Rule.create({
            'name': 'Rule A',
            'company_id': self.company.id,
            'threshold': 1,
            'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertTrue(counter.count_requested)

        quants = self.env['stock.quant']._gather(self.productA, self.stock_location, strict=False)
        quants.action_set_inventory_quantity()
        quants[0].inventory_quantity = quants[0].quantity
        quants[0].with_context(inventory_mode=True)._apply_inventory()

        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(counter.move_count, 0)
        self.assertFalse(counter.count_requested)
        self.assertTrue(counter.last_reset_date)

    # 16 - applying the count must not immediately re-trigger (loop protection)
    def test_apply_inventory_does_not_retrigger(self):
        rule = self.Rule.create({
            'name': 'Rule A',
            'company_id': self.company.id,
            'threshold': 1,
            'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertTrue(counter.count_requested)

        quants = self.env['stock.quant']._gather(self.productA, self.stock_location, strict=False)
        # Force a discrepancy so applying the count creates a real reconciliation move.
        quants[0].inventory_quantity = quants[0].quantity + 5
        quants[0].with_context(inventory_mode=True)._apply_inventory()

        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(counter.move_count, 0)
        self.assertFalse(counter.count_requested)

    # 5 - draft move: no increment
    def test_draft_move_no_increment(self):
        rule = self.Rule.create({
            'name': 'Rule A', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.stock_location.id,
        })
        self.env['stock.move'].create({
            'product_id': self.productA.id,
            'product_uom_qty': 1,
            'product_uom': self.productA.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
        })
        self.assertFalse(self._counter(rule, self.productA, self.stock_location))

    # 6 - cancelled move: no increment
    def test_cancelled_move_no_increment(self):
        rule = self.Rule.create({
            'name': 'Rule A', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.stock_location.id,
        })
        move = self.env['stock.move'].create({
            'product_id': self.productA.id,
            'product_uom_qty': 1,
            'product_uom': self.productA.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'state': 'confirmed',
        })
        move._action_cancel()
        self.assertFalse(self._counter(rule, self.productA, self.stock_location))

    # 7 - inactive rule: no increment
    def test_inactive_rule_ignored(self):
        rule = self.Rule.create({
            'name': 'Rule A', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.stock_location.id,
            'active': False,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        self.assertFalse(self._counter(rule, self.productA, self.stock_location))

    # 8 - product scope
    def test_product_scope(self):
        rule = self.Rule.create({
            'name': 'Rule Product A', 'company_id': self.company.id,
            'threshold': 1, 'product_id': self.productA.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productB, self.stock_location, 10)
        self._make_move(self.productB, self.stock_location, self.customer_location, 1)
        self.assertFalse(self._counter(rule, self.productB, self.stock_location))

        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        self.assertTrue(self._counter(rule, self.productA, self.stock_location))

    # 9 - category scope
    def test_category_scope(self):
        categ = self.env['product.category'].create({'name': 'Dynamic Count Test Categ'})
        self.productA.categ_id = categ.id
        rule = self.Rule.create({
            'name': 'Rule Categ', 'company_id': self.company.id,
            'threshold': 1, 'product_categ_id': categ.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productB, self.stock_location, 10)
        self._make_move(self.productB, self.stock_location, self.customer_location, 1)
        self.assertFalse(self._counter(rule, self.productB, self.stock_location))

        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        self.assertTrue(self._counter(rule, self.productA, self.stock_location))

    # 10 - location scope
    def test_location_scope(self):
        rule = self.Rule.create({
            'name': 'Rule Location', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.location_b, 10)
        self._make_move(self.productA, self.location_b, self.customer_location, 1)
        self.assertFalse(self._counter(rule, self.productA, self.location_b))

    # 11 - company isolation
    def test_company_isolation(self):
        # Note: rule2 is deliberately left without a location_id. Scoping it
        # to self.stock_location (company 1) while company_id=company2 would
        # violate _check_location_company (a location must belong to its
        # rule's company) - that constraint is correct Phase 1 behavior, not
        # a bug, so this test instead proves isolation the way it actually
        # has to be configured: a company-2 rule with no location/product
        # restriction still must not react to company-1 activity, because
        # rule matching filters on `rule.company_id == location.company_id`.
        company2 = self.env['res.company'].create({'name': 'Other Co'})
        rule2 = self.Rule.create({
            'name': 'Rule Other Co', 'company_id': company2.id,
            'threshold': 1,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        self.assertFalse(self._counter(rule2, self.productA, self.stock_location))

    # 12 - incoming: supplier -> internal, destination increments
    def test_incoming_increments_destination(self):
        rule = self.Rule.create({
            'name': 'Rule In', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.stock_location.id,
        })
        self._make_move(self.productA, self.supplier_location, self.stock_location, 5)
        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(counter.move_count, 1)

    # 13 - outgoing: internal -> customer, source increments
    def test_outgoing_increments_source(self):
        rule = self.Rule.create({
            'name': 'Rule Out', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(counter.move_count, 1)

    # 14 - internal A -> internal B: each side handled independently
    def test_internal_transfer_both_sides(self):
        rule_a = self.Rule.create({
            'name': 'Rule A', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.stock_location.id,
        })
        rule_b = self.Rule.create({
            'name': 'Rule B', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.location_b.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        self._make_move(self.productA, self.stock_location, self.location_b, 4)
        self.assertEqual(self._counter(rule_a, self.productA, self.stock_location).move_count, 1)
        self.assertEqual(self._counter(rule_b, self.productA, self.location_b).move_count, 1)

    # 15 - one move, several move lines for the same product/location -> counts once
    def test_multiple_move_lines_single_increment(self):
        rule = self.Rule.create({
            'name': 'Rule Split', 'company_id': self.company.id,
            'threshold': 5, 'location_id': self.stock_location.id,
        })
        self._make_split_move(self.productA, self.supplier_location, self.stock_location,
                               qty_per_line=1, lines=3)
        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(counter.move_count, 1)

    # 17 - an earlier native count date must never be postponed
    def test_earlier_native_date_preserved(self):
        rule = self.Rule.create({
            'name': 'Rule A', 'company_id': self.company.id,
            'threshold': 1, 'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        quants = self.env['stock.quant']._gather(self.productA, self.stock_location, strict=False)
        earlier_date = Date.today() - timedelta(days=5)
        quants.inventory_date = earlier_date

        self._make_move(self.productA, self.stock_location, self.customer_location, 1)

        quants = self.env['stock.quant']._gather(self.productA, self.stock_location, strict=False)
        for quant in quants:
            self.assertEqual(quant.inventory_date, earlier_date)

    # 18 - only one counter exists for a given rule/product/location
    def test_single_counter_per_combination(self):
        rule = self.Rule.create({
            'name': 'Rule A', 'company_id': self.company.id,
            'threshold': 100, 'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 10)
        for _i in range(3):
            self._make_move(self.productA, self.stock_location, self.customer_location, 1)
        counters = self._counter(rule, self.productA, self.stock_location)
        self.assertEqual(len(counters), 1)
        self.assertEqual(counters.move_count, 3)
