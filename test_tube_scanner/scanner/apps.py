from django.apps import AppConfig


class ScannerConfig(AppConfig):
    name = 'scanner'
    
    def ready(self):
        import scanner.models  # noqa — active les signaux post_save/post_delete