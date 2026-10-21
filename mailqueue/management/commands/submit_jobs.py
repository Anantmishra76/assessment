from django.core.management.base import BaseCommand, CommandError
from mailqueue.services import create_job
from mailqueue.tasks import dispatch_due

class Command(BaseCommand):
    help = 'Persist fake-provider jobs; first job fails temporarily and second permanently.'
    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=100)
    def handle(self, *args, **options):
        count = options['count']
        if not 1 <= count <= 10000:
            raise CommandError('count must be between 1 and 10000')
        for index in range(count):
            create_job(recipient=f'user{index}@example.com', subject='Assessment', body='Demo',
                scenario='transient_once' if index == 0 else 'permanent' if index == 1 else 'success')
        self.stdout.write(f'Persisted {count} jobs. Beat will publish even if immediate dispatch fails.')
        dispatch_due()
