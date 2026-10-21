import json
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.test import Client
from silk.models import Request

class Command(BaseCommand):
    help = 'Run actual Silk middleware and export query counts, SQL, and timings.'
    def handle(self, *args, **options):
        call_command('seed_orders')
        client = Client()
        client.force_login(get_user_model().objects.get(username='assessment-demo'))
        results = []
        for path in ['/api/orders/summary/broken/', '/api/orders/summary/']:
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError(f'{path}: {response.status_code}')
            capture = Request.objects.filter(path=path).latest('start_time')
            results.append({'path': path, 'status': response.status_code,
                'order_count': len(response.json()['orders']),
                'silk_request_id': str(capture.pk),
                'query_count': capture.queries.count(),
                'time_taken_ms': capture.time_taken,
                'queries': list(capture.queries.values('query', 'time_taken'))})
        target = Path('evidence/silk-profile.json')
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(results, indent=2), encoding='utf-8')
        self.stdout.write(str(target))
