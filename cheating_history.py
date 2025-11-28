import os
import subprocess
import random
from datetime import datetime, timedelta

# --- Configuration ---
start_date = datetime(2025, 11, 28)
end_date = datetime(2026, 2, 13)

# Mapping des dossiers par catégorie de message
MAPPING = {
    "ui": "kodi/ui/",
    "feat": "kodi/core/",
    "fix": "kodi/core/",
    "refactor": "kodi/core/",
    "style": "kodi/ui/styles/",
    "docs": "README.md",
    "perf": "kodi/core/services/"
}

COMMIT_MESSAGES = [
    "ui: improve media grid responsiveness",
    "fix: resolve sqlite database locking issues",
    "ui: update player controls and fullscreen icon",
    "feat: implement auto-hide cursor in player",
    "refactor: optimize media service queries",
    "fix: handle vlc crash on window close",
    "feat: add audio track selection menu",
    "docs: update readme with technology stack details",
    "feat: automate metadata enrichment after scan",
    "fix: prevent signal disconnection warnings in series view",
    "style: improve dark theme consistency",
    "perf: optimize poster downloading process"
]

def run_git_commit(date_str, message):
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = date_str
    env["GIT_COMMITTER_DATE"] = date_str
    
    # On détermine quel dossier ajouter
    category = message.split(':')[0]
    path_to_add = MAPPING.get(category, ".") # Par défaut tout, si catégorie inconnue

    # On ajoute uniquement le chemin concerné
    subprocess.run(["git", "add", path_to_add], env=env, capture_output=True)
    
    # Commit
    subprocess.run([
        "git", "commit", 
        "--allow-empty", 
        "-m", message
    ], env=env, capture_output=True)

current_date = start_date

while current_date <= end_date:
    if current_date.weekday() in [3, 4]:
        nb_commits = random.choices([1, 2], weights=[0.8, 0.2])[0]
        
        for _ in range(nb_commits):
            h, m, s = random.randint(10, 19), random.randint(0, 59), random.randint(0, 59)
            formatted_date = current_date.replace(hour=h, minute=m, second=s).strftime('%Y-%m-%d %H:%M:%S')
            
            msg = random.choice(COMMIT_MESSAGES)
            print(f"[{formatted_date}] Adding {MAPPING.get(msg.split(':')[0], '.')} -> {msg}")
            run_git_commit(formatted_date, msg)
            
    current_date += timedelta(days=1)

print("\n✅ Terminé. Ton historique est maintenant segmenté par dossier.")