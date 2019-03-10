import os
import json
import sys
import requests
import socket

from util import *

freebox_config_file = os.path.join(os.path.dirname(__file__), 'freebox.json')
app_id = 'freebox-revolution-munin'  # Script legacy name. Changing this would break authentication
app_name = 'Freebox-OS-munin'
app_version = '1.0.0'
device_name = socket.gethostname()


class Freebox:
    app_token = None
    session_challenge = None
    session_token = None

    @staticmethod
    def get_api_call_uri(endpoint):
        return 'http://mafreebox.freebox.fr/api/v3/' + endpoint

    def save(self):
        with open(freebox_config_file, 'w') as fh:
            json.dump(self.__dict__, fh)

    @staticmethod
    def retrieve():
        freebox = Freebox()
        with open(freebox_config_file, 'r') as fh:
            freebox.__dict__ = json.load(fh)

        return freebox

    def api(self, endpoint, params=None):
        uri = self.get_api_call_uri(endpoint)

        # Build request
        r = requests.get(uri, params=params, headers={
            'X-Fbx-App-Auth': self.session_token
        })
        r_json = r.json()

        if not r_json['success']:
            if r_json['error_code'] == 'auth_required':
                # Open session and try again
                api_open_session(self)
                return self.api(endpoint, params)
            else:
                # Unknown error (http://dev.freebox.fr/sdk/os/login/#authentication-errors)
                message = 'Unknown API error "{}" on URI {} (endpoint {})'.format(
                    r_json['error_code'],
                    uri,
                    endpoint
                )
                try:
                    print('{}: {}'.format(message, r_json['msg']))
                except UnicodeEncodeError:
                    print('{}. Plus, we could not print the error message correctly.'.format(
                        message
                    ))
                sys.exit(1)

        return r_json.get('result', '')

    def api_get_connected_disks(self):
        disks = self.api('storage/disk/')

        # Define a display name for each disk
        for disk in disks:
            name = disk.get('model')

            # Disk does not provide its model, and has exactly one partition:
            if len(name) == 0 and len(disk.get('partitions')) == 1:
                name = disk.get('partitions')[0].get('label')

            # Could not determine name from partition, try to use serial
            if len(name) == 0:
                name = disk.get('serial')

            # In last resort, use disk id
            if len(name) == 0:
                name = disk.get('id')

            slug = slugify(name)
            name += ' ({})'.format(disk.get('type'))

            disk['slug'] = slug
            disk['display_name'] = name

        return disks


def api_authorize():
    print('Authorizing...')
    uri = Freebox.get_api_call_uri('login/authorize/')
    r = requests.post(uri, json={
        'app_id': app_id,
        'app_name': app_name,
        'app_version': app_version,
        'device_name': device_name
    })

    r_json = r.json()

    if not r_json['success']:
        print('Error while authenticating: {}'.format(r_json))
        return 1

    app_token = r_json['result']['app_token']
    track_id = r_json['result']['track_id']

    # Watch for token status
    print('Waiting for you to push the "Yes" button on your Freebox')

    challenge = None
    while True:
        r2 = requests.get(uri + str(track_id))
        r2_json = r2.json()
        status = r2_json['result']['status']

        if status == 'pending':
            sys.stdout.write('.')
            sys.stdout.flush()
        elif status == 'timeout':
            print('\nAuthorization request timeouted. Re-run this script, but please go faster next time')
            return 1
        elif status == 'denied':
            print('\nYou denied authorization request.')
            return 1
        elif status == 'granted':
            challenge = r2_json['result']['challenge']
            break

    freebox = Freebox()
    freebox.app_token = app_token
    freebox.session_challenge = challenge
    freebox.save()

    # That's a success
    print('\nSuccessfully authenticated script. Exiting.')

    return 0


def encode_app_token(app_token, challenge):
    import hashlib
    import hmac

    return hmac.new(app_token.encode('utf-8'), challenge.encode('utf-8'), hashlib.sha1).hexdigest()


def api_open_session(freebox):
    # Retrieve challenge
    uri = Freebox.get_api_call_uri('login/')
    r = requests.get(uri)
    r_json = r.json()

    if not r_json['success']:
        print('Could not retrieve challenge when opening session: {}'.format(r_json['msg']))
        sys.exit(1)

    challenge = r_json['result']['challenge']
    freebox.session_challenge = challenge

    # Open session
    uri += 'session/'
    password = encode_app_token(freebox.app_token, challenge)
    r = requests.post(uri, json={
        'app_id': app_id,
        'password': password
    })
    r_json = r.json()

    if not r_json['success']:
        print('Could not open session: {}'.format(r_json['msg']))
        sys.exit(1)

    session_token = r_json['result']['session_token']
    freebox.session_token = session_token
    freebox.save()


def get_freebox():
    return Freebox.retrieve()
