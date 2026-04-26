#!/bin/bash

ETC="$(pwd)"

# Script d'installation d'Adminer avec Nginx (sans Apache) + détection automatique de PHP
# Mise à jour des paquets
echo "[1/6] Mise à jour des paquets..."
sudo apt update && sudo apt upgrade -y

# Installation de Nginx et PHP-FPM (avec détection de la version de PHP)
echo "[2/6] Installation de Nginx et PHP-FPM..."
sudo apt install -y nginx

# Détection de la version de PHP installée (ou installation si absente)
VERSION=$(apt-cache policy php | awk '/Candidate:/ {print $2}')
PHP_VERSION=$(apt-cache show php | awk -F'[: ]+' '/Depends:/ {for(i=1;i<=NF;i++) if($i ~ /^php[0-9]+\.[0-9]+$/) print substr($i,4)}' | head -n1)
echo "Version du paquet php (meta): $version"
echo "Version PHP utilisée: $php_version"

if [ -z "$PHP_VERSION" ]; then
    echo "Aucune version de PHP détectée. Installation de PHP 8.2 par défaut..."
    sudo apt install -y php8.2 php8.2-fpm php8.2-mysql
    PHP_VERSION="8.2"
else
    echo "Version de PHP détectée : $PHP_VERSION"
    sudo apt install -y "php$PHP_VERSION" "php$PHP_VERSION-fpm" "php$PHP_VERSION-mysql"
fi

# Téléchargement de la dernière version stable d'Adminer
echo "[3/6] Téléchargement de la dernière version d'Adminer..."
ADMINER_VERSION=$(curl -s https://api.github.com/repos/vrana/adminer/releases/latest | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')
sudo mkdir -p /var/www/adminer
sudo wget "https://github.com/vrana/adminer/releases/download/v$ADMINER_VERSION/adminer-$ADMINER_VERSION.php" -O /var/www/adminer/index.php


# Configuration de Nginx pour Adminer
echo "[4/6] Configuration de Nginx..."
sudo usermod -aG www-data rpi4
sudo ln -s $ETC/nginx_service.conf /etc/nginx/sites-enabled/

sudo chown -R www-data:www-data /var/www/adminer/
sudo chmod -R 755 /var/www/adminer/

# Activation du site Nginx
sudo nginx -t  # Teste la configuration Nginx

# Redémarrage des services
echo "[5/6] Redémarrage de Nginx et PHP-FPM..."
sudo systemctl restart nginx "php${PHP_VERSION}-fpm"
sudo systemctl enable nginx "php${PHP_VERSION}-fpm"

# Ajout de l'entrée dans /etc/hosts (optionnel)
echo "[6/6] Ajout de 'scanner.local' dans /etc/hosts..."
echo "$(hostname -I | awk '{print $1}') scanner.local" | sudo tee -a /etc/hosts

# Affichage des informations
echo ""
echo "=== Installation terminée ==="
echo "Adminer est accessible à l'adresse : http://scanner.local:81"
echo "ou via l'IP locale : http://$(hostname -I | awk '{print $1}'):81"
echo "Version d'Adminer installée : $ADMINER_VERSION"
echo "Version de PHP utilisée : $PHP_VERSION"
echo "Ajouter 'scanner.local' au fichier hosts:"
echo "    linux  : /etc/hosts"
echo "    windows: C:\Windows\System32\drivers\etc\hosts"
echo "    mac: /private/etc/hosts"
echo ""
echo "Pour accéder à Adminer depuis cette machine:"
echo "  http://scanner.local:81"
echo "ou"
echo "  http://$(hostname -I | awk '{print $1}')"
