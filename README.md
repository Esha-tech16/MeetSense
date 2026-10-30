# MeetSense

MeetSense is a local meeting-management website built with Flask, Python, HTML, CSS, JavaScript, and PostgreSQL. This project includes account registration/login, teams and team members, meeting audio uploads and history, task creation/assignment/status tracking, and a dashboard. Audio transcription uses local Whisper; meeting summaries, decisions, and action items use the hosted Groq API. No local LLM is required.

> **Important limitation:** No application code can make PostgreSQL accept a password that the selected PostgreSQL server rejects. This version checks the common local ports `5433` and `5432`, reports which one accepts the credentials, and verifies that the existing MeetSense database tables are present before it chooses a server. It stops rather than silently writing to a different/empty database.

> **Current feature limitations:** Speaker diarization, Google Calendar sync, password-reset email, CSRF protection, background processing, and formal database migrations are not implemented. AI features require separate setup. The website can be started without AI, but processing audio needs the optional AI components.

## Before you start

You need:

- Windows 10 or 11
- Python 3.11 or 3.12
- PostgreSQL running locally
- The existing database `meetsense_db`
- Your PostgreSQL username and password

**Database safety:** MeetSense does not drop your database or delete your existing tables. It creates only its own tables with the `ms_` prefix (`ms_users`, `ms_teams`, `ms_team_members`, `ms_meetings`, and `ms_tasks`). It does not modify the nine existing tables you created earlier (`users`, `teams`, `team_members`, `meetings`, `transcripts`, `speakers`, `transcript_segments`, `action_items`, `calendar_events`). The app currently uses its own `ms_` tables; mapping the old tables into the app is a separate schema-integration task.

## 1. Open the project folder

1. Download and extract the MeetSense ZIP.
2. Open the extracted `MeetSense` folder.
3. Click the folder address bar, type `cmd`, and press Enter.

## 2. Create a Python environment and install packages

Run these commands one at a time in Command Prompt:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `py -3.12` is not recognized but Python is installed, try:

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configure `.env`

Create your local environment file:

```bat
copy .env.example .env
```

If `.env` already exists, do not overwrite it unless you want to replace its settings. Open it with:

```bat
notepad .env
```

Set the values as shown below, replacing the password with the password for the PostgreSQL instance that contains your existing `meetsense_db` database and tables:

```dotenv
SECRET_KEY=replace-with-a-long-random-secret
DB_PASSWORD=your_actual_postgresql_password
DB_USER=postgres
DB_HOST=localhost
DB_PORT=auto
DB_NAME=meetsense_db
PORT=5000
OPEN_BROWSER=true
MAX_UPLOAD_MB=200
WHISPER_MODEL=base
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-20b
```

Use your real password instead of `your_actual_postgresql_password`. Do not add angle brackets, and do not share `.env`. If your PostgreSQL username is not `postgres`, update `DB_USER`.

`DB_PORT=auto` checks ports `5433` and `5432`. It prefers the PostgreSQL instance that contains the existing tables listed above. You can set `DB_PORT=5433` or `DB_PORT=5432` to put a port first; the app still checks the other common port, but will only use an instance where the credentials work and the existing schema can be identified.

## 4. Run MeetSense

Make sure Command Prompt shows `(.venv)` at the beginning of the line, then run:

```bat
python app.py
```

If the database connection is successful, the terminal will print the selected PostgreSQL port and start the web server. Open this address if your browser does not open automatically:

`http://127.0.0.1:5000`

Keep the Command Prompt window open while using the website. To stop the server, press `Ctrl+C` in that window.

## 5. Check the connection

With the website running, open:

`http://127.0.0.1:5000/health`

A working connection should return:

```json
{"status":"ok","database":"connected"}
```

## 6. First website test

1. Register an account using an email and a password of at least eight characters.
2. MeetSense creates a first team for that account.
3. Open Teams to create more teams or add an already-registered user by email.
4. Open Tasks to create a task, assign it to a member of the selected team, and update its status.
5. Open Meetings and upload a supported audio file.
6. Open the meeting page. Audio processing requires the optional AI setup below.

## 7. Optional AI setup

The website and account/team/task features can be tested without AI.

### Audio transcription

Activate `.venv`, then run:

```bat
pip install -r requirements-ai.txt
```

The first transcription attempt may download the Whisper model. The default `base` model is a reasonable starting point for an Intel i3 computer with 8 GB RAM, but processing can be slow for long recordings.

### Summaries, decisions, and action items (cloud; no local LLM)

1. Create an API key in the [Groq Console](https://console.groq.com/).
2. Open your private `.env` file and set `GROQ_API_KEY` to that key. Never paste the key into chat or commit it to Git.
3. Keep `GROQ_MODEL=openai/gpt-oss-20b`, unless you choose another currently supported model from Groq's model list.
4. Restart MeetSense and process the meeting again.

Install the AI requirements, which include the Groq Python client and local Whisper transcription:

```bat
pip install -r requirements-ai.txt
```

The transcript is sent to Groq for summarization, so do not process confidential meeting content unless you are comfortable with the provider's data handling terms. If Groq is unavailable or the key/model is invalid, MeetSense reports an error instead of inventing a summary.

### Speaker diarization and calendar

Speaker diarization and Google Calendar synchronization are not implemented in this starter version.

## Troubleshooting

### “PostgreSQL password is not configured”

Open `.env` (not `.env.example`) and set `DB_PASSWORD` to the password for the intended PostgreSQL server. Save the file and restart `python app.py`.

### “Password authentication failed”

This means the server on that port rejected the password. If `psql -U postgres` works but `psql -U postgres -h localhost -p 5433 -d meetsense_db` fails, the two commands may be reaching different PostgreSQL instances (often ports 5432 and 5433). A password is specific to a PostgreSQL server/account; it is not necessarily the same across two installed instances. Connect through pgAdmin to the server that contains `meetsense_db` and confirm its port and credentials. Do not change authentication settings or reset a password until you have identified the intended server.

### “Could not confidently identify the existing database schema”

The credentials worked on a PostgreSQL server, but the expected existing tables were not found there. The app stops to avoid creating its `ms_` tables in the wrong database. Verify that `meetsense_db` and your nine tables are on the selected port. If the tables are in a different schema instead of `public`, the schema check must be adjusted after confirming the schema name.

### “Connection refused” or no PostgreSQL ports respond

Confirm the PostgreSQL service is running and that the server is listening on port `5432` or `5433`. Confirm `DB_HOST` and `DB_NAME` in `.env`.

### `psql` reports “SCRAM authentication requires libpq version 10 or above”

That is a client-version issue, not a MeetSense code issue. Use the newer `psql.exe` from the matching PostgreSQL installation, for example `C:\Program Files\PostgreSQL\17\bin\psql.exe` if version 17 is installed.

### “No module named …” or a `psycopg` error

Activate `.venv` and run:

```bat
pip install -r requirements.txt
```

### Browser did not open

Open `http://127.0.0.1:5000` manually and check the terminal for startup errors.

### Port 5000 is already in use

Change `PORT=5000` in `.env` to `PORT=5001`, save the file, restart the app, and open `http://127.0.0.1:5001`.

### AI processing does not work

Install `requirements-ai.txt` for transcription and the Groq client, set `GROQ_API_KEY` in `.env`, and check the terminal for the exact error.

## Security and data notes

- Passwords are stored as hashes, not plain text.
- The app checks team membership before displaying team meetings and tasks.
- Keep `.env` private. Do not publish your PostgreSQL password or secret key.
- This app is intended for local academic demonstration, not public internet deployment.
- `db.create_all()` creates missing `ms_` tables; it is not a migration system and does not alter existing table definitions.


## Run MeetSense on Windows

From the project folder, open Command Prompt or PowerShell and run:

```powershell
.venv\Scripts\activate
python app.py
```

If the virtual environment has not been created yet, create it and install the packages once:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-ai.txt
```

### Password reset email (optional)

Forgot-password reset links are sent by email when SMTP settings are configured in `.env`:
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `MAIL_FROM`.
For a local setup without SMTP, MeetSense prints the one-time reset link in the terminal.
Reset links expire after 30 minutes.


Note: the distributed ZIP includes an empty `uploads` folder. Previously uploaded local audio recordings are not included; upload recordings again from the MeetSense interface after extracting the project.
