{
    'name': "TriangleTech Dynamic Inventory Count",
    'summary': "Trigger physical inventory counts from actual stock movement activity.",
    'description': """
Extends Inventory so a physical count can be requested once a configurable
number of completed stock movements or cumulative quantity of stock activity
has occurred for a product at a location. Quantity is normalized to each
product's base unit of measure and measures absolute activity, not net change.

Reuses native stock.quant physical inventory counting. Supports movement-count
and cumulative-quantity triggers only.
""",
    'author': "TriangleTech",
    'maintainer': "TriangleTech",
    'website': "https://triangletech.co",
    'category': 'Supply Chain/Inventory',
    'version': '19.0.2.0.0',
    'license': 'OPL-1',
    'depends': ['stock'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/tt_dynamic_count_rule_views.xml',
        'views/tt_dynamic_count_counter_views.xml',
    ],
    'installable': True,
    'application': False,
}
