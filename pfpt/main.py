from celery import Celery
from flask import Flask, make_response, redirect, request, Response, render_template
from functools import wraps
from pymongo import MongoClient

import argparse
import base64
import copy
import getpass
import hashlib
import json
import os
import random
import string
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

    email = subject_collection.find_one({'subject_hash': subject_hash}, {'_id': False})
    opens = open_collection.find({'subject_hash': subject_hash}, {'_id': False})

    output = {}
    output['email'] = email
    output['opens'] = []

    for openevt in opens:
        output['opens'].append(openevt)

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
        resp.set_cookie('token', token)

        return resp

    return render_template('login.html')


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

    parser.add_argument('command', nargs=1, choices=('run', 'create-user', ))
    args = parser.parse_args()

    if 'run' in args.command:
        app.run(debug=debug)
    elif 'create-admin-user' in args.command:
        username = raw_input("Username: ")
        password = getpass.getpass("Password: ")

        create_user(username, password)

        print('User {} has been created.'.format(username))
