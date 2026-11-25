from decimal import Decimal
from types import SimpleNamespace
import unittest

from booking_pricing import apply_half_hour_reward, calculate, reward_eligible


class BookingRewardPricingTest(unittest.TestCase):
    def day(self, **overrides):
        day = dict(date='2027-01-01', start_time='10:00', finish_time='12:00', publicity_type='Private',
                   charge_type='Client', pitch_fee_required=False, travel_miles='25', estimated_cost='90.00')
        return dict(day, **overrides)

    def quote(self, events, metadata, prior_events=None):
        booking = SimpleNamespace(total_event_cost=Decimal('0.00'), travel_charge=Decimal('0.00'))
        settings = dict(hourly_rate='45.00', minimum_hours='1', free_miles='10', mile_rate='1', travel_cap='30')
        return calculate(booking, events, prior_events or [], metadata, settings, '50% deposit')

    def test_hourly_discount_applies_once_to_first_paid_private_day(self):
        free = self.day(charge_type='Customers', estimated_cost='0.00', reward_discount='99.00')
        first = self.day(publicity_type=' private ', pitch_fee_required='no')
        second = self.day()
        events = [free, first, second]
        self.assertTrue(reward_eligible(events))
        self.assertEqual(apply_half_hour_reward(events, '45.00'), Decimal('22.50'))
        self.assertNotIn('reward_discount', free)
        self.assertEqual(first['estimated_cost'], '67.50')
        self.assertEqual(first['reward_discount'], '22.50')
        self.assertEqual(second['estimated_cost'], '90.00')
        self.assertNotIn('reward_discount', second)

    def test_package_discount_uses_half_hour_of_package_rate_and_caps_at_day_cost(self):
        package = dict(price='120.00', hours='2')
        day = self.day(estimated_cost='120.00')
        self.assertEqual(apply_half_hour_reward([day], '45.00', package), Decimal('30.00'))
        self.assertEqual(day['estimated_cost'], '90.00')
        low_cost = self.day(estimated_cost='10.00')
        self.assertEqual(apply_half_hour_reward([low_cost], '45.00', package), Decimal('10.00'))
        self.assertEqual(low_cost['estimated_cost'], '0.00')

    def test_quote_preserves_extras_and_travel_and_rebuilds_existing_discount(self):
        day = self.day(reward_discount='22.50', estimated_cost='67.50', _original_index=0)
        original = [day]
        metadata = {'booking_reward': {'code': 'ABCDE'},
                    'intake_options': {'extras': [{'name': 'Extra', 'price': '10.00'}]}}
        events, _, _, quote = self.quote([day], metadata, original)
        self.assertEqual(events[0]['estimated_cost'], '67.50')
        self.assertEqual(events[0]['reward_discount'], '22.50')
        self.assertEqual(quote['reward_discount'], '22.50')
        self.assertEqual(quote['extras'], '10.00')
        self.assertEqual(quote['event_total'], '77.50')
        self.assertEqual(quote['travel'], '15.00')
        self.assertEqual(quote['total'], '92.50')
        self.assertEqual(quote['deposit'], '46.25')

        events, _, _, quote = self.quote([day], {'intake_options': metadata['intake_options']}, original)
        self.assertNotIn('reward_discount', events[0])
        self.assertEqual(quote['reward_discount'], '0.00')
        self.assertEqual(quote['event_total'], '100.00')

    def test_attached_reward_blocks_ineligible_edit(self):
        ineligible = ([self.day(), self.day(publicity_type='Public')], [self.day(charge_type='Revenue sharing')],
                      [self.day(pitch_fee_required=True)])
        for days in ineligible:
            with self.subTest(days=days), self.assertRaisesRegex(ValueError, 'attached referral reward'):
                self.quote(days, {'booking_reward': {'code': 'ABCDE'}})
