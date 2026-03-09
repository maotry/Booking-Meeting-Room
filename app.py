import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
import smtplib
from io import BytesIO

from flask import Flask, flash, g, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "instance", "booking.db")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-key"),
    SMTP_HOST=os.environ.get("SMTP_HOST", ""),
    SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
    SMTP_USER=os.environ.get("SMTP_USER", ""),
    SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
    SMTP_FROM=os.environ.get("SMTP_FROM", "noreply@company.local"),
)

DEFAULT_ROOMS = [
    ("Room1", "Big Meeting Room"),
    ("Room2", "Meeting Room Floor Design"),
    ("Room3", "Meeting Room Floor Account"),
    ("Room4", "Meeting Room Floor 3"),
]


@dataclass
class Booking:
    id: int
    room_id: int
    room_code: str
    room_name: str
    meeting_title: str
    organizer_name: str
    organizer_email: str
    meeting_date: str
    start_time: str
    end_time: str
    status: str
    created_at: str


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)
    schema = """
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL,
        meeting_title TEXT NOT NULL,
        organizer_name TEXT NOT NULL,
        organizer_email TEXT NOT NULL,
        meeting_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        reminder_sent INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(room_id) REFERENCES rooms(id)
    );
    """
    with closing(sqlite3.connect(DATABASE)) as db:
        db.executescript(schema)
        for code, name in DEFAULT_ROOMS:
            db.execute(
                "INSERT OR IGNORE INTO rooms(code, name, active) VALUES (?, ?, 1)",
                (code, name),
            )
        db.commit()


def send_email(to_address: str, subject: str, body: str) -> bool:
    if not app.config["SMTP_HOST"]:
        app.logger.info("SMTP not configured. Skipping email to %s with subject %s", to_address, subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = app.config["SMTP_FROM"]
    msg["To"] = to_address
    msg.set_content(body)

    with smtplib.SMTP(app.config["SMTP_HOST"], app.config["SMTP_PORT"], timeout=10) as smtp:
        smtp.starttls()
        if app.config["SMTP_USER"]:
            smtp.login(app.config["SMTP_USER"], app.config["SMTP_PASSWORD"])
        smtp.send_message(msg)

    return True


def get_rooms(include_inactive: bool = False):
    db = get_db()
    query = "SELECT * FROM rooms"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY code"
    return db.execute(query).fetchall()


def booking_conflict(room_id: int, meeting_date: str, start_time: str, end_time: str, booking_id: int | None = None) -> bool:
    db = get_db()
    params = [room_id, meeting_date, end_time, start_time]
    query = """
    SELECT 1
    FROM bookings
    WHERE room_id = ?
      AND meeting_date = ?
      AND status = 'active'
      AND start_time < ?
      AND end_time > ?
    """
    if booking_id is not None:
        query += " AND id != ?"
        params.append(booking_id)

    return db.execute(query, params).fetchone() is not None


def parse_datetime(date_text: str, time_text: str) -> datetime:
    return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")


def fetch_bookings(status: str | None = None):
    db = get_db()
    query = """
    SELECT b.*, r.code AS room_code, r.name AS room_name
    FROM bookings b
    JOIN rooms r ON r.id = b.room_id
    """
    params = []
    if status:
        query += " WHERE b.status = ?"
        params.append(status)
    query += " ORDER BY b.meeting_date DESC, b.start_time DESC"
    return db.execute(query, params).fetchall()


@app.route("/")
def dashboard():
    rooms = get_rooms()
    bookings = fetch_bookings("active")

    today = datetime.now().strftime("%Y-%m-%d")
    availability = {}
    for room in rooms:
        active_booking = next(
            (
                b
                for b in bookings
                if b["room_id"] == room["id"] and b["meeting_date"] >= today
            ),
            None,
        )
        availability[room["id"]] = "Booked" if active_booking else "Available"

    return render_template("dashboard.html", rooms=rooms, bookings=bookings, availability=availability)


@app.route("/calendar")
def calendar_view():
    bookings = fetch_bookings("active")
    return render_template("calendar.html", bookings=bookings)


@app.route("/bookings/new", methods=["GET", "POST"])
def create_booking():
    rooms = get_rooms()
    if request.method == "POST":
        room_id = int(request.form["room_id"])
        meeting_date = request.form["meeting_date"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]
        meeting_title = request.form["meeting_title"].strip()
        organizer_name = request.form["organizer_name"].strip()
        organizer_email = request.form["organizer_email"].strip()

        if parse_datetime(meeting_date, end_time) <= parse_datetime(meeting_date, start_time):
            flash("End time must be later than start time.", "error")
            return render_template("booking_form.html", rooms=rooms, booking=request.form, mode="create")

        if booking_conflict(room_id, meeting_date, start_time, end_time):
            flash("This room is already booked during the selected time.", "error")
            return render_template("booking_form.html", rooms=rooms, booking=request.form, mode="create")

        db = get_db()
        db.execute(
            """
            INSERT INTO bookings(
                room_id, meeting_title, organizer_name, organizer_email, meeting_date, start_time, end_time, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                room_id,
                meeting_title,
                organizer_name,
                organizer_email,
                meeting_date,
                start_time,
                end_time,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        db.commit()

        send_email(
            organizer_email,
            "Meeting Room Booking Confirmed",
            f"Your booking '{meeting_title}' on {meeting_date} from {start_time} to {end_time} is confirmed.",
        )
        flash("Booking created successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("booking_form.html", rooms=rooms, booking=None, mode="create")


@app.route("/bookings/<int:booking_id>/edit", methods=["GET", "POST"])
def edit_booking(booking_id: int):
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        flash("Booking not found.", "error")
        return redirect(url_for("dashboard"))

    rooms = get_rooms()
    if request.method == "POST":
        room_id = int(request.form["room_id"])
        meeting_date = request.form["meeting_date"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]
        meeting_title = request.form["meeting_title"].strip()
        organizer_name = request.form["organizer_name"].strip()
        organizer_email = request.form["organizer_email"].strip()

        if parse_datetime(meeting_date, end_time) <= parse_datetime(meeting_date, start_time):
            flash("End time must be later than start time.", "error")
            return render_template("booking_form.html", rooms=rooms, booking=request.form, mode="edit")

        if booking_conflict(room_id, meeting_date, start_time, end_time, booking_id=booking_id):
            flash("This room is already booked during the selected time.", "error")
            return render_template("booking_form.html", rooms=rooms, booking=request.form, mode="edit")

        db.execute(
            """
            UPDATE bookings
            SET room_id = ?, meeting_title = ?, organizer_name = ?, organizer_email = ?,
                meeting_date = ?, start_time = ?, end_time = ?
            WHERE id = ?
            """,
            (room_id, meeting_title, organizer_name, organizer_email, meeting_date, start_time, end_time, booking_id),
        )
        db.commit()
        flash("Booking updated successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("booking_form.html", rooms=rooms, booking=booking, mode="edit")


@app.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id: int):
    db = get_db()
    db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
    db.commit()
    flash("Booking cancelled.", "success")
    return redirect(url_for("dashboard"))


@app.route("/history")
def history():
    bookings = fetch_bookings()
    return render_template("history.html", bookings=bookings)


@app.route("/admin/rooms", methods=["GET", "POST"])
def admin_rooms():
    db = get_db()
    if request.method == "POST":
        code = request.form["code"].strip()
        name = request.form["name"].strip()
        db.execute("INSERT INTO rooms(code, name, active) VALUES (?, ?, 1)", (code, name))
        db.commit()
        flash("Room added.", "success")
        return redirect(url_for("admin_rooms"))

    rooms = get_rooms(include_inactive=True)
    return render_template("admin_rooms.html", rooms=rooms)


@app.route("/admin/rooms/<int:room_id>/toggle", methods=["POST"])
def toggle_room(room_id: int):
    db = get_db()
    room = db.execute("SELECT active FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room:
        new_active = 0 if room["active"] else 1
        db.execute("UPDATE rooms SET active = ? WHERE id = ?", (new_active, room_id))
        db.commit()
    return redirect(url_for("admin_rooms"))


@app.route("/admin/bookings/<int:booking_id>/delete", methods=["POST"])
def delete_booking(booking_id: int):
    db = get_db()
    db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    db.commit()
    flash("Booking deleted permanently.", "success")
    return redirect(url_for("history"))


@app.route("/reports/export")
def export_report():
    bookings = fetch_bookings()
    wb = Workbook()
    ws = wb.active
    ws.title = "Bookings"
    ws.append([
        "ID", "Room Code", "Room Name", "Meeting Title", "Organizer", "Email",
        "Date", "Start", "End", "Status", "Created At"
    ])

    for b in bookings:
        ws.append([
            b["id"], b["room_code"], b["room_name"], b["meeting_title"], b["organizer_name"],
            b["organizer_email"], b["meeting_date"], b["start_time"], b["end_time"], b["status"], b["created_at"]
        ])

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    filename = f"booking_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(stream, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/admin/reminders/send", methods=["POST"])
def send_reminders():
    now = datetime.now()
    limit = now + timedelta(minutes=30)
    db = get_db()
    rows = db.execute(
        """
        SELECT b.*, r.name as room_name FROM bookings b
        JOIN rooms r ON r.id = b.room_id
        WHERE b.status = 'active' AND b.reminder_sent = 0
        """
    ).fetchall()

    sent = 0
    for row in rows:
        start_dt = parse_datetime(row["meeting_date"], row["start_time"])
        if now <= start_dt <= limit:
            if send_email(
                row["organizer_email"],
                "Meeting Reminder",
                f"Reminder: '{row['meeting_title']}' starts at {row['start_time']} in {row['room_name']} today.",
            ):
                db.execute("UPDATE bookings SET reminder_sent = 1 WHERE id = ?", (row["id"],))
                sent += 1
    db.commit()
    flash(f"Reminder process completed. Emails sent: {sent}.", "success")
    return redirect(url_for("dashboard"))


@app.before_request
def ensure_initialized():
    init_db()



if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
