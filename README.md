# Meeting Room Booking System

A professional internal web application for local company employees to reserve meeting rooms.

## Features

- Dashboard listing all rooms and real-time availability indicators.
- Calendar-style schedule list for active bookings.
- Create booking with room, date, start/end time, title, organizer name/email.
- Double-booking prevention for overlapping schedules in the same room.
- Edit and cancel bookings.
- Booking history with status tracking (active/cancelled).
- Admin room management (add room, enable/disable room).
- Admin booking deletion.
- Email notification on booking confirmation (SMTP-configurable).
- Reminder emails for meetings starting in next 30 minutes.
- Export booking report to Excel (.xlsx).

## Default Rooms

1. Room1: Big Meeting Room
2. Room2: Meeting Room Floor Design
3. Room3: Meeting Room Floor Account
4. Room4: Meeting Room Floor 3

## Project Structure

```text
Booking-Meeting-Room/
├── app.py
├── requirements.txt
├── README.md
├── instance/
│   └── booking.db              # auto-created at first run
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── booking_form.html
│   ├── calendar.html
│   ├── history.html
│   └── admin_rooms.html
└── static/
    ├── css/styles.css
    └── js/app.js
```

## Setup Instructions (Local Server)

### 1) Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Configure environment variables (optional for email)

```bash
export SECRET_KEY='replace-with-secure-value'
export SMTP_HOST='smtp.yourcompany.com'
export SMTP_PORT='587'
export SMTP_USER='booking-bot@yourcompany.com'
export SMTP_PASSWORD='your-password'
export SMTP_FROM='booking-bot@yourcompany.com'
```

If SMTP variables are not set, the app still runs but skips sending emails.

### 3) Run the app

```bash
python app.py
```

Open in browser: `http://localhost:5000`

## Usage Notes

- **Book Room:** Go to **New Booking** and fill booking details.
- **Prevent conflicts:** The app blocks overlapping bookings for the same room/time.
- **Edit/Cancel:** Use actions in Dashboard.
- **Admin Rooms:** Manage room list/status from **Admin Rooms**.
- **Send reminders:** On Dashboard, click **Send 30-min Reminders**.
- **Export report:** Click **Export Excel**.

## Database

- SQLite database file is created automatically at `instance/booking.db`.
- Tables: `rooms`, `bookings`.

## Deployment Suggestions

For a local company server deployment:

- Run behind Gunicorn + Nginx or IIS reverse proxy.
- Store `SECRET_KEY` and SMTP credentials in environment variables.
- Set up cron/task scheduler to call `/admin/reminders/send` every 5-10 minutes (authenticated in production).
- Add login/authentication for production use.

