import unittest
from datetime import datetime
from monitor import JST, classify, target_times


class AvailabilityTests(unittest.TestCase):
    def test_dropdown_times_are_not_availability(self):
        with self.assertRaises(ValueError):
            classify("Select Time 5:00 PM 5:30 PM Next Step")

    def test_explicit_results(self):
        self.assertTrue(classify("Please complete form and continue to confirmation page."))
        self.assertFalse(classify("No tables are available for 1 Person on 2026-10-26"))
        self.assertFalse(classify("Number of Guests must be greater than or equal to 2"))

    def test_conflicting_stale_result_is_unknown(self):
        with self.assertRaises(ValueError):
            classify("Please complete form and continue to confirmation page. No tables are available")

    def test_october_26_lunch_is_excluded(self):
        values = [str(int(datetime(2026, 10, 26, hour, tzinfo=JST).timestamp())) for hour in (12, 18)]
        self.assertEqual([s[1] for s in target_times(values, "2026-10-26")], ["2026-10-26 18:00"])

    def test_wrong_date_is_rejected(self):
        value = str(int(datetime(2026, 10, 27, 18, tzinfo=JST).timestamp()))
        with self.assertRaises(ValueError):
            target_times([value], "2026-10-26")


if __name__ == "__main__":
    unittest.main()
