from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from orders.models import Order, OrderItem

class Command(BaseCommand):
    help = 'Create a repeatable 250-order profiler fixture; no login password is set.'
    @transaction.atomic
    def handle(self, *args, **options):
        user, _ = get_user_model().objects.get_or_create(username='assessment-demo')
        Order.objects.filter(user=user).delete()
        orders = Order.objects.bulk_create([Order(user=user) for _ in range(250)])
        OrderItem.objects.bulk_create([OrderItem(order=o, quantity=2,
            unit_price=Decimal('12.50')) for o in orders for _ in range(3)])
        self.stdout.write('Seeded 250 orders with 750 items for assessment-demo')
