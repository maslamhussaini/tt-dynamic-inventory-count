# TriangleTech Dynamic Inventory Count

Activity-based cycle counting for Odoo 19 Community. Requests a physical
inventory count once a product/location combination has accumulated enough
real stock activity, instead of relying only on a fixed calendar frequency.

## Requirements

- Odoo 19 Community
- The `stock` (Inventory) app

No other dependencies are required.

## Installation

1. Copy this module into your Odoo `addons` path.
2. Update the apps list and install **TriangleTech Dynamic Inventory Count**.

## Configuration

1. Go to **Inventory → Configuration → Dynamic Count Rules** (requires
   Inventory / Administrator access).
2. Create a rule with:
   - A name
   - A trigger type: **Move Count** or **Cumulative Quantity**
   - A threshold
   - Optional scope: product, product category (exact match only), and/or
     location
3. Save. As matching stock moves complete, the module accumulates activity
   automatically.
4. Pending counts are visible under **Inventory → Dynamic Counts** and
   surface through Odoo's native Physical Inventory workflow.

## Trigger Types

### Move Count

Counts completed stock moves for a matching product/location. Once the
number of completed moves reaches the configured whole-number threshold, a
count is requested.

### Cumulative Quantity

Sums the absolute quantity of stock activity (not net change) for a
matching product/location, normalized to the product's base unit of
measure. Once the accumulated quantity reaches the configured threshold, a
count is requested.

Both incoming and outgoing activity — receipts, deliveries, internal
transfers, and returns — add to cumulative activity.

## Example

Rule: Trigger Type = *Move Count*, Threshold = `20`, Product Category =
*Fasteners*.

After 20 completed stock moves touching any product in the Fasteners
category at a given location, that product/location pair is flagged for a
physical count. Applying the count through Odoo's native Physical Inventory
flow resets the counter, which then begins accumulating again.

## Permissions

| Group | Dynamic Count Rules | Dynamic Count Counters |
|---|---|---|
| Inventory / User (`stock_user`) | Read-only | Read-only |
| Inventory / Administrator (`stock_manager`) | Full CRUD | Full CRUD |

Multi-company isolation is enforced via standard `ir.rule` record rules on
both models.

## Known Limitations (this version)

- Only internal and transit locations are supported for counting scope.
- Location scoping matches a specific location only — no sub-location
  hierarchy.
- Product category scoping is an exact match — no recursive sub-category
  matching.
- No cron-based periodic recheck; accumulation is driven entirely by
  completed stock moves.
- No Max Days aging trigger and no variance/recount workflow in this
  version.
- Product/location pairs with zero quants are not shown in the native
  Inventory due-list until quants exist.

## Support

Published and maintained by **TriangleTech**.
Website: https://triangletech.co
