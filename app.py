import os, threading, webbrowser, time
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from urllib.parse import urljoin
import smtplib
from email.message import EmailMessage

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"wav", "mp3", "m4a", "mp4", "webm", "ogg", "mpeg", "mpga", "flac"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-this-secret")

# Database configuration. DB_PORT may be a number or "auto". In auto mode,
# MeetSense checks the configured port first, then the common local ports 5433/5432.
# It identifies the intended database by checking for the user's existing tables
# before choosing a server. It never drops or alters those existing tables.
from sqlalchemy.engine import URL
import psycopg
from psycopg import OperationalError as PsycopgOperationalError

DB_USER = os.getenv("DB_USER", "postgres").strip() or "postgres"
DB_HOST = os.getenv("DB_HOST", "localhost").strip() or "localhost"
DB_NAME = os.getenv("DB_NAME", "meetsense_db").strip() or "meetsense_db"
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_PORT_SETTING = os.getenv("DB_PORT", "auto").strip().lower()
EXPECTED_EXISTING_TABLES = {
    "users", "teams", "team_members", "meetings", "transcripts",
    "speakers", "transcript_segments", "action_items", "calendar_events",
}

def _candidate_ports():
    ports = []
    if DB_PORT_SETTING != "auto":
        try:
            configured = int(DB_PORT_SETTING)
            if not 1 <= configured <= 65535:
                raise ValueError
            ports.append(configured)
        except ValueError as exc:
            raise RuntimeError("DB_PORT must be a port number (for example 5432) or 'auto'.") from exc
    # Keep the user's configured port first, but check the other common local
    # PostgreSQL port as well so an old .env setting cannot silently mislead them.
    for port in (5433, 5432):
        if port not in ports:
            ports.append(port)
    return ports


def resolve_database_port():
    """Find the local instance containing the existing MeetSense database schema."""
    if not DB_PASSWORD or DB_PASSWORD == "PASTE_YOUR_POSTGRES_PASSWORD_HERE":
        raise RuntimeError(
            "PostgreSQL password is not configured. Open the local .env file and set DB_PASSWORD."
        )
    attempts = []
    successful = []
    for port in _candidate_ports():
        try:
            with psycopg.connect(
                host=DB_HOST,
                port=port,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=3,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                    )
                    table_names = {row[0] for row in cur.fetchall()}
                matched = len(EXPECTED_EXISTING_TABLES.intersection(table_names))
                successful.append((matched, port, table_names))
                attempts.append(f"port {port}: authentication and database connection succeeded; {matched}/9 expected existing tables found")
        except PsycopgOperationalError as exc:
            message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            attempts.append(f"port {port}: {message}")
        except Exception as exc:
            attempts.append(f"port {port}: {type(exc).__name__}: {exc}")

    # Prefer the instance that clearly contains the schema the user already created.
    matching = [item for item in successful if item[0] >= 5]
    if matching:
        matching.sort(key=lambda item: (item[0], item[1] == (int(DB_PORT_SETTING) if DB_PORT_SETTING.isdigit() else 5433)), reverse=True)
        matched, port, _ = matching[0]
        print(f"[MeetSense] PostgreSQL connected on {DB_HOST}:{port}/{DB_NAME}; found {matched}/9 existing project tables.")
        return port

    if successful:
        details = "\n".join(f"  - {item}" for item in attempts)
        raise RuntimeError(
            "A PostgreSQL server accepted the credentials, but MeetSense could not confidently identify "
            f"the existing database schema '{DB_NAME}'. To avoid writing to the wrong database, startup was stopped.\n"
            "Confirm which port contains your nine existing tables (users, teams, team_members, meetings, "
            "transcripts, speakers, transcript_segments, action_items, calendar_events), then set DB_PORT in .env.\n"
            f"Connection checks:\n{details}"
        )

    details = "\n".join(f"  - {item}" for item in attempts)
    raise RuntimeError(
        f"MeetSense could not authenticate to database '{DB_NAME}' on the checked local PostgreSQL ports.\n"
        "This is usually a password mismatch for the specific PostgreSQL instance, or the database is on a different port. "
        "A password that works on port 5432 may not work on port 5433 if two PostgreSQL instances are installed.\n"
        "Check DB_PASSWORD in .env and confirm the same password connects to the intended server and port.\n"
        f"Connection checks:\n{details}"
    )


# SQLAlchemy creates its engine lazily. We replace this placeholder URI with the
# resolved URI before the first database operation in main().
app.config["SQLALCHEMY_DATABASE_URI"] = URL.create(
    drivername="postgresql+psycopg",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT_SETTING) if DB_PORT_SETTING.isdigit() else 5433,
    database=DB_NAME,
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
db = SQLAlchemy()
login_manager = LoginManager(app)
login_manager.login_view = "login"

team_members = db.Table(
    "ms_team_members",
    db.Column("team_id", db.Integer, db.ForeignKey("ms_teams.id", ondelete="CASCADE"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("ms_users.id", ondelete="CASCADE"), primary_key=True),
)

class User(UserMixin, db.Model):
    __tablename__ = "ms_users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    teams = db.relationship("Team", secondary=team_members, back_populates="members")

class Team(db.Model):
    __tablename__ = "ms_teams"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("ms_users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    members = db.relationship("User", secondary=team_members, back_populates="teams")
    meetings = db.relationship("Meeting", backref="team", cascade="all, delete-orphan")
    tasks = db.relationship("Task", backref="team", cascade="all, delete-orphan")

class Meeting(db.Model):
    __tablename__ = "ms_meetings"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(255))
    audio_path = db.Column(db.String(500))
    status = db.Column(db.String(30), default="uploaded", nullable=False)
    transcript = db.Column(db.Text, default="")
    summary = db.Column(db.Text, default="")
    decisions_json = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("ms_teams.id"), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("ms_users.id"), nullable=False)
    tasks = db.relationship("Task", backref="meeting", cascade="all, delete-orphan")

class Task(db.Model):
    __tablename__ = "ms_tasks"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(240), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="todo", nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey("ms_teams.id"), nullable=False)
    meeting_id = db.Column(db.Integer, db.ForeignKey("ms_meetings.id"), nullable=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("ms_users.id"), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("ms_users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    assignee = db.relationship("User", foreign_keys=[assigned_to_id])

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def user_teams():
    if not current_user.is_authenticated:
        return []
    return sorted(current_user.teams, key=lambda t: t.name.lower())

def can_access_team(team_id):
    return any(t.id == team_id for t in user_teams())

def team_or_404(team_id):
    if not can_access_team(team_id):
        from flask import abort
        abort(404)
    return db.session.get(Team, team_id)

@app.context_processor
def inject_globals():
    return {"nav_teams": user_teams(), "today": date.today()}

@app.route("/")
def index():
    if not current_user.is_authenticated:
        return render_template("landing.html")
    teams = user_teams()
    team_ids = [t.id for t in teams]
    meetings = Meeting.query.filter(Meeting.team_id.in_(team_ids)).order_by(Meeting.created_at.desc()).limit(6).all() if team_ids else []
    tasks = Task.query.filter(Task.team_id.in_(team_ids), Task.status != "done").order_by(Task.due_date.asc().nullslast(), Task.created_at.desc()).limit(6).all() if team_ids else []
    meeting_count = Meeting.query.filter(Meeting.team_id.in_(team_ids)).count() if team_ids else 0
    pending_count = Task.query.filter(Task.team_id.in_(team_ids), Task.status != "done").count() if team_ids else 0
    return render_template("dashboard.html", teams=teams, meetings=meetings, tasks=tasks, meeting_count=meeting_count, pending_count=pending_count)

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name and email, and use a password with at least 8 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "error")
        else:
            user = User(name=name, email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.flush()
            team = Team(name=f"{name}'s team", created_by_id=user.id)
            team.members.append(user)
            db.session.add(team)
            db.session.commit()
            login_user(user)
            flash("Your account and first team are ready.", "success")
            return redirect(url_for("index"))
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=False)
            return redirect(url_for("index"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        # Keep the response identical whether or not the account exists.
        if user:
            serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
            token = serializer.dumps(user.email, salt="meetsense-password-reset")
            reset_url = url_for("reset_password", token=token, _external=True)
            smtp_host = os.getenv("SMTP_HOST", "").strip()
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            smtp_user = os.getenv("SMTP_USER", "").strip()
            smtp_password = os.getenv("SMTP_PASSWORD", "")
            mail_from = os.getenv("MAIL_FROM", smtp_user).strip()
            if smtp_host and mail_from:
                try:
                    message = EmailMessage()
                    message["Subject"] = "Reset your MeetSense password"
                    message["From"] = mail_from
                    message["To"] = user.email
                    message.set_content(
                        f"Hello {user.name},\n\nUse this link to reset your MeetSense password "
                        f"(valid for 30 minutes):\n{reset_url}\n\nIf you did not request this, ignore this email."
                    )
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                        server.starttls()
                        if smtp_user:
                            server.login(smtp_user, smtp_password)
                        server.send_message(message)
                except Exception:
                    app.logger.exception("Could not send password reset email")
            else:
                # Convenient for a local/student deployment without an email provider.
                app.logger.warning("Password reset link for %s: %s", user.email, reset_url)
                print(f"\n[MeetSense] Password reset link (local development): {reset_url}\n")
        flash("If an account exists for that email, password reset instructions have been sent. Check the app terminal if SMTP is not configured.", "success")
        return redirect(url_for("login"))
    return render_template("auth.html", mode="forgot")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    try:
        email = serializer.loads(token, salt="meetsense-password-reset", max_age=1800)
    except SignatureExpired:
        flash("That reset link has expired. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("That reset link is invalid. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash("That account could not be found.", "error")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Use a password with at least 8 characters.", "error")
        elif password != confirm:
            flash("The passwords do not match.", "error")
        else:
            user.password_hash = generate_password_hash(password)
            db.session.commit()
            flash("Your password has been reset. You can now log in.", "success")
            return redirect(url_for("login"))
    return render_template("auth.html", mode="reset")

@app.route("/account", methods=["GET"])
@login_required
def account_page():
    return render_template("account.html")

@app.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    if request.form.get("confirmation", "").strip().lower() != "delete":
        flash('Type "delete" to confirm account deletion.', "error")
        return redirect(url_for("account_page"))
    user = db.session.get(User, current_user.id)
    for task in Task.query.filter_by(assigned_to_id=user.id).all():
        task.assigned_to_id = None
    # Reassign creator references in teams the user belongs to but does not own.
    for meeting in Meeting.query.filter_by(created_by_id=user.id).all():
        team = db.session.get(Team, meeting.team_id)
        replacement = next((member for member in team.members if member.id != user.id), None) if team else None
        if replacement:
            meeting.created_by_id = replacement.id
        elif team and team.created_by_id != user.id:
            meeting.created_by_id = team.created_by_id
    for task in Task.query.filter_by(created_by_id=user.id).all():
        team = db.session.get(Team, task.team_id)
        replacement = next((member for member in team.members if member.id != user.id), None) if team else None
        if replacement:
            task.created_by_id = replacement.id
        elif team and team.created_by_id != user.id:
            task.created_by_id = team.created_by_id
    owned_teams = Team.query.filter_by(created_by_id=user.id).all()
    for team in owned_teams:
        other_members = [member for member in team.members if member.id != user.id]
        if other_members:
            successor = other_members[0]
            team.created_by_id = successor.id
            for meeting in team.meetings:
                if meeting.created_by_id == user.id:
                    meeting.created_by_id = successor.id
            for task in team.tasks:
                if task.created_by_id == user.id:
                    task.created_by_id = successor.id
        else:
            # Remove uploaded recordings along with the team's data.
            for meeting in list(team.meetings):
                if meeting.audio_path:
                    try: Path(meeting.audio_path).unlink(missing_ok=True)
                    except OSError: app.logger.warning("Could not remove meeting audio: %s", meeting.audio_path)
            db.session.delete(team)
    user.teams.clear()
    db.session.delete(user)
    db.session.commit()
    logout_user()
    flash("Your MeetSense account has been deleted.", "success")
    return redirect(url_for("index"))

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.route("/teams", methods=["GET", "POST"])
@login_required
def teams_page():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            team = Team(name=name[:120], created_by_id=current_user.id)
            team.members.append(current_user)
            db.session.add(team)
            db.session.commit()
            flash("Team created.", "success")
            return redirect(url_for("teams_page"))
    return render_template("teams.html", teams=user_teams())

@app.route("/teams/<int:team_id>/members", methods=["POST"])
@login_required
def add_member(team_id):
    team = team_or_404(team_id)
    email = request.form.get("email", "").strip().lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        flash("No account found for that email. Ask them to register first.", "error")
    elif user in team.members:
        flash("That person is already a member.", "error")
    else:
        team.members.append(user)
        db.session.commit()
        flash(f"{user.name} added to {team.name}.", "success")
    return redirect(url_for("teams_page"))

@app.route("/meetings")
@login_required
def meetings_page():
    team_ids = [t.id for t in user_teams()]
    q = Meeting.query.filter(Meeting.team_id.in_(team_ids)) if team_ids else Meeting.query.filter(db.false())
    search = request.args.get("q", "").strip()
    if search:
        q = q.filter(db.or_(Meeting.title.ilike(f"%{search}%"), Meeting.transcript.ilike(f"%{search}%")))
    meetings = q.order_by(Meeting.created_at.desc()).all()
    return render_template("meetings.html", meetings=meetings, search=search)

@app.route("/meetings/new", methods=["GET", "POST"])
@login_required
def new_meeting():
    teams = user_teams()
    if not teams:
        flash("Create a team before uploading a meeting.", "error")
        return redirect(url_for("teams_page"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        team_id = request.form.get("team_id", type=int)
        team = db.session.get(Team, team_id) if team_id else None
        audio = request.files.get("audio")
        if not title or not team or not can_access_team(team.id):
            flash("Enter a title and choose one of your teams.", "error")
        elif not audio or not audio.filename or not allowed_file(audio.filename):
            flash("Choose a supported audio file (WAV, MP3, M4A, MP4, WEBM, OGG or FLAC).", "error")
        else:
            safe = secure_filename(audio.filename)
            unique = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe}"
            path = UPLOAD_DIR / unique
            audio.save(path)
            meeting = Meeting(title=title[:200], original_filename=safe, audio_path=str(path), status="uploaded", team_id=team.id, created_by_id=current_user.id)
            db.session.add(meeting)
            db.session.commit()
            flash("Meeting uploaded. Start processing from its meeting page.", "success")
            return redirect(url_for("meeting_detail", meeting_id=meeting.id))
    return render_template("meeting_new.html", teams=teams)

@app.route("/meetings/<int:meeting_id>")
@login_required
def meeting_detail(meeting_id):
    meeting = db.session.get(Meeting, meeting_id)
    if not meeting or not can_access_team(meeting.team_id):
        from flask import abort
        abort(404)
    team_members_list = meeting.team.members
    try:
        import json
        decisions = json.loads(meeting.decisions_json or "[]")
    except Exception:
        decisions = []
    return render_template("meeting_detail.html", meeting=meeting, decisions=decisions, members=team_members_list)


@app.route("/meetings/<int:meeting_id>/delete", methods=["POST"])
@login_required
def delete_meeting(meeting_id):
    meeting = db.session.get(Meeting, meeting_id)
    if not meeting or not can_access_team(meeting.team_id):
        from flask import abort
        abort(404)
    audio_path = meeting.audio_path
    title = meeting.title
    db.session.delete(meeting)
    db.session.commit()
    if audio_path:
        try:
            Path(audio_path).unlink(missing_ok=True)
        except OSError:
            app.logger.warning("Could not remove deleted meeting audio: %s", audio_path)
    flash(f'"{title}" was deleted.', "success")
    return redirect(url_for("meetings_page"))

@app.route("/meetings/<int:meeting_id>/process", methods=["POST"])
@login_required
def process_meeting(meeting_id):
    meeting = db.session.get(Meeting, meeting_id)
    if not meeting or not can_access_team(meeting.team_id):
        from flask import abort
        abort(404)
    if not meeting.audio_path or not Path(meeting.audio_path).exists():
        flash("The audio file could not be found. Upload it again.", "error")
        return redirect(url_for("meeting_detail", meeting_id=meeting.id))
    meeting.status = "processing"
    db.session.commit()
    try:
        transcript = transcribe_audio(meeting.audio_path)
        summary, decisions, tasks = summarize_meeting(transcript)
        meeting.transcript = transcript
        meeting.summary = summary
        import json
        meeting.decisions_json = json.dumps(decisions)
        meeting.status = "completed"
        for item in tasks:
            db.session.add(Task(title=item[:240], description="Extracted from meeting transcript", status="todo", team_id=meeting.team_id, meeting_id=meeting.id, created_by_id=current_user.id))
        db.session.commit()
        flash("Processing completed.", "success")
    except RuntimeError as exc:
        meeting.status = "needs_configuration"
        db.session.commit()
        flash(str(exc), "error")
    except Exception:
        app.logger.exception("Meeting processing failed")
        meeting.status = "failed"
        db.session.commit()
        flash("Processing failed. Check the terminal output and configuration, then try again.", "error")
    return redirect(url_for("meeting_detail", meeting_id=meeting.id))

def transcribe_audio(audio_path):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Transcription is not configured. Install the optional AI requirements with: pip install -r requirements-ai.txt")
    model_name = os.getenv("WHISPER_MODEL", "base")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not text:
        raise RuntimeError("No speech was detected in this audio file.")
    return text

def summarize_meeting(transcript):
    """Summarize a transcript with a hosted Groq model; no local LLM is required."""
    import json
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Transcription completed, but summarization needs a Groq API key. "
            "Add GROQ_API_KEY to your private .env file and restart MeetSense."
        )

    try:
        from groq import Groq
    except ImportError as exc:
        raise RuntimeError(
            "The Groq client is not installed. Run: pip install -r requirements-ai.txt"
        ) from exc

    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
    prompt = (
        "Analyze the meeting transcript below. Return one JSON object with exactly these keys: "
        "summary (string), decisions (array of strings), and action_items (array of concise task strings). "
        "Use only information stated in the transcript. Do not invent facts, people, decisions, deadlines, "
        "or tasks. Use empty arrays when no clear decisions or action items are present.\n\n"
        "TRANSCRIPT:\n" + transcript[:24000]
    )
    try:
        client = Groq(api_key=api_key, timeout=90.0, max_retries=2)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You extract faithful meeting notes. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_completion_tokens=1800,
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        output = json.loads(content)
        summary = output.get("summary", "")
        decisions = output.get("decisions", [])
        action_items = output.get("action_items", [])
        if not isinstance(summary, str) or not isinstance(decisions, list) or not isinstance(action_items, list):
            raise ValueError("The model returned JSON with unexpected field types.")
        return summary, [str(x) for x in decisions if str(x).strip()], [str(x) for x in action_items if str(x).strip()]
    except Exception as exc:
        app.logger.exception("Groq summarization failed")
        raise RuntimeError(
            "Transcription completed, but Groq could not generate meeting notes. "
            "Check your GROQ_API_KEY, GROQ_MODEL, internet connection, and the terminal error. "
            "No summary was fabricated."
        ) from exc

@app.route("/tasks")
@login_required
def tasks_page():
    team_ids = [t.id for t in user_teams()]
    q = Task.query.filter(Task.team_id.in_(team_ids)) if team_ids else Task.query.filter(db.false())
    status = request.args.get("status", "")
    if status in {"todo", "in_progress", "done"}:
        q = q.filter_by(status=status)
    tasks = q.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc()).all()
    return render_template("tasks.html", tasks=tasks, status=status)

@app.route("/tasks/new", methods=["GET", "POST"])
@login_required
def new_task():
    teams = user_teams()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        team = db.session.get(Team, request.form.get("team_id", type=int))
        assignee_id = request.form.get("assigned_to_id", type=int)
        due = request.form.get("due_date", "").strip()
        if not title or not team or not can_access_team(team.id):
            flash("Enter a task title and choose one of your teams.", "error")
        elif assignee_id and not any(u.id == assignee_id for u in team.members):
            flash("The assignee must belong to the selected team.", "error")
        else:
            task = Task(title=title[:240], description=request.form.get("description", "").strip(), status="todo", team_id=team.id, assigned_to_id=assignee_id or None, created_by_id=current_user.id)
            if due:
                try: task.due_date = date.fromisoformat(due)
                except ValueError: flash("Invalid due date.", "error"); return redirect(url_for("new_task"))
            db.session.add(task)
            db.session.commit()
            flash("Task created.", "success")
            return redirect(url_for("tasks_page"))
    return render_template("task_new.html", teams=teams)

@app.route("/tasks/<int:task_id>/update", methods=["POST"])
@login_required
def update_task(task_id):
    task = db.session.get(Task, task_id)
    if not task or not can_access_team(task.team_id):
        from flask import abort
        abort(404)
    status = request.form.get("status")
    if status in {"todo", "in_progress", "done"}:
        task.status = status
        db.session.commit()
        flash("Task status updated.", "success")
    return redirect(request.referrer or url_for("tasks_page"))

@app.route("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify(status="ok", database="connected")
    except Exception:
        db.session.rollback()
        return jsonify(status="error", database="unavailable"), 503

@app.errorhandler(413)
def too_large(_):
    flash(f"File is too large. Maximum upload size is {MAX_UPLOAD_MB} MB.", "error")
    return redirect(request.referrer or url_for("new_meeting"))

@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404

def initialize_database():
    # Creates only the new ms_* tables; does not drop or alter the user's original nine tables.
    with app.app_context():
        db.create_all()

def open_browser():
    time.sleep(1.2)
    port = int(os.getenv("PORT", "5000"))
    webbrowser.open(f"http://127.0.0.1:{port}")

if __name__ == "__main__":
    try:
        selected_port = resolve_database_port()
        app.config["SQLALCHEMY_DATABASE_URI"] = URL.create(
            drivername="postgresql+psycopg",
            username=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=selected_port,
            database=DB_NAME,
        )
        db.init_app(app)
        initialize_database()
    except Exception as exc:
        print("\n[MeetSense] Startup stopped before changing your existing tables.")
        print(str(exc))
        print("\nNo existing tables were dropped or altered. Fix the indicated database setting and run python app.py again.\n")
        raise SystemExit(1)
    app_port = int(os.getenv("PORT", "5000"))
    if os.getenv("OPEN_BROWSER", "true").lower() == "true":
        threading.Thread(target=open_browser, daemon=True).start()
    print(f"MeetSense is starting at http://127.0.0.1:{app_port} — press Ctrl+C to stop.")
    app.run(host="127.0.0.1", port=app_port, debug=False)
