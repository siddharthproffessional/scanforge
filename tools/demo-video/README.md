# Demo video

1. Run the API: `cd backend && SCANFORGE_DATA=/tmp/sfdata uvicorn scanforge.api:app --port 8765`
2. `pip install playwright`, then `python record_app.py` (frames to /tmp/vid/app) and `python cards.py` (title/end cards)
3. Encode each scene with ffmpeg and join them with the concat demuxer (`-c copy`).
