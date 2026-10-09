#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -f "venv/bin/activate" ]; then
  echo "Creando entorno virtual..."
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
else
  source venv/bin/activate
fi

echo "" | python3 app.py
