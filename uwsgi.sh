#!/bin/bash
cd /home/emailtracker/web
source bin/activate
cd python-flask-pixel-tracking
uwsgi -s /tmp/uwsgi.sock -w pfpt.main:app --chmod-socket=666