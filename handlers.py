import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.gen
import logging
import uuid
import datetime
import time
import motor
import os
#import imp
from shutil import copy2
from tornado.options import define, options
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.protocols.jsonrpc import JSONRPCSuccessResponse
from tinyrpc import BadRequestError, RPCBatchRequest
from tasks import UserTask, AdminTask

class BaseRequestHandler(tornado.web.RequestHandler):
  def set_default_headers(self):
    self.set_header("Access-Control-Allow-Origin", "http://anvil-front.cloudapp.net")
    self.set_header("Access-Control-Allow-Credentials", "true")  

class BinaryUploadHandler(tornado.web.RequestHandler):
  @tornado.gen.coroutine
  def post(self):
    token = self.get_argument('file.user_upload_token', default=None)
    db = self.settings['db_async']
    user = yield motor.Op(db.upload_tokens.find_one, {u'_id': token})
    yield motor.Op(db.tokens.remove, {u'_id': token})

    if not user:
      logging.debug("invalid user upload token presented")
      self.write({u'error': u'upload failed'})
      self.finish()

    fname = self.get_argument('file.name', default=None)
    fpath = self.get_argument('file.path', default=None)
    ftarg = self.get_argument('file.target_dir', default=None)

    utask = UserTask(user, self.copy)
    result = yield tornado.gen.Task(utask.start_task_as_user, fpath, ftarg)

    os.unlink(fpath)
    self.write({u'result': result})
    self.finish()

  def copy(src, dest, **kwargs):
    return copy2(src, dest)

class LoginHandler(BaseRequestHandler):
  @tornado.gen.coroutine
  def post(self):
    import pam
    import pwd

    username = self.get_argument("username")
    password = self.get_argument("password")

    if pam.authenticate(username, password):
      db = self.settings['db_async']
      info = pwd.getpwnam(username)
      fms_token = str(uuid.uuid4())
      user = {
        u'_id' : fms_token,
        u'username' : username,
        u'uid' : info.pw_uid,
        u'gid' : info.pw_gid,
        u'home': info.pw_dir,
        u'created' : datetime.datetime.now()
      }

      result =  yield motor.Op(db.tokens.insert, user)
      self.set_secure_cookie("fms_auth", fms_token, expires_days=None)
      self.write("OK")
    else:
      self.clear_cookie("username")
      self.set_status(401) #Unauthorized

class LogoutHandler(BaseRequestHandler):
  def set_default_headers(self):
    self.set_header("Access-Control-Allow-Origin", "http://anvil-front.cloudapp.net")
    self.set_header("Access-Control-Allow-Credentials", "true")
  
  def post(self):
    self.clear_cookie("username")

class ServiceHandler(tornado.websocket.WebSocketHandler):
  @tornado.gen.coroutine
  def open(self):
    fms_token = self.get_secure_cookie("fms_auth")
    if not fms_token:
      self.close()
      return

    db = self.settings['db_async']
    user = yield motor.Op(db.tokens.find_one, {u'_id': fms_token})
    yield motor.Op(db.tokens.remove, {u'_id': fms_token})
    if not user:
      self.close()
      return
  
    t_delta = datetime.datetime.now() - user["created"]
    if t_delta.seconds > 35:
      self.close()
      return

    setattr(self, "user", user)
    logging.debug("WebSocket Opened for " + user["username"] + "[" + str(options.port) + "]")

  @tornado.gen.coroutine
  def on_message(self, message):
    user = getattr(self, "user", None)
    if not user:
      self.write_message(u"Auth Error: " + message)
      self.close()

    rpc = self.settings['rpc']

    try:
      request = rpc.parse_request(message)
    except BadRequestError as e:
      # request was invalid, directly create response
      logging.error("User: " + user[u'username'])
      logging.error( "   Exception: " + str(e))
      response = e.error_respond(e)
      self.write_message(response.serialize())

    services = self.settings['services']
    svc_name, sep, func_name = request.method.partition(u'.')
    logging.debug(svc_name + ":" + func_name)

    error_result = None
    if not svc_name in services:
      logging.debug("Bad Service Name: " + svc_name)
      error_result = u"Error: " + svc_name + u" not a valid service"
    else:
      func = getattr(services[svc_name], func_name, None)
      if not callable(func):
        logging.debug("Bad Function Name: " + func_name + " in Service: " + svc_name)
        error_result = u"Error: " + func_name + u" not a valid function in service " + svc_name
      else:
        try:
          utask = UserTask(user, func)
          result = yield tornado.gen.Task(utask.start_task_as_user, *request.args, settings=self.settings, **request.kwargs)
        except Exception as e:
          logging.error("exception: " + str(e))
          error_result = request.error_respond(e)
    if error_result:
      logging.error(error_result)
      self.write_message(request.error_respond(error_result).serialize())
    else:
      if result == "":
        result = u"OK";
      logging.debug("result obtained")
      self.write_message(request.respond(result).serialize())

  def on_close(self):
    user = getattr(self, "user", None)
    if user:
      logging.debug("WebSocket Closed for " + user["username"])
    else:
      logging.error("WebSocket Closed with user auth error")

  def sleep(self, seconds):
      time.sleep(seconds)
      return (u"I'm Up!")

class AdminHandler(tornado.websocket.WebSocketHandler):
  @tornado.gen.coroutine
  def open(self):
    client_ip = self.request.remote_ip

    if not client_ip in options.admin_ips:
      logging.warning("Attempted access to admin services from unauthorized ip: %s" % client_ip)
      self.close()
    logging.debug("WebSocket Opened for Admin[" + str(options.port) + "]")

  @tornado.gen.coroutine
  def on_message(self, message):
    rpc = self.settings['rpc']

    try:
      request = rpc.parse_request(message)
    except BadRequestError as e:
      # request was invalid, directly create response
      logging.error( "   Exception: " + str(e))
      response = e.error_respond(e)
      self.write_message(response.serialize())

    services = self.settings['admin_services']
    svc_name, sep, func_name = request.method.partition(u'.')
    logging.debug('admin: ' + svc_name + ":" + func_name)

    error_result = None
    if not svc_name in services:
      logging.debug("Bad Service Name: " + svc_name)
      error_result = u"Error: " + svc_name + u" not a valid service"
    else:
      func = getattr(services[svc_name], func_name, None)
      if not callable(func):
        logging.debug("Bad Function Name: " + func_name + " in Service: " + svc_name)
        error_result = u"Error: " + func_name + u" not a valid function in admin service " + svc_name
      else:
        try:
          atask = AdminTask(func)
          result = yield tornado.gen.Task(atask.start_task_as_admin, *request.args, **request.kwargs)
        except Exception as e:
          logging.error("exception: " + str(e))
          error_result = request.error_respond(e)
    if error_result:
      logging.error(error_result)
      self.write_message(request.error_respond(error_result).serialize())
    else:
      logging.debug("result obtained")
      self.write_message(request.respond(result).serialize())

  def on_close(self):
      logging.info("WebSocket closed")

  def sleep(self, seconds):
      time.sleep(seconds)
      return (u"I'm Up!")