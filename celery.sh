#!/bin/bash
cd /home/emailtracker/web
source bin/activate
cd python-flask-pixel-tracking
celery -A pfpt.main.celery worker --loglevel=INFO --concurrency=1