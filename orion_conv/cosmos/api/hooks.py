# Copyright 2019 PandoraGo Co.,LTD.
# All Rights Reserved.
#
# Tony 2019/2/4: Add pecan hooks.

from oslo_config import cfg
from oslo_context import context
from pecan import hooks
from six.moves import http_client

from cosmos.common import policy
from cosmos.core import manager
#from cosmos.db import api as dbapi


class ConfigHook(hooks.PecanHook):
    """Attach the config object to the request so controllers can get to it."""

    def before(self, state):
        state.request.cfg = cfg.CONF


class ContextHook(hooks.PecanHook):
    """Configures a request context and attaches it to the request.

    The following HTTP request headers are used:

    X-User-Id or X-User:
        Used for context.user.

    X-Tenant-Id or X-Tenant:
        Used for context.tenant.

    X-Auth-Token:
        Used for context.auth_token.

    X-Roles:
        Used for setting context.is_admin flag to either True or False.
        The flag is set to True, if X-Roles contains either an administrator
        or admin substring. Otherwise it is set to False.

    """
    def __init__(self, public_api_routes):
        self.public_api_routes = public_api_routes
        super(ContextHook, self).__init__()

    def before(self, state):
        headers = state.request.headers

        creds = {
            'user_name': headers.get('X-User-Name'),
            'user': headers.get('X-User-Id'),
            'project_name': headers.get('X-Project-Name'),
            'tenant': headers.get('X-Project-Id'),
            'domain': headers.get('X-User-Domain-Id'),
            'domain_name': headers.get('X-User-Domain-Name'),
            'auth_token': headers.get('X-Auth-Token'),
            'roles': headers.get('X-Roles', '').split(','),
        }

        is_admin = policy.check('is_admin', creds, creds)
        state.request.context = context.RequestContext(
            is_admin=is_admin, **creds)

    def after(self, state):
        if state.request.context == {}:
            # An incorrect url path will not create RequestContext
            return
        # NOTE(Tony): RequestContext will generate a request_id if no one
        # passing outside, so it always contain a request_id.
        request_id = state.request.context.request_id
        state.response.headers['Openstack-Request-Id'] = request_id


class CoreHook(hooks.PecanHook):
    """Attach the manager object to the request so controllers can get to it."""

    def before(self, state):
        state.request.manager = manager.CoreManager()


class DBHook(hooks.PecanHook):
    """Attach the dbapi object to the request so controllers can get to it."""

    def before(self, state):
        pass
        #state.request.dbapi = dbapi.get_instance()


class NoExceptionTracebackHook(hooks.PecanHook):
    """Workaround rpc.common: deserialize_remote_exception.

    deserialize_remote_exception builds rpc exception traceback into error
    message which is then sent to the client. Such behavior is a security
    concern so this hook is aimed to cut-off traceback from the error message.

    """
    # NOTE(Tony): 'after' hook used instead of 'on_error' because
    # 'on_error' never fired for wsme+pecan pair. wsme @wsexpose decorator
    # catches and handles all the errors, so 'on_error' dedicated for unhandled
    # exceptions never fired.
    def after(self, state):
        # Omit empty body. Some errors may not have body at this level yet.
        if not state.response.body:
            return

        # Do nothing if there is no error.
        # Status codes in the range 200 (OK) to 399 (400 = BAD_REQUEST) are not
        # an error.
        if (http_client.OK <= state.response.status_int <
                http_client.BAD_REQUEST):
            return

        json_body = state.response.json
        # Do not remove traceback when traceback config is set
        if cfg.CONF.debug_tracebacks_in_api:
            return

        faultstring = json_body.get('faultstring')
        traceback_marker = 'Traceback (most recent call last):'
        if faultstring and traceback_marker in faultstring:
            # Cut-off traceback.
            faultstring = faultstring.split(traceback_marker, 1)[0]
            # Remove trailing newlines and spaces if any.
            json_body['faultstring'] = faultstring.rstrip()
            # Replace the whole json. Cannot change original one because it's
            # generated on the fly.
            state.response.json = json_body


class PublicUrlHook(hooks.PecanHook):
    """Attach the right public_url to the request.

    Attach the right public_url to the request so resources can create
    links even when the API service is behind a proxy or SSL terminator.

    """

    def before(self, state):
        state.request.public_url = (cfg.CONF.api.public_endpoint or
                                    state.request.host_url)
