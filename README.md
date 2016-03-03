python-flask-pixel-tracking
===========================

Email pixel tracking using Flask, MongoDB and Celery.

# Setup pip requirements

`pip install -r requirements.txt`

# Launching Flask

`python pfpt/main.py`

# Launching Celery

`celery -A pfpt.main.celery worker --loglevel=INFO --concurrency=1`

# Usage

http://hostname/pixel.gif?action=[open|send]&subect=(subject)&address=(recipient address)