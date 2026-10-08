# Discord YouTube Music Bot

Python Discord music bot with per-guild queues, YouTube search/URL, slash commands and player buttons.

## Requirements

- Python 3.11+
- FFmpeg in PATH
- Node.js 22+ or Deno 2.3+ (for yt-dlp YouTube extraction)
- Discord Bot Token

## Installation

Create an application at https://discord.com/developers/applications and add a Bot. Install it using scopes `bot` and `applications.commands` with permissions Connect, Speak, View Channels, Send Messages and Embed Links. Do not publish your token.

```bash
git clone https://github.com/ynmio55/botdiscord.git
cd botdiscord
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env and add DISCORD_TOKEN
python bot.py
```

On Fedora, install FFmpeg (from your configured repositories) and opus first. On Windows, activate the venv with `.venv\Scripts\activate`.

## Commands

`/play query`: search YouTube or paste YouTube video link.
`/queue`: list queued songs.
`/volume percent`: volume 0–100.
`/leave`: stop and disconnect.

The now playing panel has Pause, Resume, Skip and Stop buttons. Only members in the same voice channel as the bot may control it.

## Notes

Queues are in-memory, lost on restart. YouTube may change access methods; keep yt-dlp up to date. Playing some YouTube sources can fail due to restrictions or changes in YouTube extraction. Only use media you have the rights to play and comply with platform terms.
