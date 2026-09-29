"""Management command to deliver pending webhooks (S12).

Usage:
    python manage.py deliver_webhooks --once
    python manage.py deliver_webhooks --loop
"""

import time
from django.core.management.base import BaseCommand
from samepage.services import webhooks


class Command(BaseCommand):
    help = "Deliver pending webhooks from the outbox"

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run continuously in a worker loop",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            default=True,
            help="Run one delivery pass and exit (default)",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Sleep interval between loop iterations (seconds)",
        )

    def handle(self, *args, **options):
        is_loop = options.get("loop", False)
        interval = options.get("interval", 1.0)

        if not is_loop:
            count = webhooks.deliver_pending()
            self.stdout.write(f"Delivered {count} webhook(s).")
            return

        self.stdout.write("Starting webhooks worker loop (Ctrl+C to stop)...")
        try:
            while True:
                delivered = webhooks.deliver_pending()
                if delivered > 0:
                    self.stdout.write(f"Delivered {delivered} webhook(s).")
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Webhooks worker stopped.")
