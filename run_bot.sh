#!/bin/bash
# Cron wrapper for tqqq-bot. Runs the bot and posts to Discord if it fails in a way
# the bot couldn't report itself (missing .env, broken venv, crash before startup).
#
# The bot writes its own log file, so only stderr (tracebacks, shell errors) is appended
# to the log here — normal stdout output is already in it.

BOT_DIR=/root/tqqq_bot
LOG=/var/log/tqqq-bot/bot.log
WEBHOOK_FILE=/etc/tqqq-bot.webhook
EXIT_NOTIFIED=3  # must match EXIT_NOTIFIED in main.py

ERR=$(mktemp)
trap 'rm -f "$ERR"' EXIT

"$BOT_DIR/venv/bin/python3" "$BOT_DIR/main.py" run > /dev/null 2> "$ERR"
STATUS=$?

# Keep stderr in the log; don't let a missing log directory stop the alert below
cat "$ERR" >> "$LOG" 2> /dev/null

if [ "$STATUS" -eq 0 ] || [ "$STATUS" -eq "$EXIT_NOTIFIED" ]; then
    exit "$STATUS"
fi

# Separate copy of the webhook so alerts still work if .env is missing; fall back to .env
WEBHOOK=$(cat "$WEBHOOK_FILE" 2> /dev/null)
if [ -z "$WEBHOOK" ]; then
    WEBHOOK=$(grep -s '^DISCORD_WEBHOOK_URL=' "$BOT_DIR/.env" | cut -d= -f2- | tr -d "\"' \r")
fi
if [ -z "$WEBHOOK" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  run_bot.sh: bot failed (exit $STATUS), no webhook to alert" >> "$LOG" 2> /dev/null
    exit "$STATUS"
fi

# Attach the error output (or the end of the log if there was none) as a text file,
# which avoids having to JSON-escape it
if [ ! -s "$ERR" ]; then
    tail -n 20 "$LOG" > "$ERR" 2> /dev/null
fi
curl -s -o /dev/null --max-time 15 \
    -F "content=**[tqqq-bot] Run FAILED** (exit $STATUS) — see attached output" \
    -F "file=@$ERR;filename=error.txt" \
    "$WEBHOOK"

exit "$STATUS"
