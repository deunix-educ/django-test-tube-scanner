
# ![Planaires](assets/logo.png) PlanarianScanner

> Système d'imagerie automatisé pour le suivi comportemental de planaires

> (C) dd@linuxtarn.org pour le Laboratoire de Biologie, Université Champollion, Albi

---

## Présentation

**PlanarianScanner** est une application web développée pour le suivi de l'activité
et des mouvements de **planaires** (*Platyhelminthes*) dans le cadre de leur étude
en laboratoire.

Le système pilote un scanner multi-puits motorisé composé d'un bras CNC (GRBL) et
d'une caméra haute définition ArduCam montée sur Raspberry Pi 4. Il permet
l'acquisition automatisée d'images sur une grille de **6×4 puits × 4 plaques**,
le stockage haute performance des captures, et leur export vers des machines
d'analyse distantes.

---

## Matériel

| Composant | Détail |
|---|---|
| Carte | Raspberry Pi 4 |
| Caméra | ArduCam haute définition |
| Motorisation | Bras CNC (L2544) piloté en GRBL |
| Grille de puits | 6×4 × 4 plaques multi-puits |
| Réseau | LAN local — export Samba/rsync |

---

## Stack technique

| Couche | Technologie |
|---|---|
| Backend | Django + Django Channels |
| Temps réel | Redis (broker + channel layer) |
| Acquisition | OpenCV + Picamera2 |
| Stockage | ReductStore (time series haute performance) |
| Tâches asynchrones | Celery + django-celery-beat |
| Export | Samba (CIFS), rsync/SSH |
| Plateforme | Raspberry Pi 4 — Debian Linux |

---
## Fonctionnalités

- Pilotage du bras CNC en GRBL — déplacement automatique puits par puits
- Calibration des multi-puits avec synchro base de données
- Acquisition image haute définition via ArduCam (OpenCV + Picamera2)
- Stockage des frames en base time série ReductStore
- Sessions de scan paramétrables (grille complète ou sélection de puits)
- Export asynchrone (Celery) :
  - Archive ZIP d'images JPEG par session
  - Vidéo MP4 générée depuis les frames capturées
- Transfert automatique des exports vers machines distantes (Linux / Windows)
- Planification nocturne des exports via django-celery-beat
- Interface web temps réel (Django Channels / WebSocket)
- Interface administration Django (sqlite3 ou mariadb ou postgresql)
- Suivi de progression des tâches longues par polling

Supporte plusieurs planaires avec paramètres configurables via django ou csv.

Export CSV par planaire compatible EthoVision XT.


### Seuils EthoVision par défaut (configurables via django ou csv)

- **Immobile** : déplacement < 0.2 mm/s
- **Mobile** : 0.2 à 1.5 mm/s
- **Très mobile** : > 1.5 mm/s

| EthoVision | CSV frames | CSV summary |
|---|---|---|
| movedCenter-pointTotalmm | total_distance_mm | movedCenter_pointTotal_mm |
| VelocityCenter-pointMeanmm/s | velocity_mm_s | velocity_mean_mm_s |
| MovementMoving | moving, duration_moving_s | movement_moving_duration_s |
| MovementNot Moving | duration_stopped_s | movement_not_moving_duration_s |
| ImmobileFrequency / Duration | mobility_state | mobility_immobile_frequency/duration_s |
| MobileFrequency / Duration | mobility_state | mobility_mobile_frequency/duration_s |
| Highly mobileFrequency / Duration | mobility_state | mobility_highly_mobile_frequency/duration_s |

### Métriques calculées

- Distance totale parcourue (mm) → movedCenter-pointTotalmm
- Vitesse instantanée (mm/s) → VelocityCenter-pointMeanmm/s
- Durée cumulée en mouvement (s) → MovementMoving
- Durée cumulée à l'arrêt (s) → MovementNot Moving
- Fréquence et durée par état de mobilité → Mobility state (EthoVision)
- Distance à la paroi (mm) → thigmotactisme

### Comportements

- **Thigmotactisme** : attraction vers la paroi (--thigmotaxis)
- **Phototactisme** : fuite de la lumière (--photo-mode, --photo-strength)
- **Chimiotactisme** : attraction vers une source de nourriture (--chemo-strength)
- **Inter-individus** : évitement de contact, agrégation, répulsion chimique


---

## Architecture

```
Raspberry Pi 4
├── Django (interface web + API)
│   ├── Django Channels  ←→  Redis  (WebSocket temps réel)
│   └── Celery workers
│       ├── scanning(session_id)       — parcours des puits
│       ├── export_images_zip()        — génération ZIP JPEG
│       ├── export_video_mp4()         — génération MP4 (OpenCV)
│       └── transfer → /mnt/exports   — partage Samba
│
├── ArduCam  ←  Picamera2 / OpenCV    — capture HD
├── CNC GRBL ←  Serial                — déplacement XY
└── ReductStore                        — stockage time série frames
```

---

## Installation

> Documentation complète à venir.

Avec piImager installez PI OS 64-bits Trixie sur le raspberry pi4.<br>
Personnalisez votre raspberry avec au moins ssh (sshkey ou password)<br>
Plus tard, par commodité vous installerez VNC server


```bash
ssh rpi4@ip.du.raspi

git clone https://github.com/votre-repo/planarianscanner.git
git@github.com:deunix-educ/PlanarianScanner.git

# modifier les variables d'environnement si besoin
cp .env.example .env
# Éditer .env : SECRET_KEY, REDIS_URL, REDUCTSTORE_URL, ... 

cd PlanarianScanner/etc
chmod +x *.sh

# installation des librairies systèmes
./1-install-sys.sh

# compilation reductstore 15 mn sur le raspberry pi4
./2-cargo-reductstore-install.sh

# installation samba client
./3-install-samba-client.sh

# installation de mariadb
./4-install_mariadb.sh

# installation de adminer
./5-install_adminer.sh

# Configuration des applications Django
./6-install_django_app.sh

# tester
sudo supervisorctl stop test_tube:*
./manage.py runserver 0.0.0.0:8000

# tester en local
# http://127.0.0.1:8000

# tester en distant
# http://ip.du.raspi:8000

# fin du test
sudo supervisorctl restart test_tube:*

```

Démarrage des services :

```bash
Tous les services sont accessibles depuis supervisor
http://root:toor@ip-du-raspi:9001
ou 
sudo supervisorctl start|stop|restart reductstore
sudo supervisorctl start|stop|restart test_tube:*

Ajouter scanner.local au fichier hosts des clients web:
ip.du.rasp.berry scanner.local

- linux  : /etc/hosts
- windows: C:\Windows\System32\drivers\etc\hosts
- mac    : /private/etc/hosts"

```

## Organisation du dépôt

```bash
PlanarianScanner/
├── assets
│   ├── calibration-auto.jpg
│   ├── calibration-auto.mp4
│   ├── calibration-auto.png
│   └── logo.png
├── browser.py
├── etc
│   ├── 1-install-sys.sh
│   ├── 2-cargo-reductstore-install.sh
│   ├── 3-install-samba-client.sh
│   ├── 4-install_mariadb.sh
│   ├── 5-install_adminer.sh
│   ├── 6-install_django_app.sh
│   ├── db
│   │   ├── configuration.json
│   │   ├── multiwell.json
│   │   └── well.json
│   ├── install-linux-samba-server.sh
│   ├── nginx_service.conf
│   ├── reductstore_service.conf
│   ├── requirements.txt
│   ├── scanner_service.conf
│   └── supervisor-inet_http.conf
├── LICENSE
├── logo.png
├── README.md
└── test_tube_scanner
    ├── home
    │   ├── apps.py
    │   ├── asgi.py
    │   ├── celerymodule.py
    │   ├── context_processors.py
    │   ├── __init__.py
    │   ├── locale
    │   ├── management
    │   ├── middleware.py
    │   ├── __pycache__
    │   ├── settings.py
    │   ├── static
    │   ├── templates
    │   ├── templatetags
    │   ├── urls.py
    │   ├── views.py
    │   └── wsgi.py
    ├── logs
    │   ├── celery.log
    │   └── test_tube.log
    ├── manage.py
    ├── media
    │   ├── images
    │   └── simulation
    ├── modules
    │   ├── capture_interface.py
    │   ├── circular_crop.py
    │   ├── grbl.py
    │   ├── __init__.py
    │   ├── picamera2_capture_basic.py
    │   ├── picamera2_capture.py
    │   ├── planarian_metrics.py
    │   ├── planarian_tracker.py
    │   ├── __pycache__
    │   ├── reductstore.py
    │   ├── system_stats.py
    │   ├── tube_aligner.py
    │   ├── utils.py
    │   ├── videofile_capture.py
    │   └── webcam_capture.py
    ├── planarian
    │   ├── admin.py
    │   ├── apps.py
    │   ├── forms.py
    │   ├── __init__.py
    │   ├── migrations
    │   ├── models.py
    │   ├── __pycache__
    │   ├── templates
    │   ├── tests.py
    │   ├── urls.py
    │   └── views.py
    ├── run-workers.sh
    ├── scanner
    │   ├── admin.py
    │   ├── apps.py
    │   ├── constants.py
    │   ├── consumers.py
    │   ├── export_tasks.py
    │   ├── __init__.py
    │   ├── migrations
    │   ├── models.py
    │   ├── multiwell.py
    │   ├── process.py
    │   ├── __pycache__
    │   ├── routing.py
    │   ├── static
    │   ├── tasks.py
    │   ├── templates
    │   ├── templatetags
    │   ├── tests.py
    │   ├── urls.py
    │   └── views.py
    ├── staticfiles
    │   ├── admin
    │   ├── css
    │   ├── img
    │   ├── js
    │   ├── scanner
    │   └── webfonts
    └── templates
        └── admin

```

---

## Procédure de calibration en 4 étapes
1. Activer "Debug détection" → voir le cercle et les zones sur le stream

Calibration auto

![Aperçu de la vidéo](assets/calibration-auto.png) Calibration auto

![Vidéo Calibration auto 🎬](https://www.linuxtarn.org/media/original_videos/calibration-auto.mp4) Vidéo Calibration auto



## Contexte scientifique

Les **planaires** sont des vers plats dotés de remarquables capacités de
régénération et d'un système nerveux primitif faisant l'objet de nombreuses
recherches en neurobiologie et biologie du développement.

Ce système d'imagerie automatisé permet d'observer et d'enregistrer leur
comportement (déplacements, réponses à des stimuli) sur de longues périodes,
pour un grand nombre d'individus en parallèle, sans intervention humaine.

---

## Laboratoire

Développé par dd@linuxtarn.org pour le **Laboratoire de Biologie de l'Université Champollion**, Albi.

---


## Statut

> Documentation détaillée et guides d'installation complets à venir prochainement.

![status](https://img.shields.io/badge/statut-en%20développement-orange)
![platform](https://img.shields.io/badge/plateforme-Raspberry%20Pi%204-red)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![django](https://img.shields.io/badge/django-4.2%2B-green)
![license](https://img.shields.io/badge/licence-GPL3-lightgrey)

---

## Licence

GPL-3.0 — Projet opensource, développé pour le partage et la reproductibilité scientifique.
