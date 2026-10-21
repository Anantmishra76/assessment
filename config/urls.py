from django.conf import settings
from django.urls import include, path
from orders import views
urlpatterns = [
    path('api/orders/summary/', views.summary, name='summary'),
    path('api/orders/summary/broken/', views.broken_summary, name='broken-summary'),
]
if settings.DEBUG:
    urlpatterns += [path('silk/', include('silk.urls', namespace='silk'))]
