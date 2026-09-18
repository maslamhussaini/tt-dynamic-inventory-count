from odoo.addons.stock.tests.common import TestStockCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestDynamicCountDashboard(TestStockCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env['tt.dynamic.count.rule']
        cls.Counter = cls.env['tt.dynamic.count.counter']
        cls.Dashboard = cls.env['tt.dynamic.count.dashboard']

    def _move(self, product, src, dst, qty=1.0, **values):
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'state': 'confirmed',
            **values,
        })
        move._action_assign()
        move.move_line_ids.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def _counter(self, rule, product, location):
        return self.Counter.search([
            ('rule_id', '=', rule.id),
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ])

    def test_kpis_basic_counts(self):
        before = self.Dashboard.get_kpis()
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 100)
        rule_move = self.Rule.create({
            'name': 'Move Rule',
            'company_id': self.env.company.id,
            'trigger_type': 'move_count',
            'threshold': 1,
            'product_id': self.productA.id,
            'location_id': self.stock_location.id,
        })
        rule_qty = self.Rule.create({
            'name': 'Qty Rule',
            'company_id': self.env.company.id,
            'trigger_type': 'cumulative_qty',
            'threshold': 5,
            'product_id': self.productB.id,
            'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productB, self.stock_location, 100)

        self._move(self.productA, self.stock_location, self.customer_location, 1)
        self._move(self.productB, self.stock_location, self.customer_location, 10)

        kpis = self.Dashboard.get_kpis()
        self.assertEqual(kpis['active_rules'] - before['active_rules'], 2)
        self.assertEqual(kpis['due_items'] - before['due_items'], 2)
        self.assertEqual(kpis['due_move_count'] - before['due_move_count'], 1)
        self.assertEqual(kpis['due_cumulative_qty'] - before['due_cumulative_qty'], 1)
        self.assertEqual(kpis['active_counters'] - before['active_counters'], 2)

        counter_move = self._counter(rule_move, self.productA, self.stock_location)
        self.assertTrue(counter_move.count_requested)

    def test_active_counters_excludes_archived_rule(self):
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 100)
        rule = self.Rule.create({
            'name': 'To Archive',
            'company_id': self.env.company.id,
            'trigger_type': 'move_count',
            'threshold': 1,
            'location_id': self.stock_location.id,
        })
        self._move(self.productA, self.stock_location, self.customer_location, 1)
        self.assertTrue(self._counter(rule, self.productA, self.stock_location))

        before = self.Dashboard.get_kpis()['active_counters']
        rule.active = False
        after = self.Dashboard.get_kpis()['active_counters']
        self.assertEqual(after, before - 1)

    def test_due_by_location_and_trigger_groupings(self):
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 100)
        rule = self.Rule.create({
            'name': 'Move Rule',
            'company_id': self.env.company.id,
            'trigger_type': 'move_count',
            'threshold': 1,
        })
        self._move(self.productA, self.stock_location, self.customer_location, 1)

        by_location = self.Dashboard.get_due_by_location()
        self.assertTrue(any(row['value'] >= 1 for row in by_location))

        by_trigger = self.Dashboard.get_due_by_trigger()
        move_rows = [row for row in by_trigger if row['label'] == 'Completed Movements']
        self.assertTrue(move_rows)
        self.assertGreaterEqual(move_rows[0]['value'], 1)

    def test_top_due_items_trigger_aware_formatting(self):
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 100)
        rule_move = self.Rule.create({
            'name': 'Move Rule',
            'company_id': self.env.company.id,
            'trigger_type': 'move_count',
            'threshold': 1,
            'product_id': self.productA.id,
            'location_id': self.stock_location.id,
        })
        self._move(self.productA, self.stock_location, self.customer_location, 1)

        items = self.Dashboard.get_top_due_items(limit=10)
        self.assertTrue(items)
        move_item = next(i for i in items if i['trigger_type'] == 'move_count')
        self.assertIn('movements', move_item['current_activity'])
        self.assertIn('movements', move_item['threshold'])
        self.assertTrue(move_item['count_requested'])

    def test_company_isolation(self):
        user = self.user_stock_user
        dashboard_user_c1_before = self.Dashboard.with_user(user).with_context(
            allowed_company_ids=[self.env.company.id])
        before_c1 = dashboard_user_c1_before.get_kpis()['due_items']

        company2 = self.env['res.company'].create({'name': 'Dashboard Other Company'})
        user.company_ids = [(4, company2.id)]
        location2 = self.env['stock.location'].create({
            'name': 'Dashboard Other Stock', 'usage': 'internal', 'company_id': company2.id,
        })
        customer2 = self.env.ref('stock.stock_location_customers')
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 100)
        self.env['stock.quant']._update_available_quantity(self.productA, location2, 100)

        self.Rule.create({
            'name': 'Company 1 Rule',
            'company_id': self.env.company.id,
            'trigger_type': 'move_count',
            'threshold': 1,
            'location_id': self.stock_location.id,
        })
        self.Rule.create({
            'name': 'Company 2 Rule',
            'company_id': company2.id,
            'trigger_type': 'move_count',
            'threshold': 1,
            'location_id': location2.id,
        })
        self._move(self.productA, self.stock_location, self.customer_location, 1)
        self._move(self.productA, location2, customer2, 1, company_id=company2.id)

        dashboard_c1 = self.Dashboard.with_user(user).with_context(
            allowed_company_ids=[self.env.company.id])
        kpis_c1 = dashboard_c1.get_kpis()
        self.assertEqual(kpis_c1['due_items'] - before_c1, 1)

        dashboard_c2 = self.Dashboard.with_user(user).with_context(
            allowed_company_ids=[company2.id])
        kpis_c2 = dashboard_c2.get_kpis()
        self.assertEqual(kpis_c2['due_items'], 1)

    def test_stock_user_access_respects_acl(self):
        # Scope assertions to the fixture data this test creates rather than
        # asserting an absolute due-item count across the whole database:
        # tt_dyn_count_test is a long-lived DB shared by every test method
        # in this class (and across repeated -u upgrade runs), so other
        # tests' due counters legitimately coexist here. Asserting an
        # absolute total makes the test order/history-dependent without
        # actually verifying anything more about ACL/company scoping than a
        # properly-isolated delta/membership check already does.
        dashboard_before = self.Dashboard.with_user(self.user_stock_user).with_context(
            allowed_company_ids=[self.env.company.id])
        due_items_before = dashboard_before.get_kpis()['due_items']

        rule = self.Rule.create({
            'name': 'Move Rule',
            'company_id': self.env.company.id,
            'trigger_type': 'move_count',
            'threshold': 1,
            'product_id': self.productA.id,
            'location_id': self.stock_location.id,
        })
        self.env['stock.quant']._update_available_quantity(self.productA, self.stock_location, 100)
        self._move(self.productA, self.stock_location, self.customer_location, 1)

        dashboard_as_user = self.Dashboard.with_user(self.user_stock_user).with_context(
            allowed_company_ids=[self.env.company.id])
        kpis = dashboard_as_user.get_kpis()
        # A stock_user (with read access, per ir.model.access.csv) sees this
        # test's own due counter reflected in the company-scoped total.
        self.assertEqual(kpis['due_items'] - due_items_before, 1)

        counter = self._counter(rule, self.productA, self.stock_location)
        self.assertTrue(counter.count_requested)

        items = dashboard_as_user.get_top_due_items(limit=1000)
        item_ids = {item['id'] for item in items}
        self.assertIn(counter.id, item_ids)

    def test_dashboard_action_and_menu_exist(self):
        action = self.env.ref('tt_dynamic_inventory_count.tt_dynamic_count_dashboard_action')
        self.assertEqual(action.tag, 'tt_dynamic_count_dashboard')
        menu = self.env.ref('tt_dynamic_inventory_count.tt_dynamic_count_dashboard_menu')
        self.assertEqual(menu.action.id, action.id)
