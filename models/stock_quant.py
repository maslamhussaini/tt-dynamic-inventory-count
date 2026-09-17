from odoo import models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _apply_inventory(self, date=None):
        # Capture the (product, location) pairs before the native counting
        # logic clears `inventory_quantity` / `inventory_quantity_set` on
        # `self`. `super()` internally creates the reconciliation move with
        # `is_inventory=True` and runs it through `stock.move._action_done`,
        # which our own override always ignores for counter purposes - so
        # this reset can never race with, or be undone by, that reconciled
        # movement re-incrementing the same counters.
        pairs = [(quant.product_id, quant.location_id) for quant in self]

        super()._apply_inventory(date=date)

        # If the write above raises, this reset code never runs and the
        # whole apply, including the reconciliation move, is rolled back
        # by the surrounding Odoo transaction - counters are only reset on
        # an actually-applied count.
        if pairs:
            self.env['tt.dynamic.count.counter'].sudo()._tt_reset_for_pairs(pairs)
