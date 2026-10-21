from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from .models import Order

def amount_expression():
    return ExpressionWrapper(F('items__quantity') * F('items__unit_price'),
                             output_field=DecimalField(max_digits=18, decimal_places=2))

def broken_data(user):
    # Equivalent to a serializer property that was changed to inspect related items.
    return [{'id': order.pk, 'total': str(sum(
        (item.quantity * item.unit_price for item in order.items.all()), Decimal('0.00')))}
        for order in Order.objects.filter(user=user).order_by('id')]

def fixed_data(user):
    # LEFT JOIN keeps orders with no items. GROUP BY computes one total per order.
    return [{'id': order.pk, 'total': format(order.total, '.2f')}
        for order in Order.objects.filter(user=user).annotate(
            total=Sum(amount_expression(), default=Decimal('0.00'))).order_by('id')]

@login_required
@require_GET
def broken_summary(request):
    return JsonResponse({'orders': broken_data(request.user)})

@login_required
@require_GET
def summary(request):
    return JsonResponse({'orders': fixed_data(request.user)})
