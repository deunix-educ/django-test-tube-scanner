#!/bin/bash

# Script d'installation et de configuration d'un client Samba sur Raspberry Pi 4 (Debian Trixie)
# Mise à jour des paquets
echo "[1/5] Mise à jour des paquets..."
sudo apt update && sudo apt upgrade -y

# Installation des paquets nécessaires (client Samba et outils de montage)
echo "[2/5] Installation des paquets nécessaires..."
sudo apt install -y cifs-utils smbclient

# Création du point de montage pour le partage distant
echo "[3/5] Création du point de montage..."
sudo mkdir -p /mnt/samba/public
sudo mkdir -p /mnt/samba/secure

# Demande des informations de connexion au partage Samba
read -p "Adresse IP ou nom d'hôte du serveur Samba (ex: 192.168.1.10) : " samba_server
read -p "Nom du partage public (ex: public) : " public_share
read -p "Nom du partage sécurisé (ex: secure) : " secure_share
read -p "Nom d'utilisateur Samba (laissez vide si partage public uniquement) : " samba_user
if [ -n "$samba_user" ]; then
    read -s -p "Mot de passe de l'utilisateur Samba : " samba_password
    echo
fi

# Configuration des identifiants Samba (pour le partage sécurisé)
if [ -n "$samba_user" ]; then
    echo "[4/5] Configuration des identifiants pour le partage sécurisé..."
    sudo bash -c "echo 'username=$samba_user' > /etc/samba/credentials"
    sudo bash -c "echo 'password=$samba_password' >> /etc/samba/credentials"
    sudo chmod 600 /etc/samba/credentials
fi

# Configuration du montage automatique dans /etc/fstab
echo "[5/5] Configuration du montage automatique dans /etc/fstab..."
# Sauvegarde du fichier fstab existant
sudo cp /etc/fstab /etc/fstab.bak

# Ajout des lignes pour monter les partages Samba
if [ -n "$samba_user" ]; then
    # Montage du partage sécurisé
    sudo bash -c "echo '//$samba_server/$secure_share /mnt/samba/secure cifs credentials=/etc/samba/credentials,uid=1000,gid=1000,file_mode=0770,dir_mode=0770 0 0' >> /etc/fstab"
fi

# Montage du partage public (sans authentification)
sudo bash -c "echo '//$samba_server/$public_share /mnt/samba/public cifs guest,uid=1000,gid=1000,file_mode=0777,dir_mode=0777 0 0' >> /etc/fstab"

# Montage des partages
echo "Montage des partages Samba..."
sudo mount -a

sudo mkdir -p /mnt/samba/public/images /mnt/samba/public/videos

# Vérification du montage
echo "Vérification des partages montés :"
df -h | grep samba

echo "Installation et configuration du client Samba terminées !"
echo "Les partages sont montés dans /mnt/samba/public et /mnt/samba/secure."

