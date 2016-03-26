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

GET http://hostname/api/generate-pixel?to=[]&from=[]&subject=[]

this will return an id that you pass to:

http://hostname/pixel.gif?sh=(id)

which should be embedded as an image in your email