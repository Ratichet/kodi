# EpiKodi — Media Center Desktop

EpiKodi est une application media center moderne développée en Python, conçue pour organiser, enrichir et lire votre bibliothèque multimédia locale (films et séries) avec une expérience fluide inspirée de Kodi.

## 1. Technologies et Librairies utilisées

L'application repose sur une stack logicielle robuste pour garantir performance et extensibilité :

* **Interface Graphique (UI) :** **PySide6 (Qt for Python)** pour une interface desktop native, réactive et stylisée via des feuilles de style QSS.
* **Moteur de Lecture :** **python-vlc**, une interface pour **libVLC**, permettant le support de la quasi-totalité des codecs vidéo et audio, ainsi que la gestion matérielle des flux.
* **Base de Données :** **SQLAlchemy** (ORM) avec **SQLite** pour un stockage local performant des métadonnées et du suivi de progression.
* **Analyse de fichiers :** **guessit** pour extraire intelligemment le titre, l'année, la saison et l'épisode à partir des noms de fichiers, même complexes.
* **Métadonnées en ligne :** **TMDb API (The Movie Database)** via la librairie `requests` pour récupérer les synopsis, affiches, notes et castings.
* **Surveillance en temps réel :** **watchdog** pour détecter instantanément l'ajout ou la suppression de fichiers dans les dossiers surveillés.
* **Environnement :** **python-dotenv** pour la gestion sécurisée des clés API et de la configuration.

## 2. Fonctionnement détaillé

### Système d'Indexation (Scanner)

L'application parcourt les dossiers configurés par l'utilisateur. Le processus se déroule en trois étapes :

1. **Scan :** Identification des fichiers vidéos (mkv, mp4, etc.) en ignorant les fichiers trop petits ou les échantillons (samples).
2. **Parsing :** `guessit` analyse le nom du fichier pour séparer le titre des informations techniques (résolution, codec).
3. **Persistence :** Les informations sont enregistrées dans la base de données SQLite locale pour permettre un affichage instantané sans re-scanner le disque.

### Enrichissement des métadonnées

Une fois un média indexé, EpiKodi interroge l'API TMDb :

* Il récupère les informations textuelles (synopsis, note, genre).
* Il télécharge et met en cache les affiches (posters) et les images de fond (backdrops) localement pour une navigation fluide hors-ligne.

### Bibliothèque et Navigation

L'interface est organisée en vues spécialisées gérées par un contrôleur central (`MainWindow`) :

* **Accueil :** Affiche les films en cours de lecture et les derniers ajouts.
* **Films & Séries :** Grilles responsives avec filtres par genre ou année.
* **Vue Détail :** Présentation complète du média avec option de reprise de lecture.

### Lecteur Multimédia Immersif

Le lecteur intégré utilise VLC pour la lecture. Il propose des fonctionnalités avancées :

* **Gestion de la progression :** Sauvegarde automatique de la position pour reprendre la lecture plus tard.
* **Contrôles intelligents :** Masquage automatique du curseur et de l'interface après quelques secondes d'inactivité en plein écran.
* **Support multi-pistes :** Sélection des pistes audio et chargement automatique des sous-titres locaux (`.srt`, `.ass`).

## 3. Installation et Configuration

### Prérequis

* **VLC Media Player** (version 64-bits) doit être installé sur votre système.

### Installation

1. Créer l'environnement virtuel :
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

```


2. Installer les dépendances :
```bash
pip install -r requirements.txt

```



### Configuration

1. Renommez le fichier `.env.example` en `.env`.
2. Ajoutez votre clé API TMDb :
```ini
TMDB_API_KEY=votre_cle_ici
TMDB_LANGUAGE=fr-FR

```



## 4. Structure du Projet

* `core/` : Logique métier, modèles de données et services API.
* `ui/` : Définition de l'interface utilisateur et des vues.
* `ui/widgets/` : Composants réutilisables (grilles, cartes, lecteur).
* `cache/` : Stockage local des affiches et images.