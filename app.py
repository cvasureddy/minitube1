import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MINITUBE_DATA", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "minitube.db"
ALLOWED_EXTENSIONS = {"mp4", "webm", "ogg", "mov", "m4v"}
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-development-key")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            filename TEXT NOT NULL,
            category TEXT DEFAULT 'Other',
            views INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS likes (
            user_id INTEGER NOT NULL,
            video_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id, video_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            video_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            subscriber_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(subscriber_id, creator_id),
            CHECK(subscriber_id != creator_id),
            FOREIGN KEY(subscriber_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(creator_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)
        db.commit()


@app.before_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        with connect_db() as db:
            g.user = db.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash("Please sign in to do that.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sql = """
        SELECT v.*, u.username,
        (SELECT COUNT(*) FROM likes l WHERE l.video_id = v.id) AS like_count
        FROM videos v JOIN users u ON u.id = v.user_id
        WHERE 1=1
    """
    params = []
    if query:
        sql += " AND (v.title LIKE ? OR v.description LIKE ? OR u.username LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like, like])
    if category and category != "All":
        sql += " AND v.category = ?"
        params.append(category)
    sql += " ORDER BY v.created_at DESC"
    with connect_db() as db:
        videos = db.execute(sql, params).fetchall()
    categories = ["All", "Education", "Gaming", "Music", "Technology", "Entertainment", "Lifestyle", "Other"]
    return render_template("index.html", videos=videos, query=query, category=category or "All", categories=categories)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(username) > 30:
            flash("Username must be 3–30 characters.", "error")
        elif not username.replace("_", "").isalnum():
            flash("Use only letters, numbers, and underscores in your username.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        else:
            try:
                with connect_db() as db:
                    cur = db.execute(
                        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                        (username, generate_password_hash(password), datetime.utcnow().isoformat())
                    )
                    db.commit()
                    session.clear()
                    session["user_id"] = cur.lastrowid
                flash("Welcome to MiniTube! Your account is ready.", "success")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "error")
    return render_template("auth.html", mode="signup")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with connect_db() as db:
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("You're signed in.", "success")
            next_url = request.args.get("next", "")
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("index"))
        flash("Incorrect username or password.", "error")
    return render_template("auth.html", mode="login")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have signed out.", "info")
    return redirect(url_for("index"))


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "Other")
        video = request.files.get("video")
        if not title or len(title) > 120:
            flash("Enter a title of up to 120 characters.", "error")
        elif not video or not video.filename:
            flash("Choose a video file first.", "error")
        elif not allowed_file(video.filename):
            flash("Supported formats: MP4, WEBM, OGG, MOV, and M4V.", "error")
        else:
            original = secure_filename(video.filename)
            extension = original.rsplit(".", 1)[1].lower()
            filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.{extension}"
            video.save(UPLOAD_DIR / filename)
            with connect_db() as db:
                db.execute(
                    "INSERT INTO videos (user_id, title, description, filename, category, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (g.user["id"], title, description, filename, category, datetime.utcnow().isoformat())
                )
                db.commit()
            flash("Your video is uploaded!", "success")
            return redirect(url_for("index"))
    categories = ["Education", "Gaming", "Music", "Technology", "Entertainment", "Lifestyle", "Other"]
    return render_template("upload.html", categories=categories)


@app.route("/video/<int:video_id>")
def watch(video_id):
    with connect_db() as db:
        video = db.execute("""
            SELECT v.*, u.username,
            (SELECT COUNT(*) FROM likes l WHERE l.video_id = v.id) AS like_count,
            (SELECT COUNT(*) FROM comments c WHERE c.video_id = v.id) AS comment_count,
            (SELECT COUNT(*) FROM subscriptions s WHERE s.creator_id = v.user_id) AS subscriber_count
            FROM videos v JOIN users u ON u.id = v.user_id WHERE v.id = ?
        """, (video_id,)).fetchone()
        if not video:
            abort(404)
        db.execute("UPDATE videos SET views = views + 1 WHERE id = ?", (video_id,))
        liked = False
        subscribed = False
        if g.user:
            liked = bool(db.execute("SELECT 1 FROM likes WHERE user_id = ? AND video_id = ?", (g.user["id"], video_id)).fetchone())
            subscribed = bool(db.execute("SELECT 1 FROM subscriptions WHERE subscriber_id = ? AND creator_id = ?", (g.user["id"], video["user_id"])).fetchone())
        comments = db.execute("""
            SELECT c.*, u.username FROM comments c JOIN users u ON u.id = c.user_id
            WHERE c.video_id = ? ORDER BY c.created_at DESC
        """, (video_id,)).fetchall()
        related = db.execute("""
            SELECT v.*, u.username FROM videos v JOIN users u ON u.id = v.user_id
            WHERE v.id != ? ORDER BY v.created_at DESC LIMIT 4
        """, (video_id,)).fetchall()
    return render_template("watch.html", video=video, liked=liked, subscribed=subscribed, comments=comments, related=related)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    safe = secure_filename(filename)
    if safe != filename:
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False, conditional=True)


@app.route("/video/<int:video_id>/like", methods=["POST"])
@login_required
def toggle_like(video_id):
    with connect_db() as db:
        exists = db.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone()
        if not exists:
            abort(404)
        like = db.execute("SELECT 1 FROM likes WHERE user_id = ? AND video_id = ?", (g.user["id"], video_id)).fetchone()
        if like:
            db.execute("DELETE FROM likes WHERE user_id = ? AND video_id = ?", (g.user["id"], video_id))
        else:
            db.execute("INSERT INTO likes (user_id, video_id, created_at) VALUES (?, ?, ?)", (g.user["id"], video_id, datetime.utcnow().isoformat()))
        db.commit()
    return redirect(url_for("watch", video_id=video_id))


@app.route("/video/<int:video_id>/comment", methods=["POST"])
@login_required
def add_comment(video_id):
    body = request.form.get("body", "").strip()
    if not body or len(body) > 1000:
        flash("Comment must contain 1–1000 characters.", "error")
    else:
        with connect_db() as db:
            exists = db.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone()
            if not exists:
                abort(404)
            db.execute("INSERT INTO comments (user_id, video_id, body, created_at) VALUES (?, ?, ?, ?)",
                       (g.user["id"], video_id, body, datetime.utcnow().isoformat()))
            db.commit()
    return redirect(url_for("watch", video_id=video_id) + "#comments")


@app.route("/creator/<int:creator_id>/subscribe", methods=["POST"])
@login_required
def toggle_subscription(creator_id):
    if creator_id == g.user["id"]:
        flash("You cannot subscribe to your own channel.", "info")
        return redirect(request.referrer or url_for("index"))
    with connect_db() as db:
        creator = db.execute("SELECT id FROM users WHERE id = ?", (creator_id,)).fetchone()
        if not creator:
            abort(404)
        existing = db.execute("SELECT 1 FROM subscriptions WHERE subscriber_id = ? AND creator_id = ?", (g.user["id"], creator_id)).fetchone()
        if existing:
            db.execute("DELETE FROM subscriptions WHERE subscriber_id = ? AND creator_id = ?", (g.user["id"], creator_id))
        else:
            db.execute("INSERT INTO subscriptions (subscriber_id, creator_id, created_at) VALUES (?, ?, ?)",
                       (g.user["id"], creator_id, datetime.utcnow().isoformat()))
        db.commit()
    return redirect(request.referrer or url_for("index"))


@app.route("/channel/<int:user_id>")
def channel(user_id):
    with connect_db() as db:
        creator = db.execute("""
            SELECT u.id, u.username,
            (SELECT COUNT(*) FROM subscriptions s WHERE s.creator_id = u.id) AS subscriber_count
            FROM users u WHERE u.id = ?
        """, (user_id,)).fetchone()
        if not creator:
            abort(404)
        videos = db.execute("""
            SELECT v.*, u.username,
            (SELECT COUNT(*) FROM likes l WHERE l.video_id = v.id) AS like_count
            FROM videos v JOIN users u ON u.id = v.user_id
            WHERE v.user_id = ? ORDER BY v.created_at DESC
        """, (user_id,)).fetchall()
        subscribed = False
        if g.user:
            subscribed = bool(db.execute("SELECT 1 FROM subscriptions WHERE subscriber_id = ? AND creator_id = ?", (g.user["id"], user_id)).fetchone())
    return render_template("channel.html", creator=creator, videos=videos, subscribed=subscribed)


@app.route("/my-videos")
@login_required
def my_videos():
    with connect_db() as db:
        videos = db.execute("""
            SELECT v.*, u.username,
            (SELECT COUNT(*) FROM likes l WHERE l.video_id = v.id) AS like_count
            FROM videos v JOIN users u ON u.id = v.user_id
            WHERE v.user_id = ? ORDER BY v.created_at DESC
        """, (g.user["id"],)).fetchall()
    return render_template("my_videos.html", videos=videos)


@app.route("/video/<int:video_id>/delete", methods=["POST"])
@login_required
def delete_video(video_id):
    with connect_db() as db:
        video = db.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        if not video:
            abort(404)
        if video["user_id"] != g.user["id"]:
            abort(403)
        db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        db.commit()
    try:
        (UPLOAD_DIR / video["filename"]).unlink(missing_ok=True)
    except OSError:
        pass
    flash("Video deleted.", "success")
    return redirect(url_for("my_videos"))


@app.errorhandler(413)
def too_large(_error):
    flash(f"That file is too large. Maximum upload size is {MAX_UPLOAD_MB} MB.", "error")
    return redirect(url_for("upload"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You don't have permission to access that."), 403


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
