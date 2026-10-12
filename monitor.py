"""Read-only Marumo reservation searches. Never books or fills guest details."""
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
BOOKING = "https://www.tablecheck.com/en/shops/pizza-marumo/reserve"
COUNTER = "638810bdddd29900402b47e3"
DATES = ["2026-10-26", "2026-10-27", "2026-10-28"]
END = datetime(2026, 10, 28, 22, tzinfo=JST)
STATUS = {"phase": "starting", "last_success": None, "failures": 0,
          "successful_checks": 0, "telegram_deliveries": 0, "last_delivery": None,
          "search": None, "slots_checked": 0, "bookable_slots": None}
LOCK = threading.Lock()
LOG = logging.getLogger("marumo")


def classify(text):
    positive = re.search(r"Please complete (?:the )?form and continue to (?:the )?confirmation page", text, re.I)
    negative = re.search(r"No tables? (?:are|is) available|no availability|not available for online booking|Number of Guests must", text, re.I)
    if positive and negative:
        raise ValueError("Conflicting booking results")
    if negative:
        return False
    if positive:
        return True
    raise ValueError("No explicit availability result")


def target_times(options, day):
    slots = []
    for raw in options:
        if not str(raw).isdigit():
            continue
        epoch = int(raw)
        if epoch > 10**12:
            epoch //= 1000
        at = datetime.fromtimestamp(epoch, JST)
        if at.strftime("%Y-%m-%d") != day:
            raise ValueError("Time dropdown contains a different date")
        minute = at.hour * 60 + at.minute
        lunch = 11 * 60 <= minute <= 14 * 60
        dinner = 17 * 60 <= minute <= 21 * 60 + 30
        if dinner or (day != DATES[0] and lunch):
            slots.append((str(raw), at.strftime("%Y-%m-%d %H:%M"), "dinner" if dinner else "lunch"))
    if not slots:
        raise ValueError("No target times available to validate")
    return slots


def send(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    body = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT_ID"],
        "text": message, "disable_web_page_preview": "true"}).encode()
    request = urllib.request.Request("https://api.telegram.org/bot" + token + "/sendMessage", data=body)
    with urllib.request.urlopen(request, timeout=25) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise ValueError("Telegram rejected delivery")
    with LOCK:
        STATUS["telegram_deliveries"] += 1
        STATUS["last_delivery"] = datetime.now(JST).isoformat()
    LOG.info("Telegram delivery confirmed")
    return result["result"]["message_id"]


def fetch():
    from playwright.sync_api import sync_playwright
    found = set()
    with LOCK:
        STATUS["slots_checked"] = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        try:
            page = browser.new_page(locale="en-US", timezone_id="Asia/Tokyo")
            page.set_default_timeout(20000)
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in
                       ("image", "media", "font") else route.continue_())
            for day in DATES:
                meals = ("dinner",) if day == DATES[0] else ("lunch", "dinner")
                for meal in meals:
                    LOG.info("Searching %s %s", day, meal)
                    with LOCK:
                        STATUS["search"] = day + " " + meal
                    first_time = "11:30" if meal == "lunch" else "17:00"
                    page.goto(BOOKING + "?" + urllib.parse.urlencode({"start_date": day,
                        "start_time": first_time, "pax_adult": 1, "service_category_id": COUNTER}),
                        wait_until="domcontentloaded", timeout=60000)
                    page.locator("#reservation_confirm_shop_note").check()
                    adults = page.locator("#reservation_num_people_adult")
                    adults.select_option("1")
                    counter = page.locator("#reservation_service_category_" + COUNTER)
                    if not counter.is_checked():
                        counter.locator("..").click()
                    date = page.locator("#reservation_start_date").input_value()
                    if date != day:
                        raise ValueError("Requested date was not applied")
                    times = page.locator("#reservation_start_at_epoch")
                    page.wait_for_function("!document.querySelector('#reservation_start_at_epoch').disabled")
                    options = times.locator("option").evaluate_all("els => els.map(el => el.value)")
                    index = "0" if meal == "lunch" else "1"
                    plan = page.locator("#reservation_orders_attributes_" + index + "_is_group_order")
                    if not plan.is_checked():
                        plan.locator("..").click()
                    for value, slot, slot_meal in target_times(options, day):
                        if slot_meal != meal:
                            continue
                        if datetime.strptime(slot, "%Y-%m-%d %H:%M").replace(tzinfo=JST) <= datetime.now(JST):
                            continue
                        times.select_option(value)
                        page.wait_for_timeout(5500)
                        page.wait_for_load_state("networkidle", timeout=20000)
                        if (times.input_value() != value or adults.input_value() != "1"
                                or not counter.is_checked() or not plan.is_checked()
                                or page.locator("#reservation_start_date").input_value() != day):
                            raise ValueError("Search filters changed unexpectedly")
                        if classify(page.locator("body").inner_text()):
                            page.wait_for_timeout(1000)
                            if not classify(page.locator("body").inner_text()):
                                raise ValueError("Availability changed during validation")
                            found.add(slot)
                        with LOCK:
                            STATUS["slots_checked"] += 1
            return sorted(found)
        except Exception as exc:
            # This scope only handles the public booking browser, never Telegram.
            LOG.warning("Booking browser failed: %s", str(exc)[:2000])
            raise
        finally:
            browser.close()


def monitor_loop():
    prior, pending = set(), []
    announced, health_warned, delivery_tested = False, False, False
    interval = max(300, int(os.environ.get("CHECK_INTERVAL_SECONDS", "300")))
    while True:
        started = time.monotonic()
        if datetime.now(JST) >= END:
            with LOCK:
                STATUS["phase"] = "finished"
            return
        if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
            with LOCK:
                STATUS["phase"] = "needs_telegram_settings"
            time.sleep(30)
            continue
        try:
            if not delivery_tested:
                send("Marumo cloud monitor: Telegram delivery test. Availability checks have not yet been verified; another message will confirm the first successful check.")
                delivery_tested = True
            while pending:
                send(pending[0])
                pending.pop(0)
            with LOCK:
                STATUS["phase"] = "checking"
            slots = set(fetch())
            new = sorted(slots - prior)
            if new:
                lines = ["Pizza Marumo: bookable openings for 1 person, counter (Tokyo time):"]
                for slot in new:
                    day, clock = slot.split()
                    lines.extend([slot, BOOKING + "?" + urllib.parse.urlencode({"start_date": day,
                        "start_time": clock, "pax_adult": 1, "service_category_id": COUNTER})])
                lines.append("No reservation has been made. Availability may change.")
                pending.append("\n".join(lines))
            if health_warned:
                pending.append("Marumo availability checks have recovered.")
                health_warned = False
            if not announced:
                pending.append("Marumo cloud monitor: first successful availability check completed for 1 person, counter; October 26 dinner and October 27–28 lunch/dinner, 2026. " +
                    ("Openings found (see alert)." if slots else "No bookable seats found.") +
                    " Checks roughly every 5 minutes while the free service is running. Render can sleep unless the external scheduler is configured.")
                announced = True
            prior = slots
            while pending:
                send(pending[0])
                pending.pop(0)
            with LOCK:
                STATUS.update(phase="running", last_success=datetime.now(JST).isoformat(), failures=0,
                              bookable_slots=len(slots), search=None)
                STATUS["successful_checks"] += 1
            LOG.info("Successful check; %d bookable slots", len(slots))
        except Exception as exc:
            with LOCK:
                STATUS["phase"] = "check_or_delivery_failed"
                STATUS["failures"] += 1
                failures = STATUS["failures"]
            # Log only exception types; URLs could contain Telegram credentials.
            LOG.warning("Check/delivery failed: %s", type(exc).__name__)
            if failures >= 3 and not health_warned:
                pending.append("Marumo monitor: three consecutive checks or Telegram deliveries failed. Availability is unknown; retrying. Check the service logs.")
                health_warned = True
        time.sleep(max(10, interval - (time.monotonic() - started)))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health"):
            self.send_error(404)
            return
        with LOCK:
            data = json.dumps(STATUS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    threading.Thread(target=monitor_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), Handler).serve_forever()
