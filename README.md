# EpiKodi — Media Center Desktop

EpiKodi est une application media center moderne développée en Python, conçue pour organiser, enrichir et lire votre bibliothèque de films et de séries avec une expérience fluide inspirée de Kodi.

## 1. Technologies et Librairies utilisées

L'application repose sur une stack logicielle robuste pour garantir performance et extensibilité :

* **Interface Graphique (UI) :** **PySide6 (Qt for Python)** pour une interface desktop native, réactive et stylisée via des feuilles de style QSS.
* **Moteur de Lecture :** **python-vlc**, une interface pour **libVLC**, permettant le support de la quasi-totalité des codecs vidéo et audio, ainsi que la gestion matérielle des flux.
* **Base de Données :** **SQLAlchemy** (ORM) avec **SQLite** pour un stockage local performant des métadonnées et du suivi de progression.
* **Analyse de fichiers :** **guessit** pour extraire intelligemment le titre, l'année, la saison et l'épisode à partir des noms de fichiers, même complexes.
* **Métadonnées en ligne :** **TMDb API (The Movie Database)** via la librairie `requests` pour récupérer les synopsis, affiches, notes et castings.
* **Surveillance en temps réel :** **watchdog** pour détecter instantanément l'ajout ou la suppression de fichiers dans les dossiers surveillés.
* **Configuration :** un fichier local `settings.json` (ignoré par Git) éditable depuis l'écran **Paramètres** de l'application.

## 2. Fonctionnement détaillé

### Système d'Indexation (Scanner)

L'application parcourt les dossiers configurés par l'utilisateur. Le processus se déroule en trois étapes :

1. **Scan :** Identification des fichiers vidéos (mkv, mp4, etc.) en ignorant les fichiers trop petits ou les échantillons (samples).
2. **Parsing :** `guessit` analyse le nom du fichier pour séparer le titre des informations techniques (résolution, codec).
3. **Persistence :** Les informations sont enregistrées dans la base de données SQLite locale pour permettre un affichage instantané sans re-scanner le disque.

### Surveillance en temps réel

En plus du scan manuel, EpiKodi surveille en continu les dossiers configurés
(`watchdog`) et met la bibliothèque à jour sans intervention :

* **Ajout :** un fichier déposé dans un dossier surveillé est indexé, enrichi via
  TMDb, puis apparaît dans les grilles — l'interface se rafraîchit toute seule.
* **Copie en cours :** un fichier n'est traité qu'une fois sa taille stable sur
  deux passes (~2 s). Sans cela, une copie serait examinée dès le premier octet,
  rejetée comme « trop petite », puis jamais réexaminée.
* **Suppression :** retirer un fichier — ou tout un dossier de saison — retire les
  entrées correspondantes de la bibliothèque.
* **Filtrage :** les mêmes règles que le scan complet s'appliquent (taille
  minimale, `sample`, `trailer`…).

La surveillance démarre avec l'application et couvre les dossiers actifs ; ajouter
un dossier dans les **Paramètres** l'intègre immédiatement.

### Téléchargements

L'écran **Téléchargements** met des liens `http(s)` en file d'attente vers un dossier
de la bibliothèque :

* **File séquentielle :** un transfert à la fois, dans un thread annexe ; le débit est
  de toute façon partagé, et une file séquentielle évite d'arbitrer plusieurs écritures
  concurrentes en base.
* **Reprise :** le fichier s'écrit dans un `.part` et le transfert repart de l'octet
  atteint (en-tête HTTP `Range`). Si le serveur ignore la reprise et répond `200` avec
  tout le fichier, le téléchargement recommence proprement plutôt que de dupliquer le
  début.
* **Nommage :** le nom vient de l'URL, ou du `Content-Disposition` du serveur s'il en
  propose un. Une collision devient `Film (2).mkv`, les entrées encore en file comptant
  autant que les fichiers déjà sur le disque.
* **Destination :** par défaut le premier dossier surveillé, si bien qu'un fichier
  terminé est indexé et enrichi sans rien demander. L'écran signale en rouge une
  destination hors surveillance. `download_dir` dans les réglages permet de la changer.
* **Rien à moitié dans la bibliothèque :** l'extension `.part` n'étant pas indexable, la
  surveillance de dossier ignore un téléchargement en cours ; le renommage final est
  atomique.

* **Archives :** un `.zip` ou un `.rar` téléchargé est extrait sur place puis supprimé,
  l'arborescence interne conservée. Un fichier déjà présent n'est pas écrasé. Si
  l'archive est illisible, le fichier téléchargé est conservé tel quel et le motif
  s'affiche sur sa ligne. Le ZIP passe par la bibliothèque standard : une entrée qui
  chercherait à sortir du dossier (`../ailleurs`) est ignorée et l'espace disque est
  vérifié avant de commencer. Le RAR passe par le `tar.exe` (bsdtar) livré avec
  Windows 10 et 11, sans rien à installer : une entrée `../` y fait échouer
  l'extraction et l'archive est gardée. Les RAR en plusieurs volumes (`.part1.rar`…)
  et le 7z ne sont pas pris en charge.
* **Liens d'hébergeur :** certaines adresses désignent une page et non le fichier. Un
  résolveur les échange contre un lien direct auprès de l'API de l'hébergeur, avec les
  identifiants de l'utilisateur, avant chaque tentative — ces liens étant à usage
  unique. 1fichier est pris en charge (clé API, compte payant, à saisir dans
  **Paramètres → Téléchargements**) ; les autres URL passent inchangées.

La source des liens n'est pas du ressort de l'application : c'est l'utilisateur qui les
fournit.

### Enrichissement des métadonnées

Une fois un média indexé, EpiKodi interroge l'API TMDb :

* Il récupère les informations textuelles (synopsis, note, genre) et, pour les séries,
  le titre et le résumé de chaque épisode.
* Il enregistre les têtes d'affiche (les dix premiers noms du générique) dans la
  colonne `actors`, ce qui rend la bibliothèque cherchable par acteur sans appel
  réseau.
* Il télécharge et met en cache localement les affiches, les images de fond et les
  vignettes d'épisode (« stills ») pour une navigation fluide hors-ligne.

L'enrichissement ne repasse que sur les médias sans `tmdb_id`. Un scan complet
enchaîne donc sur une passe de complément qui va chercher ce qui manque encore aux
fiches déjà connues — le casting, le titre d'un épisode — sans les réenrichir
entièrement. Les génériques sont demandés une fois par film et par série, pas une
fois par épisode.

Le nom du fichier ne l'emporte jamais sur une fiche déjà enrichie : `guessit` ne
trouve aucun titre d'épisode dans `South.Park.S15E01.MULTi.1080p.mkv`, et réindexer
écrasait le titre TMDb par ce vide — à chaque scan, sans retour possible.

### Bibliothèque et Navigation

L'interface est organisée en vues spécialisées gérées par un contrôleur central (`MainWindow`) :

* **Accueil :** Affiche les films en cours de lecture et les derniers ajouts.
* **Films :** Grille responsive avec filtres (genre, année, vus) et tri (titre, année,
  note, date d'ajout).
* **Séries :** Navigation à deux niveaux — grille des séries, puis sélecteur de saison
  et grille d'épisodes où **chaque épisode a sa propre vignette TMDb**, son résumé et
  son avancement. Un bouton « Reprendre » pointe directement sur l'épisode en cours.
* **Recherche :** la barre des Films et celle des Séries acceptent un titre **ou un
  nom d'acteur** ; « hanks » ramène les films de la bibliothèque où il est au
  générique. Un acteur se cherche par début de mot, pas par sous-chaîne, sinon
  « an » sortirait tous les films où joue une Susan.
* **Vue Détail :** Présentation complète du média avec option de reprise de lecture.

Les affiches et vignettes sont décodées hors du thread d'interface : ouvrir une grille
de plusieurs centaines de titres ne bloque pas la fenêtre.

### Lecteur Multimédia Immersif

Le lecteur intégré utilise VLC pour la lecture. Il propose des fonctionnalités avancées :

* **Gestion de la progression :** Sauvegarde automatique de la position pour reprendre la lecture plus tard.
* **Support multi-pistes :** Sélection des pistes audio et chargement automatique des sous-titres locaux (`.srt`, `.ass`).
* **Langues préférées :** sur un fichier multilingue, la piste audio et les sous-titres
  correspondant aux langues choisies dans les **Paramètres → Lecture** sont
  sélectionnés à l'ouverture, sans passer par les menus 🔊 et CC à chaque épisode.
  La préférence vaut aussi pour les sous-titres externes : `Film.fr.srt` est chargé
  plutôt que `Film.en.srt` si le français est demandé.
* **Pas de veille pendant un film :** le système ne compte que le clavier et la
  souris comme signes d'activité et éteignait donc l'écran en pleine lecture. Tant
  qu'une vidéo tourne, l'application inhibe la mise en veille de l'écran et de la
  machine (`SetThreadExecutionState` sous Windows, `caffeinate` sous macOS,
  `systemd-inhibit` sous Linux), et rend la main dès la pause, l'arrêt, la fin du
  film ou le départ vers une autre vue.

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

La clé API TMDb se saisit directement dans l'application : **Paramètres → Configuration
TMDB**. Elle est enregistrée dans `settings.json`, à la racine du projet (à côté de
l'exécutable pour une version packagée). Ce fichier n'est jamais versionné.

Pour le préremplir manuellement, copiez `settings.example.json` en `settings.json` :

```json
{
  "tmdb_api_key": "votre_cle_ici",
  "tmdb_language": "fr-FR",
  "audio_language": "",
  "subtitle_language": "",
  "download_dir": ""
}
```

Obtenez une clé sur [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api).

`download_dir` fixe le dossier de destination des téléchargements ; vide, le premier
dossier surveillé est utilisé. `onefichier_api_key` porte la clé API 1fichier, sans
laquelle un lien de ce service ne peut pas être résolu.

`audio_language` et `subtitle_language` portent les langues préférées à la lecture, au
format attendu par VLC — les variantes d'une même langue séparées par des virgules,
par exemple `eng,en,english`. Elles se règlent dans **Paramètres → Lecture** ; vides,
la première piste audio du fichier est gardée et aucun sous-titre intégré n'est activé.

### Lancement

```bash
python main.py
```

### Construire l'application

```bash
pip install pyinstaller
python tools/build.py              # exécutable unique, comme la release
python tools/build.py --onedir     # dossier : démarrage bien plus rapide
python tools/build.py --clean      # repart de zéro
```

Le script produit `dist/EpiKodi.exe` (ou `dist/EpiKodi` en `--onedir`). Sur Windows, il
embarque VLC — depuis `vlc_libs/` s'il est présent, sinon depuis l'installation système —
pour que l'exécutable fonctionne sur une machine qui n'a pas VLC. Sur Linux il s'appuie
sur le paquet système, comme la CI. **C'est le même script qu'appelle le workflow de
release**, afin que les options PyInstaller ne vivent qu'à un seul endroit.

L'icône se régénère seule si elle manque, ou à la demande :

```bash
python tools/make_icon.py --png
```

Elle est entièrement tracée à partir de la charte de `ui/styles.py` (le ⬡ de la barre
latérale, l'accent `#e94560`) et écrite en sept tailles, de 16 à 256 pixels : aucune
image extérieure n'entre dans le paquet.

### Publier une version et mise à jour automatique

1. Monter `APP_VERSION` dans `core/config.py` (ex. `1.2.0`).
2. Commiter, puis pousser un tag identique préfixé de `v` :
   `git tag v1.2.0 && git push origin v1.2.0`.

Le workflow de release refuse un tag qui ne correspond pas à `APP_VERSION`. Pour
Windows, il publie `EpiKodi-v1.2.0-windows.zip` : le dossier `--onedir` zippé.

Au lancement, l'application Windows installée en dossier (`EpiKodi.exe` à côté de
`_internal/`) interroge la dernière release GitHub. Si elle est plus récente, elle
propose de l'installer, la télécharge dans `%LOCALAPPDATA%\EpiKodi\update`, puis se
ferme. Un script PowerShell attend la fin du processus, recopie le nouveau dossier en
miroir (`robocopy /MIR`) et relance l'application. Le journal de la copie reste dans
`update\install.log`. Hors ligne, la vérification est simplement sautée.

Ne se mettent pas à jour seuls : le lancement depuis les sources, l'exécutable unique
(`--onefile`) et Linux. La vérification lit l'API GitHub sans authentification, ce qui
suppose un dépôt public.

### Tests

```bash
python test.py          # ou : pytest test.py -v
```

Les tests s'exécutent sur une base temporaire (`EPIKODI_DB_PATH`) et ne touchent
jamais `epikodi.db`.

## 4. Structure du Projet

* `core/` : Logique métier, modèles de données et services API.
* `ui/` : Définition de l'interface utilisateur et des vues.
* `ui/widgets/` : Composants réutilisables (grilles, cartes, lecteur).
* `cache/`, `epikodi.db`, `settings.json` : affiches, bibliothèque et réglages. Dans le
  dépôt en développement, dans `%LOCALAPPDATA%\EpiKodi` pour l'application installée.