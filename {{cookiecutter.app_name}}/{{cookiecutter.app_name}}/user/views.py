from oauthlib.oauth2 import InvalidGrantError
from flask import Blueprint, request, redirect, render_template, session, \
    abort, url_for, current_app

from .models import Organization
from ..utils import login_required, decode_jwt, get_oauth_session
from ..extensions import fulfil

blueprint = Blueprint('user', __name__)


@blueprint.route('/')
@login_required
def home():
    return render_template("home.html")


@blueprint.route('/login', methods=['GET', 'POST'])
def login():
    subdomain = None
    if request.method == 'POST' and request.form.get('organization'):
        subdomain = request.form.get('organization')
    else:
        subdomain = request.args.get('subdomain')

    if subdomain:
        session['subdomain'] = subdomain
        oauth_session = get_oauth_session()
        authorization_url, state = oauth_session.create_authorization_url(
            redirect_uri=url_for(
                '.authorized',
                next=request.args.get('next'),
                _external=True
            ),
            scope=current_app.config['FULFIL_PERMISSIONS']
        )
        session['oauth_state'] = state
        return redirect(authorization_url)
    return render_template('login.html')


@blueprint.route('/authorized')
def authorized():
    state = request.args.get('state')
    oauth_state = session.pop('oauth_state', None)
    if not oauth_state or oauth_state != state:
        # Verify if state is there in session
        abort(401)

    code = request.args.get('code')
    payload = decode_jwt(code)
    oauth_session = get_oauth_session(scope=payload['scope'])
    try:
        token = oauth_session.get_token(code=code)
    except InvalidGrantError:
        # Send user to home page which ask for login again.
        return redirect(url_for('user.home'))
    if not token:
        abort(400)

    if token.get('offline_access_token'):
        Organization.create_or_update(
            session['subdomain'],
            token['offline_access_token'],
            payload['organization_id'],
        )
    session['fulfil'] = {
        'user': token['associated_user'],
        'oauth_token': token,
        'subdomain': session['subdomain']
    }

    Access = fulfil.model('ir.model.access')
    models = set()
    permissions = set()
    for p in current_app.config['FULFIL_PERMISSIONS']:
        model, action = p.split(':')
        models.add(model)
        permissions.add((model, action))

    access_map = Access.get_access(list(models))
    for model, action in list(permissions):
        if not access_map[model][action]:
            logout()
            return render_template("login_permission_error.html"), 401

    return redirect(request.args.get('next') or url_for('user.home'))


@blueprint.route('/logout')
def logout():
    session.pop('fulfil', None)
    session.pop('session_id', None)
    session.pop('context', None)
    return redirect(url_for('user.home'))
