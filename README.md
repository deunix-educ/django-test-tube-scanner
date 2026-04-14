
# ![Planaires](./logo.png) PlanarianScanner

> Système d'imagerie automatisé pour le suivi comportemental de planaires —
> Laboratoire de Biologie, Université Champollion, Albi

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
- calibration des multi-puits avec synchro base de données
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

cd PlanarianScanner/etc
chmod +x *.sh

# compilation reductstore 15 mn sur le raspberry pi4
./cargo-reductstore-install.sh

# installation des librairies systèmes
./install-sys.sh

> samba configuration  à venir.

# Configuration des applications Django
cd ../test-tube-scanner

cp .env.example .env
# Éditer .env : SECRET_KEY, REDIS_URL, REDUCTSTORE_URL, ... 

./manage.py migrate
Si besoin:
./manage.py makemigrations
./manage.py migrate

# créer superadmin et tables 
./manage.py init_data
./manage.py loaddata ../etc/scanner_configuration.json
./manage.py loaddata ../etc/well.json
./manage.py loaddata ../etc/multiwell.json

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

```

---

## Organisation du dépôt

```
PlanarianScanner/
├── cameras/                  # App principale
│   ├── models.py             # ExportSession, ScanningStatus
│   ├── tasks/
│   │   ├── export_tasks.py   # export_images_zip, export_video_mp4
│   │   ├── scanning_tasks.py # scanning, on_scanning_done
│   │   └── transfer_tasks.py # copy vers Samba
│   ├── consumers.py          # WebSocket Channels
│   └── views.py
├── cnc/                      # Pilotage GRBL
├── logs/                     # Logs Celery (rotation auto)
├── media/exports/            # Fichiers exportés temporaires
└── requirements.txt
```

---

## Contexte scientifique

Les **planaires** sont des vers plats dotés de remarquables capacités de
régénération et d'un système nerveux primitif faisant l'objet de nombreuses
recherches en neurobiologie et biologie du développement.

Ce système d'imagerie automatisé permet d'observer et d'enregistrer leur
comportement (déplacements, réponses à des stimuli) sur de longues périodes,
pour un grand nombre d'individus en parallèle, sans intervention humaine.

---

## Laboratoire

Développé pour le **Laboratoire de Biologie de l'Université Champollion**, Albi.

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
