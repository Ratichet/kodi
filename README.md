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
- Torrenting

### LA FLEEEEEEEME
- DRM / streaming de plateformes commerciales (Netflix, Prime Video, etc.)
- Synchronisation cloud

## 3. Equipe
- Stagiaire : Quentin Lecourt (chef de projet & dev unique)
- Encadrant : Joffrey Riela
