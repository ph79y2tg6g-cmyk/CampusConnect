
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
import sqlite3
import os
import uuid
from pathlib import Path
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "dev-only-change-this-secret-key"
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "campus.db"
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

BRANCHES = [
    "All Branches", "CSE", "AIML", "ISE", "ECE", "EEE",
    "Mechanical Engineering", "Civil Engineering"
]

SPORTS_INDIVIDUAL = [
    "100m Running", "200m Running", "400m Running",
    "800m Running", "Long Jump", "High Jump",
    "Shot Put", "Discus Throw"
]

SPORTS_TEAM = [
    "Kabaddi", "Volleyball", "Cricket", "Football",
    "Basketball", "Kho-Kho", "Throwball",
    "Relay Race", "Tug of War"
]

CULTURAL_INDIVIDUAL = [
    "Solo Singing", "Solo Dance", "Classical Dance",
    "Stand-up Comedy", "Poetry", "Mimicry",
    "Instrumental Music", "Photography", "Painting"
]

CULTURAL_GROUP = [
    "Group Dance", "Group Singing", "Drama", "Skit",
    "Fashion Show", "Group Music", "Mime",
    "Short Film", "Group Folk Dance"
]


# DATABASE CONNECTION

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# DATABASE INITIALIZATION

def init_db():
    with get_db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                event_date TEXT,
                venue TEXT,
                created_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        columns = [
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(posts)"
            ).fetchall()
        ]

        migrations = {
            "branch": "ALTER TABLE posts ADD COLUMN branch TEXT DEFAULT 'All Branches'",
            "is_demo": "ALTER TABLE posts ADD COLUMN is_demo INTEGER DEFAULT 0",
            "photo_filename": "ALTER TABLE posts ADD COLUMN photo_filename TEXT"
        }

        for column, sql in migrations.items():
            if column not in columns:
                conn.execute(sql)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # NEW: EVENT REGISTRATIONS TABLE
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                participation_type TEXT NOT NULL,
                selected_event TEXT NOT NULL,
                student_name TEXT NOT NULL,
                usn TEXT NOT NULL,
                branch TEXT NOT NULL,
                semester TEXT NOT NULL,
                phone TEXT NOT NULL,
                team_name TEXT,
                team_members TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        seed_demo_events(conn)


# SAMPLE EVENTS

def seed_demo_events(conn):
    demo_events = [
        (
            "Annual Sports Meet 2026", "Event",
            "Annual Sports Meet with cricket, football, volleyball, badminton and athletics.",
            "2026-11-28", "College Sports Ground", "All Branches"
        ),
        (
            "24-Hour National Level Hackathon 2026", "Event",
            "A 24-hour hackathon for students to showcase coding and problem-solving skills.",
            "2026-12-05", "Computer Science Department", "All Branches"
        ),
        (
            "RIT UTSAV 2026 - Annual College Fest", "Event",
            "Cultural performances, music, technical competitions and project exhibitions.",
            "2026-12-12", "College Auditorium and Campus", "All Branches"
        )
    ]

    for event in demo_events:
        exists = conn.execute(
            "SELECT id FROM posts WHERE title=? AND is_demo=1",
            (event[0],)
        ).fetchone()

        if not exists:
            conn.execute("""
                INSERT INTO posts (
                    title, category, description, event_date,
                    venue, created_by, status, branch, is_demo
                )
                VALUES (?, ?, ?, ?, ?, 'Demo Data', 'approved', ?, 1)
            """, event)


# PHOTO HELPERS

def allowed_file(filename):
    return bool(
        filename and "." in filename and
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def save_uploaded_photo(file):
    if not file or not file.filename:
        return None

    if not allowed_file(file.filename):
        raise ValueError(
            "Use a PNG, JPG, JPEG, GIF or WEBP image."
        )

    extension = secure_filename(file.filename).rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{extension}"
    file.save(UPLOAD_FOLDER / filename)

    return filename


def delete_uploaded_photo(filename):
    if filename:
        path = UPLOAD_FOLDER / filename
        if path.is_file():
            path.unlink()


# ADMIN LOGIN PROTECTION

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Please log in as an administrator.", "error")
            return redirect(url_for("admin"))
        return view(*args, **kwargs)
    return wrapped


# HOME PAGE

@app.route("/")
def home():
    with get_db() as conn:
        announcements = conn.execute("""
            SELECT * FROM posts
            WHERE status='approved'
              AND category IN ('Announcement', 'Placement')
            ORDER BY id DESC LIMIT 3
        """).fetchall()

        events = conn.execute("""
            SELECT * FROM posts
            WHERE status='approved' AND category='Event'
            ORDER BY event_date ASC LIMIT 3
        """).fetchall()

    return render_template(
        "index.html",
        announcements=announcements,
        events=events
    )


# PLACEMENTS

@app.route("/placements")
def placements():
    with get_db() as conn:
        notices = conn.execute("""
            SELECT * FROM posts
            WHERE status='approved' AND category='Placement'
            ORDER BY id DESC
        """).fetchall()

    return render_template("placements.html", notices=notices)


# EVENTS WITH BRANCH FILTER

@app.route("/events")
def events():
    selected_branch = request.args.get(
        "branch", "All Branches"
    )

    if selected_branch not in BRANCHES:
        selected_branch = "All Branches"

    with get_db() as conn:
        if selected_branch == "All Branches":
            items = conn.execute("""
                SELECT * FROM posts
                WHERE status='approved' AND category='Event'
                ORDER BY event_date ASC
            """).fetchall()
        else:
            items = conn.execute("""
                SELECT * FROM posts
                WHERE status='approved' AND category='Event'
                  AND (branch=? OR branch='All Branches')
                ORDER BY event_date ASC
            """, (selected_branch,)).fetchall()

    return render_template(
        "events.html",
        events=items,
        branches=BRANCHES,
        selected_branch=selected_branch
    )


# NEW: EVENT REGISTRATION

@app.route("/register/<event_type>", methods=["GET", "POST"])
def register_event(event_type):

    if event_type == "sports":
        event_title = "Annual Sports Meet 2026"
        individual_events = SPORTS_INDIVIDUAL
        team_events = SPORTS_TEAM

    elif event_type == "utsav":
        event_title = "RIT UTSAV 2026"
        individual_events = CULTURAL_INDIVIDUAL
        team_events = CULTURAL_GROUP

    else:
        flash("Invalid event.", "error")
        return redirect(url_for("events"))

    if request.method == "POST":

        participation_type = request.form.get(
            "participation_type", ""
        )

        selected_event = request.form.get(
            "selected_event", ""
        ).strip()

        student_name = request.form.get(
            "student_name", ""
        ).strip()

        usn = request.form.get("usn", "").strip()
        branch = request.form.get("branch", "").strip()
        semester = request.form.get("semester", "").strip()
        phone = request.form.get("phone", "").strip()

        team_name = request.form.get(
            "team_name", ""
        ).strip()

        team_members = request.form.get(
            "team_members", ""
        ).strip()

        # Check participation type
        if participation_type == "individual":
            allowed_events = individual_events

        elif participation_type == "team":
            allowed_events = team_events

        else:
            flash("Select a valid participation type.", "error")
            return redirect(url_for(
                "register_event", event_type=event_type
            ))

        # Check selected event
        if selected_event not in allowed_events:
            flash("Select a valid event.", "error")
            return redirect(url_for(
                "register_event", event_type=event_type
            ))

        # Check student details
        if not all([
            student_name, usn, branch,
            semester, phone
        ]):
            flash("Please fill in all required details.", "error")
            return redirect(url_for(
                "register_event", event_type=event_type
            ))

        if branch not in BRANCHES[1:]:
            flash("Select a valid branch.", "error")
            return redirect(url_for(
                "register_event", event_type=event_type
            ))

        if semester not in [str(i) for i in range(1, 9)]:
            flash("Select a valid semester.", "error")
            return redirect(url_for(
                "register_event", event_type=event_type
            ))

        if not phone.isdigit() or len(phone) != 10:
            flash("Enter a valid 10-digit phone number.", "error")
            return redirect(url_for(
                "register_event", event_type=event_type
            ))

        # Check team details
        if participation_type == "team":
            if not team_name or not team_members:
                flash("Enter the team name and team members.", "error")
                return redirect(url_for(
                    "register_event", event_type=event_type
                ))

            members = [
                line.strip()
                for line in team_members.splitlines()
                if line.strip()
            ]

            if not members:
                flash("Enter at least one team member.", "error")
                return redirect(url_for(
                    "register_event", event_type=event_type
                ))

        # Save registration
        with get_db() as conn:
            conn.execute("""
                INSERT INTO event_registrations (
                    event_type,
                    participation_type,
                    selected_event,
                    student_name,
                    usn,
                    branch,
                    semester,
                    phone,
                    team_name,
                    team_members
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_type,
                participation_type,
                selected_event,
                student_name,
                usn,
                branch,
                semester,
                phone,
                team_name if participation_type == "team" else None,
                team_members if participation_type == "team" else None
            ))

        flash("Registration submitted successfully!", "success")
        return redirect(url_for(
            "register_event", event_type=event_type
        ))

    return render_template(
        "register.html",
        event_type=event_type,
        event_title=event_title,
        individual_events=individual_events,
        team_events=team_events,
        branches=BRANCHES[1:]
    )


# ANNOUNCEMENTS WITH BRANCH FILTER

@app.route("/announcements")
def announcements():
    selected_branch = request.args.get(
        "branch", "All Branches"
    )

    if selected_branch not in BRANCHES:
        selected_branch = "All Branches"

    with get_db() as conn:
        if selected_branch == "All Branches":
            items = conn.execute("""
                SELECT * FROM posts
                WHERE status='approved'
                  AND category IN ('Announcement', 'Placement')
                ORDER BY id DESC
            """).fetchall()
        else:
            items = conn.execute("""
                SELECT * FROM posts
                WHERE status='approved'
                  AND category IN ('Announcement', 'Placement')
                  AND (branch=? OR branch='All Branches')
                ORDER BY id DESC
            """, (selected_branch,)).fetchall()

    return render_template(
        "announcements.html",
        announcements=items,
        branches=BRANCHES,
        selected_branch=selected_branch
    )


# STUDENT / FACULTY SUBMISSION

@app.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "POST":

        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        event_date = request.form.get("event_date", "").strip()
        venue = request.form.get("venue", "").strip()
        created_by = request.form.get("created_by", "").strip()
        branch = request.form.get(
            "branch", "All Branches"
        ).strip()

        if not all([title, category, description, created_by]):
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("submit"))

        if category not in ["Event", "Announcement"]:
            flash("Please choose a valid category.", "error")
            return redirect(url_for("submit"))

        if branch not in BRANCHES:
            flash("Please select a valid branch.", "error")
            return redirect(url_for("submit"))

        try:
            photo_filename = save_uploaded_photo(
                request.files.get("photo")
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("submit"))

        with get_db() as conn:
            conn.execute("""
                INSERT INTO posts (
                    title, category, description, event_date,
                    venue, created_by, status, branch,
                    is_demo, photo_filename
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 0, ?)
            """, (
                title, category, description, event_date,
                venue, created_by, branch, photo_filename
            ))

        flash(
            "Your submission was sent to the admin for approval.",
            "success"
        )
        return redirect(url_for("submit"))

    return render_template("submit.html", branches=BRANCHES)


# ADMIN REGISTRATION

@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        registration_code = request.form.get(
            "registration_code", ""
        )

        required_code = os.environ.get("ADMIN_REGISTRATION_CODE")

        if not required_code:
            flash(
                "Admin registration is not configured. "
                "Set ADMIN_REGISTRATION_CODE first.",
                "error"
            )
            return redirect(url_for("admin_register"))

        if registration_code != required_code:
            flash("Incorrect admin registration code.", "error")
            return redirect(url_for("admin_register"))

        if len(username) < 3 or len(password) < 8:
            flash(
                "Username must be at least 3 characters "
                "and password at least 8 characters.",
                "error"
            )
            return redirect(url_for("admin_register"))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("admin_register"))

        try:
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO admin_users (username, password_hash)
                    VALUES (?, ?)
                """, (
                    username,
                    generate_password_hash(password)
                ))
        except sqlite3.IntegrityError:
            flash("That username is already registered.", "error")
            return redirect(url_for("admin_register"))

        flash("Admin account created. You can now log in.", "success")
        return redirect(url_for("admin"))

    return render_template("admin_register.html")


# ADMIN LOGIN AND DASHBOARD

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST" and request.form.get("action") == "login":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db() as conn:
            admin_user = conn.execute("""
                SELECT * FROM admin_users
                WHERE username=? COLLATE NOCASE
            """, (username,)).fetchone()

        if admin_user and check_password_hash(
            admin_user["password_hash"], password
        ):
            session.clear()
            session["admin_id"] = admin_user["id"]
            session["admin_username"] = admin_user["username"]

            flash("Welcome to the admin dashboard.", "success")
            return redirect(url_for("admin"))

        flash("Incorrect username or password.", "error")

    if not session.get("admin_id"):
        return render_template("admin.html", logged_in=False)

    with get_db() as conn:
        pending = conn.execute("""
            SELECT * FROM posts
            WHERE status='pending'
            ORDER BY id DESC
        """).fetchall()

        approved = conn.execute("""
            SELECT * FROM posts
            WHERE status='approved'
            ORDER BY id DESC
        """).fetchall()

        rejected = conn.execute("""
            SELECT * FROM posts
            WHERE status='rejected'
            ORDER BY id DESC
        """).fetchall()

    return render_template(
        "admin.html",
        logged_in=True,
        pending=pending,
        approved=approved,
        rejected=rejected,
        branches=BRANCHES,
        admin_username=session.get("admin_username")
    )


# ADMIN ADD POST

@app.route("/admin/add", methods=["POST"])
@admin_required
def admin_add():

    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()
    event_date = request.form.get("event_date", "").strip()
    venue = request.form.get("venue", "").strip()
    branch = request.form.get("branch", "All Branches").strip()

    if not all([title, category, description]):
        flash("Title, category and description are required.", "error")
        return redirect(url_for("admin"))

    if category not in ["Event", "Announcement", "Placement"]:
        flash("Please select a valid category.", "error")
        return redirect(url_for("admin"))

    if branch not in BRANCHES:
        flash("Please select a valid branch.", "error")
        return redirect(url_for("admin"))

    try:
        photo_filename = save_uploaded_photo(
            request.files.get("photo")
        )
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin"))

    with get_db() as conn:
        conn.execute("""
            INSERT INTO posts (
                title, category, description, event_date,
                venue, created_by, status, branch,
                is_demo, photo_filename
            )
            VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, 0, ?)
        """, (
            title, category, description, event_date,
            venue, session.get("admin_username", "Admin"),
            branch, photo_filename
        ))

    flash("New information published successfully.", "success")
    return redirect(url_for("admin"))


# APPROVE, REJECT OR DELETE POSTS

@app.route("/admin/update/<int:post_id>/<action>", methods=["POST"])
@admin_required
def update_post(post_id, action):

    if action not in ["approve", "reject", "delete"]:
        flash("Invalid action.", "error")
        return redirect(url_for("admin"))

    with get_db() as conn:
        post = conn.execute("""
            SELECT photo_filename FROM posts WHERE id=?
        """, (post_id,)).fetchone()

        if not post:
            flash("Post not found.", "error")
            return redirect(url_for("admin"))

        if action == "approve":
            conn.execute("""
                UPDATE posts SET status='approved' WHERE id=?
            """, (post_id,))
            flash("Submission approved and published.", "success")

        elif action == "reject":
            conn.execute("""
                UPDATE posts SET status='rejected' WHERE id=?
            """, (post_id,))
            flash("Submission rejected.", "success")

        else:
            conn.execute("""
                DELETE FROM posts WHERE id=?
            """, (post_id,))
            delete_uploaded_photo(post["photo_filename"])
            flash("Post deleted.", "success")

    return redirect(url_for("admin"))


# NEW: ADMIN VIEW REGISTRATIONS

@app.route("/admin/registrations")
@admin_required
def admin_registrations():

    with get_db() as conn:
        registrations = conn.execute("""
            SELECT * FROM event_registrations
            ORDER BY registered_at DESC
        """).fetchall()

    return render_template(
        "admin_registrations.html",
        registrations=registrations
    )


# ADMIN LOGOUT

@app.route("/logout")
@admin_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


# FILE SIZE ERROR

@app.errorhandler(413)
def file_too_large(error):
    flash("Image is too large. Maximum file size is 5 MB.", "error")
    return redirect(url_for("submit"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
