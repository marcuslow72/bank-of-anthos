'''
Copyright 2018 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

import datetime
import json
import logging
import os

from flask import Flask, abort, jsonify, make_response, redirect, \
    render_template, request, url_for

import jwt

import requests


app = Flask(__name__)
# TODO: clean naming?
app.config["TRANSACTIONS_URI"] = 'http://{}/new_transaction'.format(
    os.environ.get('TRANSACTIONS_API_ADDR'))
app.config["BALANCES_URI"] = 'http://{}/get_balance'.format(
    os.environ.get('BALANCES_API_ADDR'))
app.config["HISTORY_URI"] = 'http://{}/get_history'.format(
    os.environ.get('HISTORY_API_ADDR'))
app.config["TOKEN_CREATOR_URI"] = 'http://{}/get_token'.format(
    os.environ.get('TOKEN_CREATOR_API_ADDR'))
app.config["INTERNAL_CONTACTS_URI"] = 'http://{}/contacts'.format(
    os.environ.get('CONTACTS_API_ADDR'))
app.config["EXTERNAL_ACCOUNTS_URI"] = 'http://{}/external'.format(
    os.environ.get('CONTACTS_API_ADDR'))


TOKEN_NAME = 'token'

local_routing_num = os.getenv('LOCAL_ROUTING_NUM')


# handle requests to the server
@app.route("/home")
def main():
    # TODO: properly handle erros from other services
    token = request.cookies.get(TOKEN_NAME)
    if not verify_token(token):
        # user isn't authenticated
        return redirect(url_for('login_page'))

    display_name = jwt.decode(token, verify=False)['name']

    hed = {'Authorization': 'Bearer ' + token}
    # get balance
    balance = None
    try:
        req = requests.get(url=app.config["BALANCES_URI"], headers=hed)
        balance = req.json()['balance']
    except requests.exceptions.RequestException as e:
        logging.error(str(e))
    # get history
    transaction_list = []
    try:
        req = requests.get(url=app.config["HISTORY_URI"], headers=hed)
        transaction_list = req.json()['history']
    except requests.exceptions.RequestException as e:
        logging.error(str(e))
    # get contacts
    internal_list = []
    try:
        req = requests.get(url=app.config["INTERNAL_CONTACTS_URI"], headers=hed)
        internal_list = req.json()['account_list']
    except requests.exceptions.RequestException as e:
        logging.error(str(e))
    # get external accounts
    external_list = []
    try:
        req = requests.get(url=app.config["EXTERNAL_ACCOUNTS_URI"], headers=hed)
        external_list = req.json()['account_list']
    except requests.exceptions.RequestException as e:
        logging.error(str(e))
    return render_template('index.html',
                           history=transaction_list,
                           balance=balance,
                           name=display_name,
                           external_accounts=external_list,
                           favorite_accounts=internal_list)


@app.route('/payment', methods=['POST'])
def payment():
    token = request.cookies.get(TOKEN_NAME)
    if not verify_token(token):
        # user isn't authenticated
        return abort(401)

    account_id = jwt.decode(token, verify=False)['acct']
    recipient = request.form['recipient']
    if recipient == 'other':
        recipient = request.form['other-recipient']
    # convert amount to integer
    amount = int(float(request.form['amount']) * 100)
    # verify balance is sufficient
    hed = {'Authorization': 'Bearer ' + token}
    req = requests.get(url=app.config["BALANCES_URI"], headers=hed)
    balance = req.json()['balance']
    if balance > amount:
        transaction_obj = {'from_routing_num':  local_routing_num,
                           'from_account_num': account_id,
                           'to_routing_num': local_routing_num,
                           'to_account_num': recipient,
                           'amount': amount}
        hed = {'Authorization': 'Bearer ' + token,
               'content-type': 'application/json'}
        requests.post(url=app.config["TRANSACTIONS_URI"],
                      data=jsonify(transaction_obj).data,
                      headers=hed,
                      timeout=3)
    return redirect(url_for('main'))


@app.route('/deposit', methods=['POST'])
def deposit():
    token = request.cookies.get(TOKEN_NAME)
    if not verify_token(token):
        # user isn't authenticated
        return abort(401)

    # get account id from token
    account_id = jwt.decode(token, verify=False)['acct']

    # get data from form
    account_details = json.loads(request.form['account'])
    external_account_num = account_details['account_num']
    external_routing_num = account_details['routing_num']
    # convert amount to integer
    amount = int(float(request.form['amount']) * 100)

    # simulate transaction from external bank into user's account
    transaction_obj = {'from_routing_num':  external_routing_num,
                       'from_account_num': external_account_num,
                       'to_routing_num': local_routing_num,
                       'to_account_num': account_id,
                       'amount': amount}
    hed = {'Authorization': 'Bearer ' + token,
           'content-type': 'application/json'}
    requests.post(url=app.config["TRANSACTIONS_URI"],
                  data=jsonify(transaction_obj).data,
                  headers=hed,
                  timeout=3)
    return redirect(url_for('main'))


@app.route("/", methods=['GET'])
def login_page():
    token = request.cookies.get(TOKEN_NAME)
    if verify_token(token):
        # already authenticated
        return redirect(url_for('main'))

    return render_template('login.html')


@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    req = requests.get(url=app.config["TOKEN_CREATOR_URI"],
                       params={'username': username, 'password': password})
    resp = make_response(redirect(url_for('main')))
    if req.status_code == 200:
        # login success
        token = req.json()['token']
        claims = jwt.decode(token, verify=False)
        max_age = claims['exp'] - claims['iat']
        resp.set_cookie(TOKEN_NAME, token, max_age=max_age)
    return resp


@app.route('/logout', methods=['POST'])
def logout():
    resp = make_response(redirect(url_for('login_page')))
    resp.delete_cookie(TOKEN_NAME)
    return resp


def verify_token(token):
    if token is None:
        return False
    try:
        jwt.decode(token, key=_public_key,  algorithms='RS256', verify=True)
        return True
    except jwt.exceptions.InvalidTokenError as e:
        logging.error(e)
        return False


def format_timestamp(timestamp):
    """ Format the input timestamp in a human readable way """
    # TODO: time zones?
    date = datetime.datetime.fromtimestamp(float(timestamp))
    return date.strftime('%b %d, %Y')


def format_currency(int_amount):
    """ Format the input currency in a human readable way """
    if int_amount is None:
        return '$---'
    amount_str = '${:0,.2f}'.format(abs(float(int_amount)/100))
    if int_amount < 0:
        amount_str = '-' + amount_str
    return amount_str


if __name__ == '__main__':
    for v in ['PORT', 'TRANSACTIONS_API_ADDR', 'BALANCES_API_ADDR',
              'LOCAL_ROUTING_NUM', 'TOKEN_CREATOR_API_ADDR', 'PUB_KEY_PATH',
              'CONTACTS_API_ADDR']:
        if os.environ.get(v) is None:
            print("error: {} environment variable not set".format(v))
            exit(1)
    _public_key = open(os.environ.get('PUB_KEY_PATH'), 'r').read()

    logging.basicConfig(level=logging.INFO,
                        format=('%(levelname)s|%(asctime)s'
                                '|%(pathname)s|%(lineno)d| %(message)s'),
                        datefmt='%Y-%m-%dT%H:%M:%S',
                        )
    logging.getLogger().setLevel(logging.INFO)

    # register format_duration for use in html template
    app.jinja_env.globals.update(format_timestamp=format_timestamp)
    app.jinja_env.globals.update(format_currency=format_currency)

    logging.info("Starting flask.")
    app.run(debug=False, port=os.environ.get('PORT'), host='0.0.0.0')
