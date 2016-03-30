from celery import Celery
from flask import Flask, make_response, redirect, request, Response, render_template
from functools import wraps

import argparse
import base64
import copy
import datetime
import getpass
import hashlib
import json
import os
import pymongo
import random
import string
import time

debug = True

app = Flask(__name__)
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
app.config['MONGO_SERVER'] = 'localhost'
app.config['MONGO_DB'] = 'flask-pixel-tracker'

mongo_client = pymongo.MongoClient(app.config['MONGO_SERVER'], 27017, connect=False)
mongo_db = mongo_client[app.config['MONGO_DB']]

celery = Celery('pfpt.main', broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)


@celery.task
def consume_open(event_record):
    send_hash = event_record['data']['sh'] if 'sh' in event_record['data'] else None

    event_collection = mongo_db['event-collection']
    event_id = event_collection.insert_one(event_record)

    sent_collection = mongo_db['sent-collection']
    subject_collection = mongo_db['subject-collection']
    open_collection = mongo_db['opens-collection']

    sent_collection.update_one({'send_hash': send_hash}, {'$inc': {'opens': 1}}, True)

    sent_email = sent_collection.find_one({'send_hash': send_hash})

    subject_hash = sent_email['subject_hash']
    open_hash = sent_email['open_hash']

    open_result = open_collection.update_one({'open_hash': open_hash}, {'$inc': {'opens': 1}}, True)

    if open_collection.find_one({'open_hash': open_hash})['opens'] == 1:
        subject_collection.update_one({'subject_hash': subject_hash}, {'$inc': {'opens': 1}}, True)


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

    consume_open.delay(event_record)

    return Response(pixel_data, mimetype="image/gif")


@app.route("/api/generate-pixel")
def generate_pixel():
    event_record = {
        'to_address': request.args.get('to', None),
        'from_address': request.args.get('from', None),
        'subject': request.args.get('subject', None),
        'sent_date': int(time.time()),
        'opens': 0,
    }

    send_hash = hashlib.sha1('{}'.format(event_record)).hexdigest()
    subject_hash = hashlib.sha1(event_record['subject']).hexdigest()
    open_hash = hashlib.sha1('{}:{}'.format(event_record['subject'],
        event_record['to_address'])).hexdigest()

    event_record['send_hash'] = send_hash
    event_record['subject_hash'] = subject_hash
    event_record['open_hash'] = open_hash

    sent_collection = mongo_db['sent-collection']
    sent_collection.insert_one(event_record)

    subject_collection = mongo_db['subject-collection']
    open_collection = mongo_db['opens-collection']

    if subject_collection.find_one({'subject_hash': subject_hash}) is None:
        subject_collection.insert_one({
            'subject_hash': subject_hash,
            'subject': event_record['subject'],
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
            'subject': event_record['subject'],
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

    return Response(json.dumps({'id': send_hash}), mimetype="application/json")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('token', None)

        if not token:
            return redirect('/auth/login', 302)

        user_collection = mongo_db['auth-users']

        user = user_collection.find_one({'token': token})

        if user is None:
            return redirect('/auth/login', 302)

        return f(*args, **kwargs)

    return decorated_function


@app.route("/emails")
@login_required
def emails():
    subject_collection = mongo_db['subject-collection']

    output = []

    for subject in subject_collection.find({}, {'_id': False}):
        subject['open_percent'] = (float(subject['opens']) / float(subject['sends'])) * 100.

        output.append(subject)

    return render_template('emails.html', emails=output)


@app.route("/email/<subject_hash>")
@login_required
def email(subject_hash):
    subject_collection = mongo_db['subject-collection']
    open_collection = mongo_db['opens-collection']
    sent_collection = mongo_db['sent-collection']

    email = subject_collection.find_one({'subject_hash': subject_hash}, {'_id': False})
    sends = sent_collection.find({'subject_hash': subject_hash}, {'_id': False}).sort('sent_date', pymongo.DESCENDING)

    output = {}
    output['email'] = email
    output['sends'] = []

    for e in sends:
        output['sends'].append(e)

    return render_template('email.html', email=output)


@app.route("/login")
def login():
    return redirect('/auth/login', 302)


@app.route("/auth/login", methods=['GET', 'POST'])
def auth_login():
    if request.method == 'GET':
        return render_template('login.html')

    username = request.form.get('username', '')
    password = request.form.get('password', '')

    user = get_user(username)

    if user and check_password(password, user['password']):
        token = hashlib.sha512(''.join([random.SystemRandom().choice(string.ascii_letters) for _ in xrange(1024)])).hexdigest()

        user_collection = mongo_db['auth-users']

        user_collection.update_one({
            'username': username
        }, {
            '$set': {
                'token': token,
            }
        })

        resp = make_response(redirect('/emails', 302))
        resp.set_cookie('token', token, 3600 * 24 * 30)

        return resp

    return render_template('login.html')


@app.template_filter('epoch_to_date')
def epoch_to_date(value):
    dt = datetime.datetime.fromtimestamp(value)
    return dt.strftime('%Y-%m-%d %H:%M')


def set_password(raw_password):
    algo = 'sha512'

    salt = os.urandom(128)
    encoded_salt = base64.b64encode(salt)

    hsh = hashlib.sha512('{}{}'.format(salt, raw_password)).hexdigest()

    return '{}:{}:{}'.format(algo, encoded_salt, hsh)


def check_password(raw_password, enc_password):
    algo, encoded_salt, hsh = enc_password.split(':')
    salt = base64.b64decode(encoded_salt)
    return hsh == hashlib.sha512('{}{}'.format(salt, raw_password)).hexdigest()


def get_user(username):
    user_collection = mongo_db['auth-users']

    return user_collection.find_one({'username': username})


def create_user(username, password):
    user_collection = mongo_db['auth-users']

    return user_collection.update_one({
            'username': username
        }, {
            '$set': {
                'password': set_password(password),
                'token': None,
            }
        }, True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Python & Flask implementation of pixel tracking')

    parser.add_argument('command', nargs=1, choices=('run', 'create-admin-user', ))
    args = parser.parse_args()

    if 'run' in args.command:
        app.run(debug=debug)
    elif 'create-admin-user' in args.command:
        username = raw_input("Username: ")
        password = getpass.getpass("Password: ")

        create_user(username, password)

        print('User {} has been created.'.format(username))
