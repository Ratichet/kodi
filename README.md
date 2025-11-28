# Cahier des charges — EpiKodi (simili Kodi)

Projet solo - Quentin Lecourt   
Durée indicative : 8-12 semaines

## 1. Contexte & objectifs
EpiKodi est une application media center inspirée de Kodi, visant à indexer des médias locaux (films, séries, musique), récupérer leurs métadonnées en ligne et offrir une lecture fluide sur desktop. Objectif : livrer un simili Kodi robuste, fonctionnel et extensible.

## 2. Périmètre

### MVP
- Scan de dossiers locaux de médias (configurables)
- Indexation et normalisation des fichiers (films / séries / musique basique)
- Récupération de métadonnées (affiche, synopsis, genres, casting) via TheMovieDB (TMDb) pour la vidéo
- Bibliothèque avec vues : Films, Séries (Saisons/Épisodes), Récemment ajoutés
- Lecteur intégré : lecture, pause, avance/retour rapide, saut par chapitre (si disponible), gestion du volume
- Sous-titres : chargement de fichiers locaux (même nom que la vidéo)
- Recherche et filtres (titre, genre, année, statut « vu »)
- Suivi de progression (reprendre un film/épisode là où il a été arrêté)
- Thème clair / sombre, responsive desktop

### Extensions optionnelles
- Téléchargement de sous-titres via API publique (ex. OpenSubtitles) si conditions d'utilisation acceptées
- Playlists et file d’attente
- Thèmes personnalisables
- Support musique enrichi (tags ID3, pochettes, artistes, albums)
- Casting local (DLNA / Chromecast) selon la stack choisie

### Non livrable
- PVR / TV en direct, torrenting, extensions tierces non contrôlées
- DRM / streaming de plateformes commerciales (Netflix, Prime Video, etc.)
- Synchronisation cloud

## 3. Travailleurs
- Réalisateur : Quentin Lecourt (chef de projet & dev unique)
- Encadrant : Joffrey Riela
- Utilisateurs cibles : utilisateurs desktop gérant une médiathèque locale


## Installation

1. **VLC Media Player** doit être installé sur le système (version 64-bits recommandée).
2. Créer l'environnement :
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # ou .venv\Scripts\activate sur Windows
   pip install -r requirements.txt