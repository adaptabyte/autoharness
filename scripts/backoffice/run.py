#!/usr/bin/env python3
"""A plain Django admin on 127.0.0.1:8320, with made-up orders: a real, widely used back-office interface, unrelated to medicine.
Autoharness has never seen it. Django writes the whole interface; only the data model is defined here.
  python run.py         seed if needed and serve
GET /_orders.json is for the test's checker only, and no page links to it."""
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
DB = Path.home() / ".autoharness" / "backoffice.sqlite3"
DB.parent.mkdir(exist_ok=True)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "__main__")
SECRET_KEY = "only-for-a-local-test"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1"]
ROOT_URLCONF = "__main__"
USE_TZ = False
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "shop"]
MIDDLEWARE = ["django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware"]
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(DB)}}
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SILENCED_SYSTEM_CHECKS = ["admin.E408"]

import django  # noqa: E402

django.setup()
from django.contrib import admin  # noqa: E402
from django.contrib.staticfiles.urls import staticfiles_urlpatterns  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.http import JsonResponse  # noqa: E402
from django.urls import path  # noqa: E402

from shop.models import Customer, Order  # noqa: E402


def orders(request):
    return JsonResponse({"orders": [{"number": o.number, "customer": o.customer.name, "status": o.status, "total": str(o.total), "tracking": o.tracking, "notes": o.notes} for o in Order.objects.select_related("customer")]})


urlpatterns = [path("admin/", admin.site.urls), path("_orders.json", orders)] + staticfiles_urlpatterns()


def seed():
    from django.contrib.auth.models import User
    if not User.objects.filter(username="manager").exists():
        User.objects.create_superuser("manager", "manager@example.test", "demo-pass")
    if Order.objects.exists():
        return
    rng = random.Random(4242)
    first = "Maren Silas Noor Emeka Priscilla Rafael Astrid Jun Hollis Ines Theo Wren Odalys Bram Zainab Tobias".split()
    last = "Oakhurst Quennell Vandermeer Lindgren Tovar Dunmore Kowalczyk Abernathy Brandvold Marchetto Rasmussen Castellano Halvorsen Nwosu Pemberton Achterberg".split()
    customers = [Customer.objects.create(name=f"{a} {b}", email=f"{a}.{b}@example.test".lower(), city=rng.choice(["Marlow", "Tamarack", "Ridgeway", "Corvid Bay"])) for a, b in zip(first, last)]
    used = set()
    for _ in range(60):
        n = rng.randint(10000, 99999)
        if n in used:
            continue
        used.add(n)
        Order.objects.create(number=f"ORD-{n}", customer=rng.choice(customers), status=rng.choice(["new", "paid", "packed", "shipped", "returned"]), total=f"{rng.randint(12, 900)}.{rng.randint(0, 99):02d}")


if __name__ == "__main__":
    call_command("makemigrations", "shop", verbosity=0)
    call_command("migrate", verbosity=0)
    seed()
    call_command("runserver", "127.0.0.1:8320", "--noreload", verbosity=0)
