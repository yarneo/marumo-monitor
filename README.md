# Pizza Marumo solo-seat monitor

Read-only browser searches for one adult at the counter: October 26 dinner and October 27–28 lunch/dinner, 2026, Tokyo time. Sends Telegram alerts for newly bookable times. Never submits a reservation or fills guest/payment details.

## Verification status

On October 12, 2026, the full local and Render scans completed successfully. The Render scan checked 26 candidate times across all five date/meal combinations, found no bookable seats, and confirmed Telegram delivery of both its delivery test and first-success notification. Seven local tests cover result parsing, requested dates, opening-alert deduplication and delivery retry. The meal selector now clicks its visible label, and the parser accepts both singular and plural explicit unavailable messages.

The service is https://marumo-monitor.onrender.com on Render's Free plan. **The external wake-up scheduler is still pending cron-job.org account access.** The in-process five-minute loop works while the service is awake; uninterrupted remote checks have not been established. UI changes, cloud IP blocking or insufficient memory can prevent checks.

## Deploy on Render's Free web-service plan

Use this public Git repository, Docker runtime, and the **Free** instance. No persistent disk, paid cron job, database, custom domain, or other paid add-on is required. The Blueprint also declares `plan: free`.

Enter `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as private Render environment variables, never in this repository. With either value missing the service stays paused. After settings are added and the service restarts, it sends a Telegram delivery test, then a separate notification after the first successful availability scan. A delivery test alone is not proof that scans work.

Configure a free cron-job.org HTTP GET to `https://YOUR-SERVICE.onrender.com/health` every five minutes through October 28, 2026. Render Free sleeps after 15 minutes without inbound requests. The monitor runs approximately every five minutes while awake; scans may take longer and never overlap. Render can also restart or suspend a free service.

Keep payment details absent and do not upgrade any plan. Render has monthly free-instance hours, bandwidth and build limits; without a payment method exceeding limits suspends service rather than charging. Other services in the same workspace share some quotas. Consult current Render billing settings if a payment method was previously added.

Free Render storage is ephemeral. Settings come from environment variables and survive restarts; alert history does not. A restart can repeat a delivery test or an opening alert. No historical alert archive is promised. The monitor stops checking at 22:00 Tokyo time on October 28, 2026; remove the heartbeat job afterward.

## Status and failure handling

`/health` returns the last successful scan time, phase, failure count, completed-check count, current search and checked-slot count, and Telegram delivery count/time; never credentials. A scan is marked successful only after queued notifications are delivered. Generic time options are not treated as availability. Every candidate requires an explicit positive booking message after asynchronous validation; unknown results are failures, not "no seats". Three consecutive failures queue a Telegram health alert. Failed Telegram deliveries retry while the process remains running.

## Local parser tests

`python -m unittest -v`

No paid hosting, Actions scheduler, or changedetection.io subscription is used. This is a small purpose-built monitor, not a hosted changedetection.io installation.
