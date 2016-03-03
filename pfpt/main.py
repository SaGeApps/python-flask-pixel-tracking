from celery import Celery
from flask import Flask, request, Response, render_template
from pymongo import MongoClient

import base64
import copy
import hashlib
import json
import time

debug = True

app = Flask(__name__)

app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
app.config['MONGO_SERVER'] = 'localhost'
app.config['MONGO_DB'] = 'flask-pixel-tracker'

mongo_client = MongoClient(app.config['MONGO_SERVER'], 27017, connect=False)
mongo_db = mongo_client[app.config['MONGO_DB']]

celery = Celery('pfpt.main', broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)


@celery.task
def consume_event(event_record):
    event_action = event_record['data']['action'] if 'action' in event_record['data'] else 'open'

    event_collection = mongo_db['event-collection']
    event_id = event_collection.insert_one(event_record)

    subject = event_record['data']['subject'] if 'subject' in event_record['data'] else ''
    address = event_record['data']['address'] if 'address' in event_record['data'] else ''

    subject_collection = mongo_db['subject-collection']
    open_collection = mongo_db['opens-collection']

    subject_hash = hashlib.sha1(subject).hexdigest()
    open_hash = hashlib.sha1('{}:{}'.format(subject, address)).hexdigest()

    if event_action == 'open':
        open_result = open_collection.update_one({'open_hash': open_hash}, {'$inc': {'opens': 1}}, True)

        if open_collection.find_one({'open_hash': open_hash})['opens'] == 1:
            subject_collection.update_one({'subject_hash': subject_hash}, {'$inc': {'opens': 1}}, True)

    if event_action == 'send':
        if subject_collection.find_one({'subject_hash': subject_hash}) is None:
            subject_collection.insert_one({
                'subject_hash': subject_hash,
                'subject': subject,
                'opens': 0,
                'sends': 1,
                'date_sent': int(time.time()),
            })
        else:
            subject_collection.update_one({
                'subject_hash': subject_hash
            }, {
                '$inc': {'sends': 1}
            }, True)

        if open_collection.find_one({'open_hash': open_hash}) is None:
            open_collection.insert_one({
                'open_hash': open_hash,
                'subject_hash': subject_hash,
                'subject': subject,
                'opens': 0,
                'sends': 1,
                'date_sent': int(time.time()),
            })
        else:
            open_collection.update_one({
                'open_hash': open_hash
            }, {
                '$inc': {'sends': 1}
            }, True)

    return


@app.route("/pixel.gif")
def pixel():
    pixel_data = base64.b64decode("R0lGODlhAQABAIAAAP8AAP8AACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==")
    event_record = {
        'time': int(time.time()),
        'data': {},
        'headers': {},
    }

    event_record['data'] = copy.deepcopy(request.args)

    for header in request.headers:
        event_record['headers'][header[0]] = request.headers.get(header[0])

    consume_event.delay(event_record)

    return Response(pixel_data, mimetype="image/gif")


@app.route("/log")
def log():
    return render_template('log.html')


@app.route("/json/emails")
def emails():
    subject_collection = mongo_db['subject-collection']

    output = []

    for subject in subject_collection.find({}, {'_id': False}):
        subject['open_percent'] = (float(subject['opens']) / float(subject['sends'])) * 100.

        output.append(subject)

    return Response(json.dumps(output), mimetype="application/json")


@app.route("/json/email/<subject_hash>")
def email(subject_hash):
    subject_collection = mongo_db['subject-collection']
    open_collection = mongo_db['opens-collection']

    output = {}

    email = subject_collection.find_one({'subject_hash': subject_hash}, {'_id': False})
    opens = open_collection.find({'subject_hash': subject_hash}, {'_id': False})

    output['email'] = email
    output['opens'] = []

    for openevt in opens:
        output['opens'].append(openevt)

    return Response(json.dumps(output), mimetype="application/json")

if __name__ == "__main__":
    app.run(debug=debug)
