# Django models for test tube scanner application
# Created on 10/04/2024
# denis@linuxtarn.org
from django.utils.translation import gettext_lazy as _
import uuid
import json
from django_celery_beat.models import PeriodicTask, ClockedSchedule
from django.dispatch import receiver
from django.db.models.signals import post_save, post_delete

from django.utils import timezone
from django.db import models
from django.contrib.auth.models import User


MULTIWELL_POSITION = [
    ('HG', _("HG-Haut gauche")),
    ('HD', _("HD-Haut droit")),
    ('BG', _("BG-Bas gauche")),
    ('BD', _("BD-Bas droit")),
    ('BM', _("BM-Bas milieu")),
    ('HM', _("HM-Haut milieu")),
]

FOURCC_FORMAT = [
    ('mp4v', _("MP4")),
    ('XVID', _("XVID")),
]

VIDEO_TYPE = [
    ('mp4', _("MP4")),
    ('avi', _("AVI")),
]

CAPTURE_TYPE = [
    ('rpi', _("Arducam")),
    ('webcam', _("Webcam")),
    ('file', _("mp4")),
]
    
class Configuration(models.Model):
    name = models.CharField(_("Nom de la Configuration"), help_text=_("Nom de la configuration"), max_length=100, null=True, blank=False, default=_("Configuration par défaut"))
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Auteur", null=True, blank=True)
    # Dashboard configuration
    sidebar_width = models.CharField(_("Barre latérale"), help_text=_("Largeur barre latérale (css)"), max_length=32, null=True, blank=False, default="350px")
    default_grid_columns = models.PositiveSmallIntegerField(_("Colonnes de la grille par défaut"), help_text=_("Nombre de colonnes de la grille par défaut"), blank=False, default=3)
    # opencv
    opencv_fourcc_format = models.CharField(_("Fourcc"), help_text=_('Opencv fourcc format'), max_length=8, choices=FOURCC_FORMAT, null=True, blank=False, default='mp4v')
    opencv_video_type = models.CharField(_("Video type"), help_text=_('Opencv video type'), max_length=8, choices=VIDEO_TYPE, null=True, blank=False, default='mp4')
    # Grbl configuration
    grbl_xmax = models.FloatField(_("Grbl Xmax"), help_text=_("CNC Grbl Xmax en mm"), blank=False, default=350.0)
    grbl_ymax = models.FloatField(_("Grbl Ymax"), help_text=_("CNC Grbl Ymax en mm"), blank=False, default=250.0)
    # camera configuration
    capture_type = models.CharField(_("Capture"), help_text=_("Type de capture"), default='rpi', max_length=8, choices=CAPTURE_TYPE, null=True, blank=False)
    webcam_device_index = models.PositiveSmallIntegerField(_("Index de la webcam"), help_text=_("Index de la webcam (0, 1, ...) si présente"), default=2)
    image_quality = models.PositiveSmallIntegerField(_("Qualité JPEG"), help_text=_("Qualité JPEG (1-100) pour les images exportées"), default=90)
    video_jpeg_quality = models.PositiveSmallIntegerField(_("Qualité JPEG pour les vidéos"), help_text=_("Qualité JPEG (1-100) pour les images extraites des vidéos"), default=90)
    video_frame_rate = models.FloatField(_("Fréquence vidéos (fps)"), help_text=_("Fréquence d'extraction des images des vidéos (images par seconde)"), default=5.0)
    video_width_capture = models.PositiveSmallIntegerField(_("Largeur de capture vidéo"), help_text=_("Largeur de capture vidéo en pixels"), default=1280)
    video_height_capture = models.PositiveSmallIntegerField(_("Hauteur de capture vidéo"), help_text=_("Hauteur de capture vidéo en pixels"), default=720)
    # Calibration
    calibration_crop_radius = models.PositiveSmallIntegerField(_("Rayon de découpe pour la calibration"), help_text=_("Rayon en pixels pour découper les images de calibration en px"), default=150)
    calibration_default_multiwell = models.CharField(_("Multi-puits de calibration par défaut"), help_text=_("Position du multi-puits de calibration par défaut"), max_length=8, choices=MULTIWELL_POSITION, default='HG')
    calibration_default_feed = models.PositiveIntegerField(_("Vitesse de calibration"), help_text=_("Vitesse de déplacement pour la calibration en mm/mn"), default=1000)
    calibration_default_step = models.FloatField(_("Pas de calibration"), help_text=_("Pas de déplacement pour la calibration en mm"), default=1.0)
    calibration_default_duration = models.FloatField(_("Duruée calibration"), help_text=_("Durée de pose entre chaque puits en s"), default=3.0)
    # tracking
    tracking = models.BooleanField(_("Suivi"), help_text=_("Suivi et analyse des planaires"), default=False)
    #
    active = models.BooleanField(_("Actif"), default=False)
    
    
    @classmethod
    def active_config(cls):
        return Configuration.objects.filter(active=True).first()

    class Meta:
        ordering = ['id', ]
        verbose_name = _("Configuration")
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.name}'

class Well(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Auteur", null=True, blank=True)
    name =  models.CharField(_("Nom"), help_text=_("Nom du puit: Ai..Di"), unique=True, max_length=4, null=True, blank=True)

    class Meta:
        ordering = ['name', ]
        verbose_name = _("Puit")
        verbose_name_plural = _("Puits")
        

    def __str__(self):
        return f'{self.name}'


class MultiWell(models.Model):
    label =  models.CharField(_("Label"), help_text=_("Label du multi-puit"), max_length=100, null=True, blank=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Auteur", null=True, blank=True)
    position = models.CharField(_("Position"), help_text=_('Position du multi-puits sur la table'), unique=True, max_length=8, choices=MULTIWELL_POSITION, null=True, blank=False)
    default = models.BooleanField(_("Par défaut"), help_text=_('Multi-puit par défaut'), default=False)
    
    cols = models.PositiveSmallIntegerField(_("Colonnes"), help_text=_('Nombre de colonnes'), blank=False, default=6)
    rows = models.PositiveSmallIntegerField(_("Lignes"), help_text=_('Nombre de lignes'), blank=False, default=4)  
    diameter = models.FloatField(_("Diamètre"), help_text=_('Diamètre des tubes en mm'), blank=False, default=16.0)
      
    row_def = models.CharField(_("Définition"), help_text=_('Définition des lignes'), max_length=16, null=True, blank=False, default="A,B,C,D")
    row_order = models.CharField(_("Ordre ligne"), help_text=_('Ordre ligne de puit. Lecture en serpentin dans le sens des +- X'), max_length=16, null=True, blank=False, default="D,C,B,A")

    order = models.PositiveSmallIntegerField(_("Ordre"), help_text=_('Ordre de lecture du multi-puit'), blank=False, default=0)
    duration = models.PositiveIntegerField(_("Durée"), help_text=_('Durée du film en secondes'), blank=False, default=120)
    xbase = models.FloatField(_("Origine X"), help_text=_('Base origine X en mm'), blank=False, default=50.0)
    ybase = models.FloatField(_("Origine Y"), help_text=_('Base origine Y en mm'), blank=False, default=50.0)

    dx = models.FloatField(_("Pas X"), help_text=_('Pas ou interval sur X en mm'), blank=False, default=19.5)
    dy = models.FloatField(_("Pas Y"), help_text=_('Pas ou interval sur Y en mm'), blank=False, default=19.5)
    feed = models.PositiveIntegerField(_("Vitesse"), help_text=_('Vitesse déplacement en mm/mn '), blank=False, default=1000)
    
    well_position = models.BooleanField(_("Positions"), help_text=_('Positions des puits générées ?. Non => efface WellPosition et recalcule les positions'), default=False)
    active = models.BooleanField(_("Active"), default=True)
    

    def config(self):
        return dict(
            position=self.position,
            cols=self.cols,
            rows=self.rows,
            row_def=self.row_def,
            row_order=self.row_order,
            dx=self.dx,
            dy=self.dy,
            duration=self.duration,
            feed=self.feed,
            xbase=self.xbase,
            ybase=self.ybase,
        )
        return {}

    @classmethod
    def config_by_position(cls, position):
        qs = MultiWell.objects.filter(position__exact=position).values()
        if qs:
            return dict(qs[0])
        return {}

    @classmethod
    def by_position(cls, position):
        return MultiWell.objects.filter(position__exact=position).first()

    @classmethod
    def all(cls):
        return MultiWell.objects.filter(active=True).all()

    class Meta:
        ordering = ['order', ]
        verbose_name = _("Multi-puits")
        verbose_name_plural = _("Multi-puits")


    def __str__(self):
        return f'{self.position}: {self.label}'


class WellPosition(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Auteur", null=True, blank=True)
    well = models.ForeignKey(Well, verbose_name=_("Puit"), on_delete=models.SET_NULL, null=True, blank=True)
    multiwell = models.ForeignKey(MultiWell, verbose_name=_("Multi-puits"), on_delete=models.SET_NULL, null=True, blank=True)
    
    order = models.PositiveSmallIntegerField(_("Ordre"), help_text=_('Ordre de lecture du puit'), blank=False, default=0)
    x = models.FloatField(_("X"), help_text=_('Axe X en mm'), blank=False, default=10.0)
    y = models.FloatField(_("Y"), help_text=_('Axe Y en mm'), blank=False, default=10.0)
    px_per_mm = models.FloatField( default=50.0, verbose_name=_("Pixels par mm"),  help_text=_("Facteur de calibration optique"))


    @classmethod
    def active_well(cls, multiwell, well):
        return WellPosition.objects.filter(multiwell_id=multiwell.id, well_id=well.id).first()    

    class Meta:
        ordering = ['order']
        unique_together = ["multiwell", "well"]
        verbose_name = _("Position d'un puit")
        verbose_name_plural = _("Position des puits")

    def __str__(self):
        return f'{self.multiwell.position}: {self.well.name}'  


@receiver(post_save, sender=MultiWell)
def create_well_position(sender, instance, created, **kwargs):
    if created:
        pass
    if not instance.well_position:
        row_order = instance.row_order.split(',')
        n = 0
        for row in range(instance.rows):
            if row % 2 == 0:
                cols = range(instance.cols)
            else:
                cols = range(instance.cols - 1, -1, -1)
            for col in cols:
                x = instance.xbase + col * instance.dx
                y = instance.ybase + row * instance.dy
                try:
                    name = f'{row_order[row]}{col+1}'
                    well = Well.objects.get(name__exact=name)
                    WellPosition.objects.update_or_create(
                        multiwell=instance, 
                        well=well, 
                        author=instance.author, 
                        defaults={'order': n, 'x': round(x, 4), 'y': round(y, 4)}
                    )
                    n += 1
                except:
                    pass
        instance.well_position=True
        instance.save()
             

class Experiment(models.Model):
    title = models.CharField(_("Titre de l'expérience"), max_length=100, null=True, blank=False)
    comment =  models.TextField(_("Commentaires"), help_text=_("Descriptions de l'expérience"), null=True, blank=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Auteur", null=True, blank=True)
    multiwell = models.ForeignKey(MultiWell, verbose_name=_("Multi-puits"), on_delete=models.SET_NULL, null=True, blank=True)
    created = models.DateTimeField(_("Date de création"), default=timezone.now)
    started = models.DateTimeField (_("Date de début"), null=True, blank=True)
    finished = models.DateTimeField (_("Date de fin"), null=True, blank=True)
    

    class Meta:
        ordering = ['-created', ]
        verbose_name = _("Expérience")
        verbose_name_plural = _("Expériences")

    def __str__(self):
        return f'{self.id}:{self.title}-{self.created}'


class Session(models.Model):
    
    class Status(models.TextChoices):
        PENDING   = "pending",   _("En attente")
        RUNNING   = "running",   _("En cours")
        DONE      = "done",      _("Terminé")
        ERROR     = "error",     _("Erreur")    
    
    name = models.CharField(_("Nom de la session"), help_text=_("Session d'expérience. 4 Multi-puits maximum"), max_length=100, null=True, blank=False)
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Auteur", null=True, blank=True)
    active = models.BooleanField(_("Active"), default=True)
    expected_export  = models.DateTimeField(_("Date d'exportation"), help_text=_("Date d'exportation prévue"), null=True, blank=True)
    expected_scanning  = models.DateTimeField(_("Date du balayage"), help_text=_("Date du balayage prévue"), null=True, blank=True)    
    
    created = models.DateTimeField(_("Date de création"), default=timezone.now)
    finished = models.DateTimeField (_("Date de fin"), null=True, blank=True)
    
    export_status = models.CharField(_("Status exportation"), max_length=16, choices=Status.choices, default=Status.PENDING)
    export_task = models.OneToOneField(
        "django_celery_beat.PeriodicTask", 
        verbose_name=_("Export médias"),
        help_text=_("Programmation de l'exportation des vidéos et images"),
        null=True, blank=True, on_delete=models.SET_NULL, related_name="export_session")
    export_exported_at = models.DateTimeField(_("Exportation terminée à"), null=True, blank=True)
    
    scanning_status = models.CharField(_("Status scanning"), max_length=16, choices=Status.choices, default=Status.PENDING)
    scanning_task = models.OneToOneField(
        "django_celery_beat.PeriodicTask", 
        verbose_name=_("Lancer le balayage"),
        help_text=_("Programmation du lancement du balayage"),
        null=True, blank=True, on_delete=models.SET_NULL, related_name="scanning_session")
    scanning_finished_at = models.DateTimeField(_("Balayage terminé à"), null=True, blank=True)    
    
    
    @classmethod
    def get_session(self, sid):
        return Session.objects.filter(pk=sid).first()   
    
    
    class Meta:
        ordering = ['-created', ]
        verbose_name = _("Session")
        verbose_name_plural = _("Sessions")

    def __str__(self):
        state = _("Terminée") if not self.active else _("Active")
        return f'{self.name}: {state}'
    

@receiver(post_save, sender=Session)
def create_periodic_task(sender, instance, created, **kwargs):
    """
    Crée automatiquement une PeriodicTask à la création d'une session.
    La tâche est one-shot : elle se désactive après exécution (one_off=True).
    """
    if instance.expected_export:
        try:
            clocked, _ = ClockedSchedule.objects.get_or_create(clocked_time=instance.expected_export)
            export_task = PeriodicTask.objects.create(
                name        = f"export_session_{instance.id}",
                task        = "scanner.tasks.run_session_exports",
                clocked     = clocked,
                one_off     = True,          # se désactive après la première exécution
                enabled     = True,
                last_run_at = None,          # force Celery Beat à ne pas la considérer déjà exécutée
                start_time  = None,          # pas de contrainte de démarrage
                kwargs      = json.dumps({   # paramètres passés à la tâche
                    "session_id": str(instance.id),
                }),
                description = f"Export expected at {instance.expected_export} — {instance.name}",
            )
            # Sauvegarde sans re-déclencher le signal
            Session.objects.filter(pk=instance.pk).update(export_task=export_task)
        except:
            pass
        
    if instance.expected_scanning:
        try:
            clocked, _ = ClockedSchedule.objects.get_or_create(clocked_time=instance.expected_scanning)
            scanning_task = PeriodicTask.objects.create(
                name        = f"scanning_session_{instance.id}",
                task        = "scanner.tasks.run_scanning",
                clocked     = clocked,
                one_off     = True,          # se désactive après la première exécution
                enabled     = True,
                last_run_at = None,          # force Celery Beat à ne pas la considérer déjà exécutée
                start_time  = None,          # pas de contrainte de démarrage
                kwargs      = json.dumps({   # paramètres passés à la tâche
                    "session_id": str(instance.id),
                }),
                description = f"Scanning expected at {instance.expected_scanning} — {instance.name}",
            )
            # Sauvegarde sans re-déclencher le signal
            Session.objects.filter(pk=instance.pk).update(scanning_task=scanning_task)
        except:
            pass

@receiver(post_delete, sender=Session)
def delete_periodic_task(sender, instance, **kwargs):
    """
    Supprime la PeriodicTask associée quand la session est supprimée.
    """
    if instance.export_task:
        instance.export_task.delete()
    if instance.scanning_task:
        instance.scanning_task.delete()       
    
    
class SessionExperiment(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Auteur", null=True, blank=True)
    session = models.ForeignKey(Session, verbose_name=_("Session"), on_delete=models.SET_NULL, null=True, blank=True)
    experiment = models.ForeignKey(Experiment, verbose_name=_("Expérience"), on_delete=models.SET_NULL, null=True, blank=True, related_name="session_experiments")

    @classmethod
    def experiment_by_session(cls, session_id, active=True):
        return [ ss.experiment for ss in SessionExperiment.objects.filter(session__id=session_id, session__active=active).order_by('experiment__multiwell__order') ]
    
    @classmethod
    def uuid_from_session(cls, sid):
        experiments = [ss.experiment for ss in SessionExperiment.objects.filter(session__id=sid, session__active=False)]
        uuid_list = []
        for obs in experiments:
            row_def = obs.multiwell.row_def.split(',')
            for row in range(obs.multiwell.rows):
                for col in range(obs.multiwell.cols):
                    uuid = f'{sid}-{obs.multiwell.position}-{row_def[row]}{col+1}'
                    uuid_list.append(uuid)
        return uuid_list

    class Meta:
        ordering = ['session',]
        unique_together = ["session", "experiment"]
        verbose_name = _("Session expérience")
        verbose_name_plural = _("Sessions expériences")

    def __str__(self):
        return f'{self.session.name}'


