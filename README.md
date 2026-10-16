# MiniTube — local video-sharing starter

MiniTube is a Flask + SQLite starter project with a responsive dark interface.

## Included features
- Account registration and sign-in (passwords are hashed)
- Upload and stream MP4, WEBM, OGG, MOV, and M4V files
- Search by title, description, or creator
- Filter videos by category
- Video watch page and related-video list
- Likes, comments, creator channels, and subscriptions
- Creator's video management and deletion
- SQLite database and Docker Compose volume for persistent data

## Run with Docker Desktop (Windows)
1. Install and open Docker Desktop. Wait until the Docker engine is running.
2. Open Command Prompt in the folder containing `compose.yaml`.
3. Build and start MiniTube:
   ```bat
   docker compose up --build
   ```
4. Open http://localhost:5000
5. Stop the site with `Ctrl+C`. To run it in the background instead:
   ```bat
   docker compose up --build -d
   ```
   Stop background mode with:
   ```bat
   docker compose down
   ```

Uploaded videos and the database are stored in the Docker volume `minitube_data`, so they survive container recreation.

## Run directly (optional)
```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```
Then open http://127.0.0.1:5000.

## Important limitations before public launch
This is a learning MVP, not yet production-ready. Before publishing publicly, add CSRF protection, rate limits, moderation/reporting, content scanning, stricter upload validation, HTTPS, secure production secrets, backups, and a scalable video-storage/streaming solution. Large files consume disk space. It does not yet include video transcoding, thumbnail generation, playlists, recommendations, ads, or mobile apps. Only upload videos you own or are authorized to share.
