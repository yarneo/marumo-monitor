import unittest
from unittest.mock import patch
from datetime import datetime
import monitor
from monitor import JST, classify, target_times


class AvailabilityTests(unittest.TestCase):
    def test_dropdown_times_are_not_availability(self):
        with self.assertRaises(ValueError):
            classify("Select Time 5:00 PM 5:30 PM Next Step")

    def test_explicit_results(self):
        self.assertTrue(classify("Please complete form and continue to confirmation page."))
        self.assertFalse(classify("No tables are available for 1 Person on 2026-10-26"))
        self.assertFalse(classify("No table is available for 1 Person on October 26, 2026 (Mon) 21:00"))
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

    def run_two_checks(self, delivery):
        slots = ["2026-10-26 18:00"]
        with patch.dict(monitor.os.environ, {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"}), \
                patch.object(monitor, "END", datetime(2099, 1, 1, tzinfo=JST)), \
                patch.object(monitor, "STATUS", monitor.STATUS.copy()), \
                patch.object(monitor, "fetch", return_value=slots) as fetch, \
                patch.object(monitor, "send", side_effect=delivery), \
                patch.object(monitor.time, "sleep", side_effect=[None, StopIteration]):
            with self.assertRaises(StopIteration):
                monitor.monitor_loop()
            self.assertEqual(fetch.call_count, 2)

    def test_opening_alert_is_sent_once_across_repeat_checks(self):
        sent = []
        self.run_two_checks(lambda message: sent.append(message))
        alerts = [message for message in sent if message.startswith("Pizza Marumo:")]
        self.assertEqual(len(alerts), 1)
        self.assertIn("2026-10-26 18:00", alerts[0])
        self.assertIn("pax_adult=1", alerts[0])
        self.assertIn("No reservation has been made", alerts[0])

    def test_failed_opening_delivery_is_retried(self):
        attempts, delivered = [], []
        def deliver(message):
            if message.startswith("Pizza Marumo:"):
                attempts.append(message)
                if len(attempts) == 1:
                    raise OSError("Temporary delivery failure")
            delivered.append(message)
        self.run_two_checks(deliver)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(sum(message.startswith("Pizza Marumo:") for message in delivered), 1)


if __name__ == "__main__":
    unittest.main()
