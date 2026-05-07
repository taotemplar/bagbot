#!/bin/bash

PROJ_DIR="$HOME/git/bagbot"
PID_LOG="/var/tmp/PIDbagbot.log" # store PIDs of running bagbot processes just in case...
APP_LOG="/var/tmp/bagbot.log" # store bagbot output [view: tail -n 50 -f /var/tmp/bagbot.log]
PYTHON_BIN="$PROJ_DIR/.bagbotvirtualenv/bin/python"

function stop_collector {
  # kill running process
  if ps awwjx | grep "[p]ython.*bagbot" >/dev/null 2>&1; then
    echo "shut down" >> "$APP_LOG"
    echo 'Found running proc'
    ps awwjx | grep "[p]ython.*bagbot" | awk '{print $2}' | xargs sudo kill -term
    echo 'killing...'

    # Confirm it was terminated
    i="0"
    while [ $i -lt 20 ]; do
      if ps awwjx | grep "[p]ython.*bagbot" >/dev/null 2>&1; then
        sleep 1
        i=$((i+1))
      else
        echo 'Terminated the old process'
        return 0
      fi
    done
  fi

  # Delete with -9 if it refused to close
  if ps awwjx | grep "[p]ython.*bagbot" >/dev/null 2>&1; then
    echo 'Was not able to kill the bot. Killing with -9'
    ps awwjx | grep "[p]ython.*bagbot" | awk '{print $2}' | xargs sudo kill -9
  else
    echo 'No old proc found or already terminated'
  fi
}

function start_bot {
  # Run in the correct dir
  cd "$PROJ_DIR" || { echo "Directory not found"; exit 1; }

  # Unbuffered output
  nohup "$PYTHON_BIN" -u bagbot.py "$@" >> "$APP_LOG" 2>&1 &
  
  # Store PIDs
  NEW_PID=$! 
  echo "$NEW_PID" >> "$PID_LOG"
  echo "Started bagbot with PID: $NEW_PID"
}

function show_pids {
  if ps awwjx | grep "[p]ython.*bagbot" >/dev/null 2>&1; then
    echo "--- Running Bagbots ---"
    # Print PIDs
    ps awwjx | grep "[p]ython.*bagbot" | awk '{print "PID: "$2}'
    echo "--------------------------------"
    # Print process details
    ps awwjx | grep "[p]ython.*bagbot"
  else
    echo "None running."
  fi
}

if [[ -z $1 ]]; then
  echo "use: ./runBagbot.sh {start|stop|show} [optional_arguments...]"
  exit 1
fi

COMMAND=$1
shift # Removes 'on'/'off'/'show' so "$@" only has the bot args (like --nocheck)

case "$COMMAND" in
  start)
    stop_collector
    start_bot "$@"
    ;;
  stop)
    stop_collector
    ;;
  show)
    show_pids
    ;;
  *)
    echo "unknown cmd: $COMMAND"
    echo "use: ./runBagbot.sh {start|stop|show} [--nocheck]"
    exit 1
    ;;
esac