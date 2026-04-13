#
# encoding: utf-8
#import re
#from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.core.management import BaseCommand
from django_celery_beat.models import IntervalSchedule, CrontabSchedule, SolarSchedule
from django.contrib.auth import get_user_model
from scanner.models import Well

def create_Well():
    try:
        if Well.objects.count() == 0:
            for name in [
                'A1', 'A2', 'A3', 'A4', 'A5', 'A6',
                'B1', 'B2', 'B3', 'B4', 'B5', 'B6',
                'C1', 'C2', 'C3', 'C4', 'C5', 'C6',
                'D1', 'D2', 'D3', 'D4', 'D5', 'D6',
                ]:
                Well.objects.create(name=name, user_id=1)
            print('Creating Well')
    except Exception as e:
        print(f'Creating well error {e}')


def create_user():
    try:
        User = get_user_model()
        if User.objects.count() == 0:
            for email, username, password, is_superuser in settings.ADMINS:
                if is_superuser:
                    User.objects.create_superuser(
                        email=email,
                        username=username,
                        password=password,
                        is_active=True,
                        is_superuser=is_superuser,
                    )
                else:
                    User.objects.create_user(
                        email=email,
                        username=username,
                        password=password,
                        is_active=True,
                    )
                print(f'Creating {username} user with {password} password and email: {email} superuser: {is_superuser}')
    except Exception as e:
        print(f'Creating user error {e}')

def create_schedule():
    try:
        for n in [1, 2, 5, 10, 15, 20, 30, 40, 45, 50]:
            IntervalSchedule.objects.create(every=n, period='minutes')
        print('Creating IntervalSchedule minutes')

        for n in [1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]:
            IntervalSchedule.objects.create(every=n, period='hours')
        print('Creating IntervalSchedule hours')

        for n in [1, 2, 3, 7, 15, 30, 60, 90, 180, 360]:
            IntervalSchedule.objects.create(every=n, period='days')
        print('Creating IntervalSchedule days')

        CrontabSchedule.objects.create(minute='0', hour='4', day_of_week='*', timezone=settings.TIME_ZONE)
        CrontabSchedule.objects.create(minute='0', hour='4', day_of_week='*/3', timezone=settings.TIME_ZONE)
        CrontabSchedule.objects.create(minute='15', hour='4', day_of_week='*/3', timezone=settings.TIME_ZONE)
        CrontabSchedule.objects.create(minute='30', hour='4', day_of_week='*/3', timezone=settings.TIME_ZONE)
        CrontabSchedule.objects.create(minute='0', hour='18', day_of_week='*', timezone=settings.TIME_ZONE)
        CrontabSchedule.objects.create(minute='15', hour='18', day_of_week='*/3', timezone=settings.TIME_ZONE)
        CrontabSchedule.objects.create(minute='30', hour='18', day_of_week='*/3', timezone=settings.TIME_ZONE)
        print('Creating CrontabSchedule')

        SolarSchedule.objects.create(event='sunset', latitude=43.8, longitude=2.3)
        SolarSchedule.objects.create(event='sunrise', latitude=43.8, longitude=2.3)
        print('Creating SolarSchedule')

    except Exception as e:
        print(f'Creating schedule error {e}')


class Command(BaseCommand):

    def handle(self, *args, **options):
        try:
            create_user()
            create_schedule()
            create_Well()

        except Exception as e:
            print(f'Creating monitor error {e}')
