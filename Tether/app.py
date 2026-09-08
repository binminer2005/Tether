import os
import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, flash, g, has_app_context, redirect, render_template, request, send_from_directory, session, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TETHER_DATA_DIR", BASE_DIR))
app.config["DATABASE"] = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "tether.sqlite3"))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
if os.environ.get("TRUST_PROXY", "0") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
google_credentials_files = sorted(Path(__file__).parent.glob("client_secret_*.json"))
google_credentials = {}
if google_credentials_files:
    try:
        google_payload = json.loads(google_credentials_files[0].read_text(encoding="utf-8"))
        google_credentials = google_payload.get("web", {})
    except (OSError, json.JSONDecodeError):
        google_credentials = {}
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID") or google_credentials.get("client_id")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET") or google_credentials.get("client_secret")
FONT_DIR = BASE_DIR / "Font"
LOGO_DIR = BASE_DIR / "logo"
PICS_DIR = Path(os.environ.get("TETHER_PICS_DIR", DATA_DIR / "Pics"))
UPLOAD_DIR = Path(os.environ.get("TETHER_UPLOAD_DIR", BASE_DIR / "static" / "uploads"))
USERS_FILE = Path(os.environ.get("USERS_FILE", DATA_DIR / "users.json"))
PICS_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.config["DATABASE"].parent.mkdir(parents=True, exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)
oauth = OAuth(app)
if app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"]:
    oauth.register(
        name="google",
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


PASSWORD_HASH_METHOD = "scrypt"


def hash_password(password):
    return generate_password_hash(password, method=PASSWORD_HASH_METHOD)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            google_id TEXT UNIQUE,
            avatar_url TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            content TEXT NOT NULL,
            content_json TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        CREATE TABLE IF NOT EXISTS editorial_articles (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            category_label TEXT,
            excerpt TEXT,
            author TEXT,
            read_time TEXT,
            image TEXT,
            source_json TEXT,
            editorial_json TEXT,
            status TEXT NOT NULL DEFAULT 'published',
            published_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS editorial_article_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL,
            block_type TEXT NOT NULL,
            heading TEXT,
            text TEXT,
            items_json TEXT,
            image_src TEXT,
            alt_text TEXT,
            FOREIGN KEY (article_id) REFERENCES editorial_articles (id) ON DELETE CASCADE
        );
        """
    )
    submission_columns = {row["name"] for row in db.execute("PRAGMA table_info(submissions)")}
    if "content_json" not in submission_columns:
        db.execute("ALTER TABLE submissions ADD COLUMN content_json TEXT")
    columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    if "google_id" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
    if "avatar_url" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users (google_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_editorial_articles_category ON editorial_articles (category)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_editorial_article_blocks_article ON editorial_article_blocks (article_id, sort_order)")
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_email and admin_password:
        db.execute(
            "INSERT OR IGNORE INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
            ("Quản trị viên", admin_email.lower().strip(), hash_password(admin_password), datetime.now(timezone.utc).isoformat()),
        )
    if USERS_FILE.exists():
        try:
            configured_users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            configured_users = []
        if isinstance(configured_users, list):
            for configured_user in configured_users:
                if not isinstance(configured_user, dict):
                    continue
                email = configured_user.get("email", "").strip().lower()
                name = configured_user.get("name", "").strip()
                role = configured_user.get("role", "user")
                password_env = configured_user.get("password_env", "")
                if not email or not name or role not in {"user", "admin"}:
                    continue
                existing_user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                if existing_user:
                    db.execute("UPDATE users SET name = ?, role = ? WHERE id = ?", (name, role, existing_user["id"]))
                elif password_env and os.environ.get(password_env):
                    db.execute(
                        "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                        (name, email, hash_password(os.environ[password_env]), role, datetime.now(timezone.utc).isoformat()),
                    )
    db.commit()


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.after_request
def disable_dev_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.before_request
def load_logged_in_user():
    init_db()
    user_id = session.get("user_id")
    g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None


@app.context_processor
def inject_user():
    return {
        "current_user": g.get("user"),
        "CATEGORY_LABELS": CATEGORY_LABELS,
        "asset_version": asset_version,
        "versioned_image_url": versioned_image_url,
    }


def asset_version(path):
    """Return a file timestamp so edited assets get a new browser URL."""
    file_path = Path(__file__).parent / path
    try:
        return file_path.stat().st_mtime_ns
    except OSError:
        return "dev"


def versioned_image_url(image_path):
    if not image_path or not image_path.startswith("/pics/"):
        return image_path
    filename = image_path.removeprefix("/pics/")
    return f"{image_path}?v={asset_version(f'Pics/{filename}')}"


def login_required(view):
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            flash("Bạn cần đăng nhập để thực hiện thao tác này.", "error")
            return redirect(url_for("sign", next=request.path))
        return view(*args, **kwargs)

    wrapped_view.__name__ = view.__name__
    return wrapped_view


def admin_required(view):
    def wrapped_view(*args, **kwargs):
        if g.user is None or g.user["role"] != "admin":
            flash("Bạn không có quyền truy cập khu vực này.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)

    wrapped_view.__name__ = view.__name__
    return wrapped_view


def slugify(value):
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    return re.sub(r"[-\s]+", "-", value).strip("-")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}, 200


@app.route("/fonts/<path:filename>")
def fonts(filename):
    return send_from_directory(FONT_DIR, filename)


@app.route("/logo/<path:filename>")
def logos(filename):
    return send_from_directory(LOGO_DIR, filename)


@app.route("/pics/<path:filename>")
def pics(filename):
    return send_from_directory(PICS_DIR, filename)

# ---------------------------------------------------------------------------
# Dữ liệu mẫu
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "hoc-thuat": "Học thuật",
    "cam-xuc": "Cảm xúc",
    "chua-lanh": "Chữa lành",
}

ARTICLES = [
    {
        "id": 1,
        "category": "hoc-thuat",
        "category_label": "Học thuật",
        "title": "Vì sao trí nhớ hay 'phản bội' ta khi ta buồn nhất",
        "excerpt": "Một góc nhìn tâm lý học nhận thức về cách cảm xúc bóp méo ký ức, và vì sao điều đó không có nghĩa là bạn đang nói dối chính mình.",
        "author": "Tether",
        "read_time": "9 phút đọc",
        "image": "/pics/AnhThu1.jpg",
    },
    {
        "id": 2,
        "category": "hoc-thuat",
        "category_label": "Học thuật",
        "title": "Lý thuyết gắn bó: vì sao ta yêu theo một khuôn mẫu quen thuộc",
        "excerpt": "Attachment theory không chỉ dành cho các mối quan hệ lãng mạn — nó giải thích cả cách ta phản ứng với bạn bè, đồng nghiệp và chính mình.",
        "author": "Tether",
        "read_time": "11 phút đọc",
    },
    {
        "id": 3,
        "category": "cam-xuc",
        "category_label": "Cảm xúc",
        "title": "Ngày tôi nhận ra mình đã ổn, dù chưa ai nói điều đó",
        "excerpt": "Một bài viết cá nhân về hành trình rời khỏi một mối quan hệ độc hại, và những dấu hiệu nhỏ cho thấy mình đang thực sự khá lên.",
        "author": "Người kể ẩn danh",
        "read_time": "7 phút đọc",
    },
    {
        "id": 4,
        "category": "cam-xuc",
        "category_label": "Cảm xúc",
        "title": "Tôi đã học cách xin lỗi bố sau mười năm im lặng",
        "excerpt": "Không phải câu chuyện nào cũng có cái kết đẹp — nhưng có những cuộc trò chuyện, dù muộn, vẫn đáng để bắt đầu.",
        "author": "Người kể ẩn danh",
        "read_time": "8 phút đọc",
    },
    {
        "id": 5,
        "category": "chua-lanh",
        "category_label": "Chữa lành",
        "title": "Bạn không cần phải 'vượt qua' nỗi buồn đúng thời hạn",
        "excerpt": "Xã hội thích những câu chuyện chữa lành có kết thúc gọn gàng. Thực tế thường lộn xộn hơn thế — và điều đó hoàn toàn ổn.",
        "author": "Tether",
        "read_time": "6 phút đọc",
    },
    {
        "id": 6,
        "category": "chua-lanh",
        "category_label": "Chữa lành",
        "title": "Ba câu hỏi để tự kiểm tra mình trước khi đưa ra quyết định lớn",
        "excerpt": "Không phải để có câu trả lời đúng ngay lập tức, mà để chậm lại đủ lâu trước khi quyết định điều gì đó quan trọng.",
        "author": "Tether",
        "read_time": "5 phút đọc",
    },
]

ARTICLES[0]["sections"] = [
    {
        "heading": "Khi nỗi buồn làm ký ức đổi màu",
        "paragraphs": [
            "Có những ngày ta nhớ rất rõ một câu nói, một ánh nhìn, hoặc một chi tiết nhỏ trong một cuộc trò chuyện. Nhưng khi tâm trạng thay đổi, cùng ký ức ấy có thể bỗng trở nên nặng nề hơn, như thể nó vừa được phủ thêm một lớp màu khác.",
            "Điều này không có nghĩa là ký ức của bạn giả tạo. Trí nhớ không hoạt động như một chiếc camera chỉ ghi lại sự kiện. Mỗi lần nhớ lại, não bộ tái dựng sự kiện từ những mảnh thông tin còn sót lại, cùng với cảm xúc và góc nhìn của hiện tại.",
        ],
    },
    {
        "heading": "Cảm xúc không xóa sự thật, nhưng có thể đổi trọng tâm",
        "paragraphs": [
            "Khi buồn, sự chú ý thường bị hút về những dấu hiệu của mất mát, bị từ chối hoặc thất vọng. Những chi tiết phù hợp với cảm giác đó dễ được gọi lại hơn, trong khi các chi tiết trung tính hoặc tích cực tạm thời lùi xuống phía sau.",
            "Vì vậy, câu hỏi hữu ích không phải là “Mình có đang nhớ sai không?”, mà là “Tâm trạng hiện tại đang khiến mình nhìn thấy phần nào của câu chuyện?”. Câu hỏi này mở ra khoảng cách vừa đủ để ta kiểm tra lại ký ức mà không phủ nhận cảm xúc.",
        ],
    },
    {
        "heading": "Ba cách đọc lại một ký ức khó",
        "paragraphs": [
            "Hãy viết sự kiện theo trình tự thời gian, tách phần mình trực tiếp nhìn thấy khỏi phần mình suy đoán. Sau đó, thử ghi lại một cách giải thích khác, công bằng hơn với bản thân và những người liên quan.",
            "Cuối cùng, đừng ép mình phải kết luận ngay. Một ký ức có thể vẫn đau và vẫn chứa những điều đúng cùng lúc. Hiểu được cơ chế của trí nhớ không làm nỗi buồn biến mất, nhưng giúp ta không phải một mình chống lại nó.",
        ],
    },
]

for a in ARTICLES:
    a["url"] = f"/bai-viet/{a['id']}"


def load_editorial_articles_from_db():
    """Load editorial articles from SQLite in a format compatible with the current app."""
    if has_app_context():
        db = get_db()
        close_connection = False
    else:
        db = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        close_connection = True
    try:
        table_exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'editorial_articles'"
        ).fetchone()
        if table_exists is None:
            return []

        rows = db.execute(
            "SELECT * FROM editorial_articles ORDER BY id ASC"
        ).fetchall()
        articles = []
        for row in rows:
            source = json.loads(row["source_json"]) if row["source_json"] else {}
            editorial = json.loads(row["editorial_json"]) if row["editorial_json"] else {}
            block_rows = db.execute(
                "SELECT * FROM editorial_article_blocks WHERE article_id = ? ORDER BY sort_order ASC",
                (row["id"],),
            ).fetchall()
            blocks = []
            for block_row in block_rows:
                block = {"type": block_row["block_type"]}
                if block_row["heading"]:
                    block["heading"] = block_row["heading"]
                if block_row["text"]:
                    block["text"] = block_row["text"]
                if block_row["items_json"]:
                    try:
                        items = json.loads(block_row["items_json"])
                        if isinstance(items, list):
                            block["items"] = items
                    except (TypeError, json.JSONDecodeError):
                        pass
                if block_row["image_src"]:
                    block["src"] = block_row["image_src"]
                if block_row["alt_text"]:
                    block["alt"] = block_row["alt_text"]
                blocks.append(block)

            article = {
                "id": row["id"],
                "category": row["category"],
                "category_label": row["category_label"] or CATEGORY_LABELS.get(row["category"], row["category"]),
                "title": row["title"],
                "excerpt": row["excerpt"],
                "author": row["author"] or (source.get("author_name") if isinstance(source, dict) else "Tether"),
                "read_time": row["read_time"] or "Bài biên tập",
                "image": row["image"],
                "source": source,
                "editorial": editorial,
                "blocks": blocks,
            }
            article["url"] = f"/bai-viet/{article['id']}"
            articles.append(article)
        return articles
    finally:
        if close_connection:
            db.close()


def load_editorial_articles():
    """Load Tether's editorial articles from SQLite."""
    return load_editorial_articles_from_db()


EDITORIAL_ARTICLE_IDS = set()


def refresh_editorial_articles():
    """Reload the editorial catalog from SQLite."""
    global EDITORIAL_ARTICLE_IDS

    loaded_articles = load_editorial_articles()
    loaded_ids = {article.get("id") for article in loaded_articles}
    for article_id in EDITORIAL_ARTICLE_IDS - loaded_ids:
        ARTICLES[:] = [article for article in ARTICLES if article["id"] != article_id]
    for editorial_article in loaded_articles:
        existing = next((item for item in ARTICLES if item["id"] == editorial_article.get("id")), None)
        if existing is None:
            existing = editorial_article
            ARTICLES.append(existing)
        else:
            existing.clear()
            existing.update(editorial_article)
        existing["url"] = f"/bai-viet/{existing['id']}"
    EDITORIAL_ARTICLE_IDS = loaded_ids


with app.app_context():
    refresh_editorial_articles()

RADIO_EPISODES = [
    {
        "id": 12,
        "kind": "radio",
        "title": "Tập 12 — Khi kiến thức không đủ để chữa lành",
        "desc": "Một cuộc trò chuyện về ranh giới giữa hiểu biết lý thuyết và trải nghiệm chữa lành thật sự.",
        "duration": "38 phút",
        "guest": "cùng một nhà tâm lý học lâm sàng",
    },
    {
        "id": 11,
        "kind": "radio",
        "title": "Tập 11 — Nỗi buồn mùa thu có thật hay không",
        "desc": "Góc nhìn khoa học về rối loạn cảm xúc theo mùa, và vì sao tháng 9-10 lại dễ khiến ta chùng xuống.",
        "duration": "29 phút",
        "guest": "cùng biên tập viên Tether",
    },
    {
        "id": 10,
        "kind": "radio",
        "title": "Tập 10 — Viết nhật ký có thực sự giúp ích?",
        "desc": "Nhìn lại các nghiên cứu về expressive writing và cách áp dụng nó mà không biến nó thành áp lực.",
        "duration": "24 phút",
        "guest": "cùng một nhà nghiên cứu hành vi",
    },
]

PODCAST_EPISODES = [
    {
        "id": 11,
        "kind": "podcast",
        "title": "Tập 11 — Ranh giới không phải là ích kỷ",
        "desc": "Một buổi trò chuyện dài với nhà trị liệu gia đình về cách thiết lập ranh giới mà không mang cảm giác tội lỗi.",
        "duration": "52 phút",
        "guest": "cùng một nhà trị liệu gia đình",
    },
    {
        "id": 10,
        "kind": "podcast",
        "title": "Tập 10 — Làm việc chăm chỉ có phải là một dạng né tránh?",
        "desc": "Khi sự bận rộn trở thành cách để không phải đối diện với những câu hỏi khó về bản thân.",
        "duration": "47 phút",
        "guest": "cùng một huấn luyện viên nghề nghiệp",
    },
    {
        "id": 9,
        "kind": "podcast",
        "title": "Tập 09 — Lớn lên cùng một người mẹ cầu toàn",
        "desc": "Khách mời chia sẻ hành trình gỡ rối những kỳ vọng được thừa hưởng từ gia đình.",
        "duration": "44 phút",
        "guest": "khách mời ẩn danh",
    },
]


def articles_by_category(cat):
    refresh_editorial_articles()
    return [a for a in ARTICLES if a["category"] == cat]


def published_submissions(category=None):
    query = "SELECT submissions.*, users.name AS author_name FROM submissions JOIN users ON users.id = submissions.user_id WHERE submissions.status = 'published'"
    params = ()
    if category:
        query += " AND submissions.category = ?"
        params = (category,)
    return get_db().execute(query + " ORDER BY submissions.id DESC", params).fetchall()


def submission_to_article(item):
    """Map an approved community submission to the public article shape."""
    return {
        "id": item["id"],
        "category": item["category"],
        "category_label": CATEGORY_LABELS[item["category"]],
        "title": item["title"],
        "excerpt": item["excerpt"],
        "author": item["author_name"],
        "source": {"type": "community", "label": "Bài viết cộng đồng", "author_role": "reader"},
        "editorial": {"status": "published", "reviewed": True},
        "read_time": "Bài cộng đồng",
        "url": url_for("published_submission_detail", submission_id=item["id"]),
    }


def article_cards(category=None):
    refresh_editorial_articles()
    cards = articles_by_category(category) if category else list(ARTICLES)
    for item in published_submissions(category):
        cards.append(submission_to_article(item))
    return cards


def content_to_blocks(content):
    """Convert the simple authoring format into renderable article blocks."""
    blocks = []
    paragraph_lines = []
    list_items = []

    def flush_paragraph():
        if paragraph_lines:
            blocks.append({"type": "paragraph", "text": " ".join(paragraph_lines)})
            paragraph_lines.clear()

    def flush_list():
        if list_items:
            blocks.append({"type": "list", "items": list(list_items)})
            list_items.clear()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue

        image_match = re.match(r"^!\[(.*?)\]\((.*?)\)$", line)
        if image_match:
            flush_paragraph()
            flush_list()
            blocks.append({"type": "image", "src": image_match.group(2).strip(), "alt": image_match.group(1).strip() or "Hình ảnh bài viết"})
            continue

        if line.startswith("## "):
            flush_paragraph()
            flush_list()
            blocks.append({"type": "heading", "text": line[3:].strip()})
        elif line.startswith("> "):
            flush_paragraph()
            flush_list()
            blocks.append({"type": "quote", "text": line[2:].strip()})
        elif line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:].strip())
        else:
            flush_list()
            paragraph_lines.append(line)

    flush_paragraph()
    flush_list()
    return blocks


def submission_blocks(item):
    try:
        blocks = json.loads(item["content_json"] or "")
        if isinstance(blocks, list):
            return blocks
    except (TypeError, json.JSONDecodeError):
        pass
    return content_to_blocks(item["content"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def landingpage():
    return render_template("landingpage.html", active="landing")


@app.route("/home")
def home():
    refresh_editorial_articles()
    return render_template(
        "home.html",
        active="home",
        featured=ARTICLES[0],
        latest=ARTICLES[1:4],
        radio_preview=RADIO_EPISODES[:1],
        podcast_preview=PODCAST_EPISODES[:1],
    )


@app.route("/dang-nhap", methods=["GET", "POST"])
@app.route("/sign", methods=["GET", "POST"])
def sign():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Email hoặc mật khẩu chưa đúng.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            flash("Đăng nhập thành công.", "success")
            return redirect(request.args.get("next") or url_for("home"))
    return render_template("sign.html", active="sign")


@app.route("/dang-ky", methods=["GET", "POST"])
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Vui lòng điền đủ thông tin và dùng mật khẩu ít nhất 8 ký tự.", "error")
        else:
            try:
                db = get_db()
                cursor = db.execute(
                    "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (name, email, hash_password(password), datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash("Email này đã được đăng ký.", "error")
            else:
                session.clear()
                session["user_id"] = cursor.lastrowid
                flash("Tài khoản đã được tạo.", "success")
                return redirect(url_for("submit_article"))
    return render_template("register.html", active="register")


@app.route("/dang-xuat")
def logout():
    session.clear()
    flash("Bạn đã đăng xuất.", "success")
    return redirect(url_for("landingpage"))


@app.route("/dang-nhap/google")
def google_login():
    if not app.config["GOOGLE_CLIENT_ID"] or not app.config["GOOGLE_CLIENT_SECRET"]:
        flash("Đăng nhập Google chưa được cấu hình. Vui lòng dùng email và mật khẩu.", "error")
        return redirect(url_for("sign"))
    next_url = request.args.get("next")
    if next_url:
        session["google_next"] = next_url
    redirect_uri = url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/dang-ky/google/hoan-tat", methods=["GET", "POST"])
def complete_google_registration():
    pending_google = session.get("pending_google")
    if not pending_google:
        flash("Phiên đăng ký Google đã hết hạn. Vui lòng thử lại.", "error")
        return redirect(url_for("sign"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        if not name or len(password) < 8:
            flash("Vui lòng nhập họ tên và mật khẩu ít nhất 8 ký tự.", "error")
        else:
            db = get_db()
            existing_user = db.execute("SELECT id FROM users WHERE email = ?", (pending_google["email"],)).fetchone()
            if existing_user:
                session.pop("pending_google", None)
                flash("Email Google này đã được đăng ký. Vui lòng đăng nhập bằng email và mật khẩu.", "error")
                return redirect(url_for("sign"))
            cursor = db.execute(
                "INSERT INTO users (name, email, password_hash, google_id, avatar_url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    name,
                    pending_google["email"],
                    hash_password(password),
                    pending_google["google_id"],
                    pending_google.get("avatar_url"),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            db.commit()
            next_url = pending_google.get("next") or url_for("home")
            session.clear()
            session["user_id"] = cursor.lastrowid
            flash("Tài khoản Google đã được tạo thành công.", "success")
            return redirect(next_url)
    return render_template(
        "complete_google_registration.html",
        active="register",
        google_email=pending_google["email"],
    )


@app.route("/dang-nhap/google/callback")
def google_callback():
    if not app.config["GOOGLE_CLIENT_ID"] or not app.config["GOOGLE_CLIENT_SECRET"]:
        return redirect(url_for("sign"))
    try:
        token = oauth.google.authorize_access_token()
        profile = token.get("userinfo") or oauth.google.userinfo()
    except Exception:
        flash("Không thể hoàn tất đăng nhập Google. Vui lòng thử lại.", "error")
        return redirect(url_for("sign"))
    email = (profile.get("email") or "").strip().lower()
    google_id = profile.get("sub")
    if not email or not google_id or not profile.get("email_verified", False):
        flash("Tài khoản Google chưa cung cấp email đã xác minh.", "error")
        return redirect(url_for("sign"))
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE google_id = ? OR email = ?", (google_id, email)).fetchone()
    if user is None:
        session["pending_google"] = {
            "email": email,
            "google_id": google_id,
            "avatar_url": profile.get("picture"),
            "next": session.pop("google_next", None),
        }
        return redirect(url_for("complete_google_registration"))
    else:
        db.execute("UPDATE users SET google_id = ?, avatar_url = ? WHERE id = ?", (google_id, profile.get("picture"), user["id"]))
        user_id = user["id"]
    db.commit()
    session.clear()
    session["user_id"] = user_id
    flash("Đăng nhập Google thành công.", "success")
    return redirect(request.args.get("next") or url_for("home"))


@app.route("/viet-bai", methods=["GET", "POST"])
@login_required
def submit_article():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        excerpt = request.form.get("excerpt", "").strip()
        content = request.form.get("content", "").strip()

        image_parts = []
        uploaded_files = request.files.getlist("images")
        for uploaded_file in uploaded_files:
            if uploaded_file and uploaded_file.filename:
                filename = secure_filename(uploaded_file.filename)
                if filename:
                    saved_path = UPLOAD_DIR / filename
                    uploaded_file.save(saved_path)
                    image_url = url_for("static", filename=f"uploads/{filename}")
                    image_parts.append(f"![{filename}]({image_url})")

        if image_parts:
            content = f"{content.rstrip()}\n\n" + "\n\n".join(image_parts)

        if category not in CATEGORY_LABELS or not title or not excerpt or not content:
            flash("Vui lòng điền đầy đủ các trường bắt buộc.", "error")
        else:
            db = get_db()
            db.execute(
                "INSERT INTO submissions (user_id, title, category, excerpt, content, content_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (g.user["id"], title, category, excerpt, content, json.dumps(content_to_blocks(content), ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )
            db.commit()
            flash("Bài viết đã được gửi và đang chờ biên tập viên duyệt.", "success")
            return redirect(url_for("my_submissions"))
    return render_template("submit_article.html", active="submit", categories=CATEGORY_LABELS)


@app.route("/bai-cua-toi")
@login_required
def my_submissions():
    submissions = get_db().execute(
        "SELECT * FROM submissions WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)
    ).fetchall()
    return render_template("my_submissions.html", active="submit", submissions=submissions)


@app.route("/quan-tri/bai-viet")
@admin_required
def article_dict_from_db_row(row):
    """Convert a sqlite row into the public article shape used by the templates."""
    source = json.loads(row["source_json"]) if row["source_json"] else {}
    editorial = json.loads(row["editorial_json"]) if row["editorial_json"] else {}
    blocks = []
    for block_row in get_db().execute(
        "SELECT * FROM editorial_article_blocks WHERE article_id = ? ORDER BY sort_order ASC",
        (row["id"],),
    ).fetchall():
        block = {"type": block_row["block_type"]}
        if block_row["heading"]:
            block["heading"] = block_row["heading"]
        if block_row["text"]:
            block["text"] = block_row["text"]
        if block_row["items_json"]:
            try:
                items = json.loads(block_row["items_json"])
                if isinstance(items, list):
                    block["items"] = items
            except (TypeError, json.JSONDecodeError):
                pass
        if block_row["image_src"]:
            block["src"] = block_row["image_src"]
        if block_row["alt_text"]:
            block["alt"] = block_row["alt_text"]
        blocks.append(block)
    article = {
        "id": row["id"],
        "category": row["category"],
        "category_label": row["category_label"] or CATEGORY_LABELS.get(row["category"], row["category"]),
        "title": row["title"],
        "excerpt": row["excerpt"],
        "author": row["author"],
        "read_time": row["read_time"],
        "image": row["image"],
        "source": source,
        "editorial": editorial,
        "blocks": blocks,
        "status": row["status"],
        "published_at": row["published_at"],
    }
    article["url"] = f"/bai-viet/{article['id']}"
    return article


@app.route("/quan-tri/bai-viet-editorial", methods=["GET", "POST"])
@admin_required
def admin_editorial_articles():
    db = get_db()
    article_id = request.args.get("edit_id", type=int)
    editing = None
    if article_id:
        row = db.execute("SELECT * FROM editorial_articles WHERE id = ?", (article_id,)).fetchone()
        if row is not None:
            editing = article_dict_from_db_row(row)

    if request.method == "POST":
        form_article_id = request.form.get("article_id")
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        excerpt = request.form.get("excerpt", "").strip()
        author = request.form.get("author", "Tether").strip() or "Tether"
        read_time = request.form.get("read_time", "Bài biên tập").strip() or "Bài biên tập"
        image = editing["image"] if editing else ""
        uploaded_image = request.files.get("image")
        image_filename = ""
        if uploaded_image and uploaded_image.filename:
            image_filename = secure_filename(uploaded_image.filename)
            if image_filename:
                uploaded_image.save(PICS_DIR / image_filename)
                image = f"/pics/{image_filename}"
        published_at = request.form.get("published_at", "").strip() or datetime.now(timezone.utc).date().isoformat()
        status = request.form.get("status", "published").strip() or "published"
        markdown = request.form.get("content", "").strip()
        if uploaded_image and image and image_filename:
            markdown = f"{markdown}\n\n![{image_filename}]({image})"
        if category not in CATEGORY_LABELS or not title or not excerpt or not markdown:
            flash("Vui lòng điền đầy đủ tiêu đề, danh mục, mô tả và nội dung bài viết.", "error")
            return redirect(url_for("admin_editorial_articles"))

        article_payload = {
            "id": int(form_article_id) if form_article_id else None,
            "title": title,
            "category": category,
            "category_label": CATEGORY_LABELS[category],
            "excerpt": excerpt,
            "author": author,
            "read_time": read_time,
            "image": image,
            "source": {"type": "editorial", "label": "Tether biên soạn", "author_name": author, "author_role": "editor"},
            "editorial": {"status": status, "reviewed": True, "reviewed_by": "Tether", "published_at": published_at},
            "blocks": content_to_blocks(markdown),
        }
        if article_payload["id"] is None:
            article_payload["id"] = db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM editorial_articles").fetchone()[0]
        db.execute(
            """
            INSERT OR REPLACE INTO editorial_articles (
                id, title, category, category_label, excerpt, author, read_time, image,
                source_json, editorial_json, status, published_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                article_payload["id"],
                article_payload["title"],
                article_payload["category"],
                article_payload["category_label"],
                article_payload["excerpt"],
                author,
                article_payload["read_time"],
                article_payload["image"],
                json.dumps(article_payload["source"], ensure_ascii=False),
                json.dumps(article_payload["editorial"], ensure_ascii=False),
                status,
                published_at,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.execute("DELETE FROM editorial_article_blocks WHERE article_id = ?", (article_payload["id"],))
        for order_index, block in enumerate(article_payload["blocks"]):
            block_type = block.get("type") or "paragraph"
            items_json = json.dumps(block.get("items", []), ensure_ascii=False) if block_type == "list" else None
            db.execute(
                "INSERT INTO editorial_article_blocks (article_id, sort_order, block_type, heading, text, items_json, image_src, alt_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article_payload["id"],
                    order_index,
                    block_type,
                    block.get("heading"),
                    block.get("text"),
                    items_json,
                    block.get("src"),
                    block.get("alt"),
                ),
            )
        db.commit()
        flash("Bài viết đã được lưu vào SQLite.", "success")
        return redirect(url_for("admin_editorial_articles"))

    rows = db.execute("SELECT * FROM editorial_articles ORDER BY id DESC").fetchall()
    articles = [article_dict_from_db_row(row) for row in rows]
    return render_template(
        "admin_editorial_articles.html",
        active="admin",
        articles=articles,
        editing=editing,
        categories=CATEGORY_LABELS,
    )


@app.post("/quan-tri/bai-viet-editorial/<int:article_id>/xoa")
@admin_required
def delete_editorial_article(article_id):
    db = get_db()
    db.execute("DELETE FROM editorial_article_blocks WHERE article_id = ?", (article_id,))
    db.execute("DELETE FROM editorial_articles WHERE id = ?", (article_id,))
    db.commit()
    flash("Bài viết đã được xóa khỏi SQLite.", "success")
    return redirect(url_for("admin_editorial_articles"))


@app.route("/quan-tri/bai-viet")
@admin_required
def admin_submissions():
    status_filter = request.args.get("status", "pending").strip()
    valid_statuses = {"pending", "published", "rejected", "all"}
    if status_filter not in valid_statuses:
        status_filter = "pending"
    query = (
        "SELECT submissions.*, users.name AS author_name, users.email AS author_email "
        "FROM submissions JOIN users ON users.id = submissions.user_id"
    )
    params = ()
    if status_filter != "all":
        query += " WHERE submissions.status = ?"
        params = (status_filter,)
    submissions = get_db().execute(query + " ORDER BY submissions.id DESC", params).fetchall()
    pending_count = get_db().execute(
        "SELECT COUNT(*) AS total FROM submissions WHERE status = 'pending'"
    ).fetchone()["total"]
    return render_template(
        "admin_submissions.html",
        active="admin",
        submissions=submissions,
        status_filter=status_filter,
        pending_count=pending_count,
    )


@app.post("/quan-tri/bai-viet/<int:submission_id>/<action>")
@admin_required
def moderate_submission(submission_id, action):
    status_map = {"publish": "published", "reject": "rejected", "pending": "pending"}
    if action not in status_map:
        return "Thao tác không hợp lệ", 400
    db = get_db()
    db.execute("UPDATE submissions SET status = ? WHERE id = ?", (status_map[action], submission_id))
    db.commit()
    flash("Đã cập nhật trạng thái bài viết.", "success")
    return redirect(url_for("admin_submissions"))


@app.route("/kien-thuc")
def kien_thuc():
    return render_template("kienthuc.html", active="kienthuc", all_articles=article_cards())


@app.route("/bai-viet/<int:article_id>")
def article_detail(article_id):
    refresh_editorial_articles()
    article = next((item for item in ARTICLES if item["id"] == article_id), None)
    if article is None:
        return "Không tìm thấy bài viết", 404
    return render_template("article_detail.html", active="kienthuc", article=article)


@app.route("/bai-viet-cong-dong/<int:submission_id>")
def published_submission_detail(submission_id):
    item = get_db().execute(
        "SELECT submissions.*, users.name AS author_name FROM submissions "
        "JOIN users ON users.id = submissions.user_id "
        "WHERE submissions.id = ? AND submissions.status = 'published'", (submission_id,)
    ).fetchone()
    if item is None:
        return "Không tìm thấy bài viết", 404
    article = submission_to_article(item)
    article["blocks"] = submission_blocks(item)
    return render_template("article_detail.html", active="kienthuc", article=article)


@app.route("/kien-thuc/hoc-thuat")
def hoc_thuat():
    return render_template(
        "hocthuat.html", active="kienthuc", articles=article_cards("hoc-thuat")
    )


@app.route("/kien-thuc/cam-xuc")
def cam_xuc():
    return render_template(
        "camxuc.html", active="kienthuc", articles=article_cards("cam-xuc")
    )


@app.route("/kien-thuc/chua-lanh")
def chua_lanh():
    return render_template(
        "chualanh.html", active="kienthuc", articles=article_cards("chua-lanh")
    )


@app.route("/radio")
def radio():
    return render_template("radio.html", active="radio", episodes=RADIO_EPISODES)


@app.route("/podcast")
def podcast():
    return render_template("podcast.html", active="podcast", episodes=PODCAST_EPISODES)


@app.route("/listen/<kind>/<int:episode_id>")
def listen(kind, episode_id):
    episode_list = RADIO_EPISODES if kind == "radio" else PODCAST_EPISODES if kind == "podcast" else []
    episode = next((item for item in episode_list if item["id"] == episode_id), None)
    if episode is None:
        return redirect(url_for("radio" if kind == "radio" else "podcast"))
    return render_template(
        "listen.html",
        active=kind,
        kind=kind,
        episode=episode,
        episodes=episode_list,
        kind_label="Radio" if kind == "radio" else "Podcast",
    )


if __name__ == "__main__":
    print("Tether đang chạy tại: http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
