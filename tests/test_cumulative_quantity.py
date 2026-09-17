from datetime import timedelta
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo.addons.stock.tests.common import TestStockCommon
from odoo.exceptions import AccessError
from odoo.fields import Date
from odoo.tests import tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestCumulativeQuantity(TestStockCommon):
    """Exercise actual stock completion and native inventory application."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env['tt.dynamic.count.rule']
        cls.Counter = cls.env['tt.dynamic.count.counter']
        cls.location_b = cls.env['stock.location'].create({
            'name': 'Quantity Internal B',
            'usage': 'internal',
            'location_id': cls.warehouse_1.view_location_id.id,
        })

    def _rule(self, **values):
        return self.Rule.create({
            'name': 'Cumulative Activity',
            'company_id': self.env.company.id,
            'trigger_type': 'cumulative_qty',
            'threshold': 500,
            'location_id': self.stock_location.id,
            **values,
        })

    def _counter(self, rule, location=None, product=None):
        return self.Counter.search([
            ('rule_id', '=', rule.id),
            ('product_id', '=', (product or self.productA).id),
            ('location_id', '=', (location or self.stock_location).id),
        ])

    def _move(self, qty, src=None, dst=None, product=None, uom=None,
              demand=None, lines=None, complete=True, **values):
        product = product or self.productA
        src = src or self.supplier_location
        dst = dst or self.stock_location
        uom = uom or product.uom_id
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom': uom.id,
            'product_uom_qty': qty if demand is None else demand,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'state': 'confirmed',
            **values,
        })
        for line in lines if lines is not None else [{'quantity': qty}]:
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'product_id': product.id,
                'product_uom_id': uom.id,
                'location_id': src.id,
                'location_dest_id': dst.id,
                **line,
            })
        move.picked = True
        if complete:
            move._action_done()
        return move

    def _stock(self, qty=1000, location=None):
        self.env['stock.quant']._update_available_quantity(
            self.productA, location or self.stock_location, qty)

    def _apply_count(self, difference=0):
        quant = self.env['stock.quant']._gather(
            self.productA, self.stock_location, strict=True)
        quant.ensure_one()
        quant.inventory_quantity = quant.quantity + difference
        quant.with_context(inventory_mode=True)._apply_inventory()

    def test_below_threshold_499(self):
        rule = self._rule()
        for qty in (100, 150, 249):
            self._move(qty)
        counter = self._counter(rule)
        self.assertEqual(counter.cumulative_qty, 499)
        self.assertEqual(counter.move_count, 0)
        self.assertFalse(counter.count_requested)

    def test_exact_threshold_500(self):
        rule = self._rule()
        self._move(499)
        self._move(1)
        counter = self._counter(rule)
        self.assertEqual(counter.cumulative_qty, 500)
        self.assertTrue(counter.count_requested)
        quants = self.env['stock.quant']._gather(self.productA, self.stock_location, strict=True)
        self.assertTrue(quants)
        self.assertTrue(all(q.inventory_date <= Date.context_today(q) for q in quants))

    def test_pending_525_no_duplicate_native_request(self):
        rule = self._rule()
        Move = type(self.env['stock.move'])
        with patch.object(Move, '_tt_request_native_count', autospec=True,
                          side_effect=Move._tt_request_native_count) as request:
            self._move(500)
            self._move(25)
        counter = self._counter(rule)
        self.assertEqual(counter.cumulative_qty, 525)
        self.assertTrue(counter.count_requested)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(self._counter(rule)), 1)

    def test_incoming_quantity(self):
        rule = self._rule()
        self._move(100)
        self.assertEqual(self._counter(rule).cumulative_qty, 100)

    def test_outgoing_adds_absolute_quantity(self):
        rule = self._rule()
        self._stock()
        self._move(40, src=self.stock_location, dst=self.customer_location)
        self.assertEqual(self._counter(rule).cumulative_qty, 40)

    def test_internal_transfer_each_endpoint_receives_25(self):
        rule = self._rule(location_id=False)
        self._stock()
        self._move(25, src=self.stock_location, dst=self.location_b)
        self.assertEqual(self._counter(rule).cumulative_qty, 25)
        self.assertEqual(self._counter(rule, self.location_b).cumulative_qty, 25)
        self.assertEqual(self.Counter.search_count([('rule_id', '=', rule.id)]), 2)

    def test_return_adds_activity(self):
        rule = self._rule()
        self._stock()
        delivery = self._move(40, src=self.stock_location, dst=self.customer_location)
        self._move(10, src=self.customer_location,
                   origin_returned_move_id=delivery.id)
        self.assertEqual(self._counter(rule).cumulative_qty, 50)

    def test_multiple_lots_40_plus_60_equals_100(self):
        rule = self._rule()
        movement_rule = self._rule(trigger_type='move_count', threshold=10)
        self.productA.tracking = 'lot'
        lots = self.env['stock.lot'].create([
            {'name': name, 'product_id': self.productA.id, 'company_id': self.env.company.id}
            for name in ('Activity Lot A', 'Activity Lot B')
        ])
        move = self._move(100, lines=[
            {'quantity': 40, 'lot_id': lots[0].id},
            {'quantity': 60, 'lot_id': lots[1].id},
        ])
        self.assertEqual(move.quantity, 100)
        self.assertEqual(len(move.move_line_ids), 2)
        self.assertEqual(self._counter(rule).cumulative_qty, 100)
        self.assertEqual(self._counter(movement_rule).move_count, 1)

    def test_decimal_threshold_and_quantities(self):
        rule = self._rule(threshold=12.5)
        self._move(0.5)
        self._move(1.25)
        self.assertAlmostEqual(self._counter(rule).cumulative_qty, 1.75)
        self.assertFalse(self._counter(rule).count_requested)
        self._move(10.75)
        self.assertAlmostEqual(self._counter(rule).cumulative_qty, 12.5)
        self.assertTrue(self._counter(rule).count_requested)

    def test_decimal_comparison_uses_uom_precision(self):
        rule = self._rule(threshold=0.3)
        for qty in (0.1, 0.1, 0.1):
            self._move(qty)
        self.assertAlmostEqual(self._counter(rule).cumulative_qty, 0.3)
        self.assertTrue(self._counter(rule).count_requested)

    def test_dozen_normalized_to_product_base_unit(self):
        self.assertEqual(self.productA.uom_id, self.uom_unit)
        rule = self._rule(threshold=100)
        move = self._move(5, uom=self.uom_dozen)
        self.assertEqual(move.quantity, 5)
        self.assertEqual(move.product_uom, self.uom_dozen)
        self.assertEqual(self._counter(rule).cumulative_qty, 60)
        self.assertFalse(self._counter(rule).count_requested)
        self._move(40)
        self.assertEqual(self._counter(rule).cumulative_qty, 100)
        self.assertTrue(self._counter(rule).count_requested)

    def test_mixed_line_uoms_and_locations(self):
        rule = self._rule(location_id=False)
        move = self._move(100, lines=[
            {'quantity': 5, 'product_uom_id': self.uom_dozen.id},
            {'quantity': 40, 'location_dest_id': self.location_b.id},
        ])
        self.assertEqual(move.quantity, 100)
        self.assertEqual(self._counter(rule).cumulative_qty, 60)
        self.assertEqual(self._counter(rule, self.location_b).cumulative_qty, 40)

    def test_partial_completion_and_real_backorder(self):
        rule = self._rule(threshold=100)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type_in.id,
            'location_id': self.supplier_location.id,
            'location_dest_id': self.stock_location.id,
        })
        move = self._move(60, demand=100, picking_id=picking.id)
        self.assertEqual(move.state, 'done')
        self.assertEqual(move.quantity, 60)
        self.assertEqual(self._counter(rule).cumulative_qty, 60)
        self.assertFalse(self._counter(rule).count_requested)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        backorder.ensure_one()
        remaining = backorder.move_ids
        remaining.ensure_one()
        self.assertNotEqual(remaining.state, 'done')
        self.assertEqual(remaining.product_uom_qty, 40)
        remaining.quantity = 40
        remaining.picked = True
        remaining._action_done()
        self.assertEqual(remaining.state, 'done')
        self.assertEqual(self._counter(rule).cumulative_qty, 100)
        self.assertTrue(self._counter(rule).count_requested)

    def test_partial_cancel_backorder_only_actual_quantity(self):
        rule = self._rule(threshold=100)
        move = self._move(60, demand=100, complete=False)
        move._action_done(cancel_backorder=True)
        self.assertEqual(move.quantity, 60)
        self.assertEqual(self._counter(rule).cumulative_qty, 60)
        self.assertFalse(self._counter(rule).count_requested)

    def test_inventory_reconciliation_never_registers_quantity(self):
        rule = self._rule(threshold=1)
        self._move(10)
        Counter = type(self.Counter)
        with patch.object(Counter, '_register_quantity', autospec=True,
                          side_effect=Counter._register_quantity) as register:
            self._apply_count(difference=5)
        register.assert_not_called()
        reconciliation = self.env['stock.move'].search([
            ('product_id', '=', self.productA.id), ('is_inventory', '=', True),
            ('state', '=', 'done'), ('location_dest_id', '=', self.stock_location.id),
        ])
        self.assertTrue(reconciliation)
        counter = self._counter(rule)
        self.assertEqual(counter.cumulative_qty, 0)
        self.assertFalse(counter.count_requested)
        self.assertTrue(counter.last_reset_date)

    def test_count_completion_resets_and_can_request_again(self):
        rule = self._rule(threshold=10)
        self._move(10)
        self._apply_count()
        counter = self._counter(rule)
        self.assertEqual(counter.cumulative_qty, 0)
        self.assertEqual(counter.move_count, 0)
        self.assertFalse(counter.count_requested)
        self.assertTrue(counter.last_reset_date)
        self._move(10)
        self.assertEqual(counter.cumulative_qty, 10)
        self.assertTrue(counter.count_requested)

    def test_simultaneous_triggers_are_independent_and_both_reset(self):
        quantity_rule = self._rule(threshold=100)
        movement_rule = self._rule(trigger_type='move_count', threshold=2)
        self._move(60)
        self._move(1)
        qty_counter = self._counter(quantity_rule)
        move_counter = self._counter(movement_rule)
        self.assertEqual(qty_counter.cumulative_qty, 61)
        self.assertEqual(qty_counter.move_count, 0)
        self.assertFalse(qty_counter.count_requested)
        self.assertEqual(move_counter.move_count, 2)
        self.assertEqual(move_counter.cumulative_qty, 0)
        self.assertTrue(move_counter.count_requested)
        self._move(39)
        self.assertTrue(qty_counter.count_requested)
        self.assertEqual(move_counter.move_count, 3)
        self._apply_count()
        for counter in qty_counter | move_counter:
            self.assertEqual(counter.move_count, 0)
            self.assertEqual(counter.cumulative_qty, 0)
            self.assertFalse(counter.count_requested)
            self.assertTrue(counter.last_reset_date)

    def test_count_also_resets_below_threshold_counters(self):
        quantity_rule = self._rule(threshold=100)
        movement_rule = self._rule(trigger_type='move_count', threshold=1)
        self._move(10)
        self.assertFalse(self._counter(quantity_rule).count_requested)
        self._apply_count()
        for counter in self._counter(quantity_rule) | self._counter(movement_rule):
            self.assertEqual(counter.move_count, 0)
            self.assertEqual(counter.cumulative_qty, 0)
            self.assertFalse(counter.count_requested)
            self.assertTrue(counter.last_reset_date)

    def test_simultaneous_thresholds_request_pair_once(self):
        self._rule(threshold=100)
        self._rule(trigger_type='move_count', threshold=1)
        Move = type(self.env['stock.move'])
        with patch.object(Move, '_tt_request_native_count', autospec=True,
                          side_effect=Move._tt_request_native_count) as request:
            self._move(100)
        request.assert_called_once()
        self.assertEqual(len(request.call_args.args[1]), 1)

    def test_product_scope(self):
        rule = self._rule(product_id=self.productA.id)
        self._move(100, product=self.productB)
        self.assertFalse(self._counter(rule, product=self.productB))
        self._move(10)
        self.assertEqual(self._counter(rule).cumulative_qty, 10)

    def test_category_scope(self):
        category = self.env['product.category'].create({'name': 'Quantity Category'})
        self.productA.categ_id = category
        rule = self._rule(product_categ_id=category.id)
        self._move(100, product=self.productB)
        self.assertFalse(self._counter(rule, product=self.productB))
        self._move(10)
        self.assertEqual(self._counter(rule).cumulative_qty, 10)

    def test_location_scope(self):
        rule = self._rule()
        self._move(100, dst=self.location_b)
        self.assertFalse(self._counter(rule, location=self.location_b))
        self._move(10)
        self.assertEqual(self._counter(rule).cumulative_qty, 10)

    def test_company_isolation_and_stock_user_access(self):
        company2 = self.env['res.company'].create({'name': 'Quantity Other Company'})
        location2 = self.env['stock.location'].create({
            'name': 'Other Company Stock', 'usage': 'internal', 'company_id': company2.id,
        })
        rule1 = self._rule(location_id=False)
        rule2 = self._rule(company_id=company2.id, location_id=False)
        self._move(10)
        self._move(20, dst=location2, company_id=company2.id)
        counter1 = self._counter(rule1)
        counter2 = self._counter(rule2, location2)
        self.assertEqual(counter1.cumulative_qty, 10)
        self.assertEqual(counter2.cumulative_qty, 20)
        self.assertFalse(self._counter(rule2))
        self.assertFalse(self._counter(rule1, location2))
        UserCounter = self.Counter.with_user(self.user_stock_user).with_context(
            allowed_company_ids=[self.env.company.id])
        self.assertEqual(UserCounter.search([('id', 'in', (counter1 | counter2).ids)]).ids,
                         counter1.ids)
        UserRule = self.Rule.with_user(self.user_stock_user).with_context(
            allowed_company_ids=[self.env.company.id])
        self.assertEqual(UserRule.search([('id', 'in', (rule1 | rule2).ids)]).ids, rule1.ids)
        with self.assertRaises(AccessError):
            UserCounter.browse(counter1.id).write({'cumulative_qty': 999})

    def test_inactive_rule(self):
        rule = self._rule(active=False)
        self._move(100)
        self.assertFalse(self._counter(rule))

    def test_earlier_native_inventory_date_preserved(self):
        rule = self._rule(threshold=10)
        self._stock()
        quant = self.env['stock.quant']._gather(self.productA, self.stock_location, strict=True)
        earlier = Date.context_today(quant) - timedelta(days=5)
        quant.inventory_date = earlier
        self._move(10, src=self.stock_location, dst=self.customer_location)
        self.assertTrue(self._counter(rule).count_requested)
        self.assertEqual(quant.inventory_date, earlier)

    def test_draft_cancelled_and_already_done_moves(self):
        rule = self._rule()
        draft = self._move(10, complete=False, state='draft')
        self.assertFalse(self._counter(rule))
        draft._action_cancel()
        self.assertFalse(self._counter(rule))
        done = self._move(10)
        done._action_done()
        self.assertEqual(self._counter(rule).cumulative_qty, 10)

    def test_default_preserves_movement_trigger(self):
        rule = self.Rule.create({'name': 'Legacy default', 'threshold': 3})
        self.assertEqual(rule.trigger_type, 'move_count')
        self._move(10)
        counter = self._counter(rule)
        self.assertEqual(counter.move_count, 1)
        self.assertEqual(counter.cumulative_qty, 0)
        self.assertFalse(counter.count_requested)

    @mute_logger('odoo.sql_db')
    def test_threshold_validation(self):
        for trigger, threshold in [('move_count', 1.25), ('cumulative_qty', 0),
                                   ('cumulative_qty', -1)]:
            with self.assertRaises(IntegrityError):
                self._rule(trigger_type=trigger, threshold=threshold)
                self.env.flush_all()
        self.assertEqual(self._rule(threshold=1.25).threshold, 1.25)
