# EpiKodi — User Manual

> Personal media center · Movies · TV Shows · Music · Playlists

---

## Installation

```bash
pip install -r requirements.txt
python main.py
```

For posters and synopses, create a `.env` file:
```
TMDB_API_KEY=your_api_key
```
(For obtain your api key go on https://www.themoviedb.org/settings/api)

---

## Navigation

| Tab | Content |
|---|---|
| 🏠 Home | Recently added, currently watching |
| 🎬 Movies | Movie library |
| 📺 Series | TV shows by season and episode |
| 🎵 Music | All your tracks |
| 📋 Playlists | Mixed audio/video playlists |
| ⚙ Settings | Watched folders |

---

## Library

Go to **⚙ Settings** → **Add a folder**. EpiKodi scans recursively and indexes automatically. Files dropped into a watched folder are detected in real time.

Supported formats:
- **Video**: `.mkv` `.mp4` `.avi` `.mov` `.wmv` `.m4v`
- **Audio**: `.mp3` `.flac` `.ogg` `.m4a` `.wav` `.aac`

> Video files < 50 MB and audio files < 100 KB are ignored (samples, jingles).

---

## Video Player

| Key | Action |
|---|---|
| `Space` | Play / Pause |
| `← →` | –10s / +10s |
| `↑ ↓` | Volume |
| `F` or double-click | Fullscreen |
| `Esc` | Exit fullscreen |

Subtitle files (`.srt` / `.ass`) placed in the same folder as the video are detected automatically.

---

## Music

Click a track to play it. The queue follows the current display order of the table — if you sort by artist, playback follows that order.

The **audio bar** at the bottom stays visible regardless of the active tab. Starting a track from any tab does not change the current view.

| Button | Action |
|---|---|
| ⏮ ▶⏸ ⏭ | Previous / Play-Pause / Next |
| ⇄ | Shuffle |
| ↻ | Repeat (off → track → all) |

---

## Playlists

Playlists can mix movies, episodes and tracks.

1. **Create** → `+ New playlist` in the left panel
2. **Add** → `+ Add media…` then search and select
3. **Play all** → ▶ button at the top of the right panel

Playback chains all items automatically. Consecutive tracks are grouped in the audio player; videos open in the video player.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Files missing from library | Check the folder in Settings, trigger a manual scan |
| No poster / synopsis | Check `TMDB_API_KEY` in `.env` |
| No sound | Make sure VLC is installed on your system |
| Audio bar disappeared | Expected — it hides during video playback and comes back after |