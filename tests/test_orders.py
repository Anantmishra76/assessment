from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from orders.models import Order, OrderItem
from orders.views import broken_data, fixed_data


@pytest.mark.django_db
@pytest.mark.parametrize('count', [1, 250])
def test_summary_query_count_and_values(django_assert_num_queries, count):
    user = get_user_model().objects.create_user(username='owner')
    other = get_user_model().objects.create_user(username='other')
    orders = Order.objects.bulk_create([Order(user=user) for _ in range(count)])
    Order.objects.create(user=other)
    OrderItem.objects.bulk_create([
        OrderItem(order=o, quantity=2, unit_price=Decimal('12.50')) for o in orders])
    with django_assert_num_queries(count + 1):
        before = broken_data(user)
    with django_assert_num_queries(1):
        after = fixed_data(user)
    assert before == after
    assert all(row['total'] == '25.00' for row in after)


@pytest.mark.django_db
def test_empty_order_and_authentication(client):
    user = get_user_model().objects.create_user(username='owner')
    order = Order.objects.create(user=user)
    assert fixed_data(user) == [{'id': order.pk, 'total': '0.00'}]
    assert client.get('/api/orders/summary/').status_code == 302
    client.force_login(user)
    assert client.get('/api/orders/summary/').json()['orders'][0]['total'] == '0.00'
    assert client.post('/api/orders/summary/').status_code == 405
