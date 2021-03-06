# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged, TransactionCase
from odoo.addons.sale.tests.test_sale_product_attribute_value_config import TestSaleProductAttributeValueSetup


@tagged('post_install', '-at_install')
class TestUi(TestSaleProductAttributeValueSetup, HttpCase):

    def setUp(self):
        super(TestUi, self).setUp()

        # set currency to not rely on demo data and avoid possible race condition
        self.currency_ratio = 1.0
        pricelist = self.env.ref('product.list0')
        pricelist.currency_id = self._setup_currency(self.currency_ratio)

    def test_01_admin_shop_sale_coupon_tour(self):
        # pre enable "Show # found" option to avoid race condition...
        self.env.ref("website_sale.search_count_box").write({"active": True})
        self.start_tour("/", 'shop_sale_coupon', login="admin")


@tagged('post_install', '-at_install')
class TestWebsiteSaleCoupon(TransactionCase):

    def setUp(self):
        super(TestWebsiteSaleCoupon, self).setUp()
        program = self.env['sale.coupon.program'].create({
            'name': '10% TEST Discount',
            'promo_code_usage': 'code_needed',
            'discount_apply_on': 'on_order',
            'discount_type': 'percentage',
            'discount_percentage': 10.0,
            'program_type': 'coupon_program',
        })

        self.env['sale.coupon.generate'].with_context(active_id=program.id).create({}).generate_coupon()
        self.coupon = program.coupon_ids[0]

        self.steve = self.env['res.partner'].create({
            'name': 'Steve Bucknor',
            'email': 'steve.bucknor@example.com',
        })
        self.empty_order = self.env['sale.order'].create({
            'partner_id': self.steve.id
        })

    def test_01_gc_coupon(self):
        # 1. Simulate a frontend order (website, product)
        order = self.empty_order
        order.website_id = self.env['website'].browse(1)
        self.env['sale.order.line'].create({
            'product_id': self.env['product.product'].create({
                'name': 'Product A',
                'list_price': 100,
                'sale_ok': True,
            }).id,
            'name': 'Product A',
            'product_uom_qty': 2.0,
            'order_id': order.id,
        })

        # 2. Apply the coupon
        self.env['sale.coupon.apply.code'].with_context(active_id=order.id).create({
            'coupon_code': self.coupon.code
        }).process_coupon()
        order.recompute_coupon_lines()

        self.assertEqual(len(order.applied_coupon_ids), 1, "The coupon should've been applied on the order")
        self.assertEqual(self.coupon, order.applied_coupon_ids)
        self.assertEqual(self.coupon.state, 'used')

        # 3. Test recent order -> Should not be removed
        order._garbage_collector()

        self.assertEqual(len(order.applied_coupon_ids), 1, "The coupon shouldn't have been removed from the order no more than 4 days")
        self.assertEqual(self.coupon.state, 'used', "Should not have been changed")

        # 4. Test order not older than ICP validity -> Should not be removed
        ICP = self.env['ir.config_parameter']
        icp_validity = ICP.create({'key': 'website_sale_coupon.abandonned_coupon_validity', 'value': 5})
        order.flush()
        query = """UPDATE %s SET write_date = %%s WHERE id = %%s""" % (order._table,)
        self.env.cr.execute(query, (fields.Datetime.to_string(fields.datetime.now() - timedelta(days=4, hours=2)), order.id))
        order._garbage_collector()

        self.assertEqual(len(order.applied_coupon_ids), 1, "The coupon shouldn't have been removed from the order the order is 4 days old but icp validity is 5 days")
        self.assertEqual(self.coupon.state, 'used', "Should not have been changed (2)")

        # 5. Test order with no ICP and older then 4 default days -> Should be removed
        icp_validity.unlink()
        order._garbage_collector()

        self.assertEqual(len(order.applied_coupon_ids), 0, "The coupon should've been removed from the order as more than 4 days")
        self.assertEqual(self.coupon.state, 'new', "Should have been reset.")
