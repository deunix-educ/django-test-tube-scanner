#
# encoding: utf-8
from uuid import uuid4
from django.core.management import BaseCommand
from django.core.management.utils import get_random_string;

class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("--app", type=str, default='django', help=f"Default application django/reductstore")
        parser.add_argument("--head", type=str, default='scanner', help=f"Default application django/reductstore")

    def handle(self, *args, **options):
        if options.get('app')=='django':
            chars =  "abcdefghijklmnopqrstuvwxyz0123456789!@#€%^&*(-_=+)"

            sk = get_random_string(50, chars)
            print(f'django-insecure-{sk}')

        elif options.get('app')=='reductstore':
            head = options.get('head')
            print(f'{head}-{uuid4()}')

