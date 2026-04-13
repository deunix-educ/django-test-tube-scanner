#
# encoding: utf-8
from django.core.management import BaseCommand
from django.urls import get_resolver

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        
        def show_urls(urllist, depth=0):
            for entry in urllist:
                print(entry.pattern)
                if hasattr(entry, 'url_patterns'):
                    show_urls(entry.url_patterns, depth + 1)

        show_urls(get_resolver().url_patterns)
        
   
        


