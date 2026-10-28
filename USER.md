# EpiKodi — User Manual

> Personal media center · Movies · TV Shows

---

## Installation

```bash
pip install -r requirements.txt
python main.py
```

For posters and synopses, open **⚙ Settings → TMDB configuration** and paste your API
key. It is stored in `settings.json` next to the application.
(To obtain an API key go to https://www.themoviedb.org/settings/api)

---

## Navigation

| Tab | Content |
|---|---|
| 🏠 Home | Recently added, currently watching |
| 🎬 Movies | Movie library, with filters and sorting |
| 📺 Series | TV shows, browsed season by season |
| ⬇ Downloads | Download queue, with progress and resume |
| ⚙ Settings | Watched folders, TMDB, playback, statistics |

---

## Library

Go to **⚙ Settings** → **Add a folder**. EpiKodi scans recursively and indexes
automatically. Files dropped into a watched folder are detected in real time: they
are indexed, enriched from TMDb and appear without any manual refresh.

Supported formats: `.mkv` `.mp4` `.avi` `.mov` `.wmv` `.m4v` `.mpg` `.ts` …

> Video files under 50 MB are ignored, as are files named `sample`, `trailer`,
> `featurette`, `extra` or `scene`.

---

## Downloads

Paste an `http(s)` link into **⬇ Downloads** and press Enter. Links are queued and
transferred one at a time, with progress, and the destination is shown right under the
field — by default the first watched folder, so a finished file joins the library on its
own. If the destination is not watched, the screen says so in red.

* **Mettre en pause** stops the running transfer and empties the waiting list. `↻` on a
  paused or failed entry puts it back in the queue: it resumes from the byte it reached,
  not from zero.
* `✕` removes an entry and its partial file.
* Files being downloaded are named `*.part` and are invisible to the library until they
  are complete, so downloading straight into a watched folder is safe.

**ZIP and RAR archives** are unpacked where they land and the archive is then deleted,
keeping any folder structure inside. Files already present are kept, not overwritten. If
the archive turns out to be unreadable the download itself is kept and the reason is
shown on its line. RAR uses the `tar` tool built into Windows 10 and 11, nothing to
install. Multi-part RAR (`.part1.rar`, `.part2.rar`…) and 7z are not handled.

**1fichier links** point at a page, not at the file, so they need an API key (paid
account) entered once in **⚙ Settings → Téléchargements**. EpiKodi then exchanges the
link for a direct one before each attempt. Whatever 1fichier answers on refusal — bad
key, no subscription, deleted file — is shown as is on the download line.

Where the links come from is up to you — the app does not search anything.

---

## Movies

Filter by genre, year or watched status, and sort by title, release year, rating or
date added. A progress bar under a poster means the film was started; a green check
means it was finished.

The search field takes a **title or an actor**: typing `hanks` brings up every film in
your library where Tom Hanks is credited. A name is matched from the start of a word,
so `hanks` and `tom h` both work while `anks` finds nothing — otherwise `an` would list
every film with a Susan in it. The searchable cast is the ten top-billed actors TMDb
gives for the title, and the other filters still apply on top of the search.

Click a poster to open its detail page, double-click to play it right away.

**🗑 Delete** on the detail page erases the video file from the disk, along with its
subtitle files, after a confirmation. It cannot be undone: the file does not go to the
Recycle Bin.

---

## Series

**Level 1 — all series.** One card per show with its poster, its season and episode
counts, an overall progress bar and a badge counting the episodes left to watch. The
search field takes a show name **or an actor**, matched the same way as on the Movies
screen.

**Level 2 — one series.** Click a card to open it:

* a header with the show backdrop, poster, year, rating, genres and synopsis;
* **▶ Resume S01E04** — jumps to the episode you started, or the first unwatched one;
* one button per season, each showing its own `watched / total` count;
* an episode grid where every episode has **its own TMDb still image**, its number,
  title, runtime, summary and progress bar.

Clicking an episode plays it. Right-click for the rest: mark as watched or unwatched,
or open the episode's detail page. Searching inside a series looks across every
season, not just the one on screen.

When an episode finishes, the next one in the series starts automatically.

**🗑 Delete the series** erases every episode file of the show, and their subtitles,
from the disk after a confirmation. To delete a single episode, open its detail page
and use **🗑 Delete** there. Neither can be undone.

---

## Video Player

| Key | Action |
|---|---|
| `Space` | Play / Pause |
| `←` / `→` | –10s / +10s |
| `N` / `P` | Next / previous episode (series only) |
| `F` or double-click | Fullscreen |
| `Esc` | Exit fullscreen |

Control bar: `⏹` closes the player, `⏮ Ép.` / `Ép. ⏭` jump between episodes,
`⏮ 10s` / `10s ⏭` seek, `CC` picks subtitles and `🔊` picks the audio track.

On a multilingual file, EpiKodi selects the audio track and the subtitles matching the
languages set in **⚙ Settings → Playback**, whenever the file offers them — no more
picking the same tracks at every episode. Without a preference the first audio track of
the file is kept and no embedded subtitle is turned on; `🔊` and `CC` still switch
tracks by hand at any time.

Subtitle files (`.srt` `.ass` `.sub` `.ssa` `.vtt`) placed next to the video —
including `movie.fr.srt` and `movie.eng.srt` style names — are detected automatically.
The one matching your preferred subtitle language is the one loaded; an external file
always wins over an embedded track.

### Moving between episodes

While watching a series, `⏮ Ép.` and `Ép. ⏭` (or the `P` / `N` keys) move to the
neighbouring episode without leaving the player. The order follows season then
episode number, so passing the last episode of a season continues into the next one.
Each button greys out at the ends of the series, and the buttons are hidden entirely
for a film.

Your position in the episode you are leaving is saved before the switch, so you can
come back to it later.

Playback position is saved every 10 seconds; a title is marked as watched past 90 %.

### Leaving the player and coming back

Clicking **Home**, **Movies** or **Series** while something is playing **pauses** it
and keeps it loaded. A red **▶ Resume — <title>** button then appears at the bottom of
the left sidebar: click it to go straight back to the player and carry on where you
stopped. Browse as much as you like in between.

The ⏹ button inside the player closes it for good — the resume button disappears and
the position is saved, so the title still shows up under *Continue watching*.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Files missing from library | Check the folder in Settings, then run **🔄 Update everything** |
| No poster / synopsis | Check the TMDB API key in Settings |
| Episode images missing | Run **🔄 Update everything**: stills are downloaded with the metadata |
| Searching an actor finds nothing | Titles indexed before this version have no cast yet: run **🔄 Update everything** once |
| Episodes show the series name instead of their own title | The title was lost by an older scan: run **🔄 Update everything** once, it is fetched again |
| No sound | Make sure VLC is installed on your system |
| Wrong audio language | **⚙ Settings → Playback → Audio**, then play the title again |
| Wrong subtitles, or none | **⚙ Settings → Playback → Subtitles**, then play the title again |
| A new file did not show up | Copies are only indexed once finished; give it a few seconds |
| Download not in the library | The destination must be a watched folder — the Downloads screen warns when it is not |
