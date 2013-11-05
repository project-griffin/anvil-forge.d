import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.gen
import functools
import logging
import socket
import multiprocessing
import subprocess
import uuid
import datetime
import time
import motor
import os
import imp
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.protocols.jsonrpc import JSONRPCSuccessResponse
from tinyrpc import BadRequestError, RPCBatchRequest

class UserTask:
  def start_task_as_user(self, taskname, *args, **kwargs):
    user = kwargs.pop('user')
    task_cb = kwargs.pop('callback')
    assert isinstance(user, dict)
    assert callable(task_cb)

    ioloop = tornado.ioloop.IOLoop.instance()
    socket_file = '/tmp/forge.d/forge_user_task_notify_%s' % uuid.uuid4()

    sox = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sox.bind(socket_file)
    sox.listen(1)

    cb = functools.partial(self.__on_complete, task_cb, socket_file)
    ioloop.add_handler(sox.fileno(), cb, ioloop.READ)
    self.tornado_conn, proc_conn = multiprocessing.Pipe()
    self.__run_process_as_user(socket_file, proc_conn, user, taskname=taskname, args=args, kwargs=kwargs)
    
    self.process_sox = sox
  
  def __run_process_as_user(self, socket_file, pipe, user, taskname=None, args=None, kwargs=None):
      assert callable(taskname)
      assert isinstance(user, dict)

      def as_user():
        os.chmod(socket_file, 0777)
        os.initgroups(user[u'username'], user[u'gid'])
        os.setgid(user[u'gid'])
        os.setuid(user[u'uid'])
        os.chdir(user[u'home'])
        pipe.send(taskname(user, *args, **kwargs))

        #notify
        sox = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sox.connect(socket_file)
        sox.close()
        pipe.close()

      proc = multiprocessing.Process(target=as_user)
      proc.start()

  def __on_complete(self, callback, socket_file, *args):
    logging.debug('ForgeD __run_process_as_user events: %s', str(args))
    ioloop = tornado.ioloop.IOLoop.instance()
    ioloop.remove_handler(self.process_sox.fileno())
    socket_file = self.process_sox.getsockname()
    self.process_sox.close()
    os.remove(socket_file)

    assert self.tornado_conn.poll()
    result = self.tornado_conn.recv()
    self.tornado_conn.close()
    callback(result)

class BaseRequestHandler(tornado.web.RequestHandler):
  def set_default_headers(self):
    self.set_header("Access-Control-Allow-Origin", "http://anvil-front.cloudapp.net")
    self.set_header("Access-Control-Allow-Credentials", "true")  

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
    logging.debug("WebSocket Opened for " + user["username"])

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
          utask = UserTask()
          result = yield tornado.gen.Task(utask.start_task_as_user, func, *request.args, user=user, **request.kwargs)
        except Exception as e:
          logging.error("exception: " + str(e))
          error_result = request.error_respond(e)
    if error_result:
      logging.error(error_result)
      self.write_message(request.error_respond(error_result).serialize())
    else:
      logging.debug(result)
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

@tornado.gen.coroutine
def fms_cleanup_orphans():
  db = db_async
  threshold = datetime.datetime.now() - datetime.timedelta(seconds=30)
  logging.info("Running token orphan cleanup for threshold: " + str(threshold))
  result = yield motor.Op(db.tokens.remove, {u'created': {'$lt': threshold}})
  n = result[u'n']
  logging.info(str(n) + " orphaned tokens cleaned")

######
# __main__
##
if __name__ == "__main__":
  # setup logging module
  logging.basicConfig(format='%(asctime)s:%(levelname)s: %(message)s', filename='/var/log/forge.d.log', level=logging.DEBUG)

  # check that tmp directory for socket notifications exists and is read/write
  if os.path.isdir('/tmp/forge.d'):
    if not os.access('/tmp/forge.d', os.W_OK | os.R_OK):
      #print "Permission error: Unable to access /tmp/forge.d"
      raise Exception("Permission error: Unable to access /tmp/forge.d/")
  else:
    logging.info("Creating temporary directory")
    os.mkdir('/tmp/forge.d')

  # open an async MongoDB client for registering the security tokens
  db_async = motor.MotorClient().open_sync().fms_auth

  # load service modules and initialize
  if not os.path.isdir('./services'):
    #print "no services directory"
    logging.info("No services directory found. No services loaded.")
  else:
    services = {}
    for file in os.listdir('./services'):
      if os.path.splitext(file)[-1].lower() == '.py':
        svc_name = os.path.splitext(file)[0]
        services[svc_name] = imp.load_source('services_' + svc_name, './services/' + file)
        func_init = getattr(services[svc_name], "initialize", None)
        if callable(func_init):
          func_init()

  application = tornado.web.Application([
      (r"/login", LoginHandler),
      (r"/logout", LogoutHandler),
      (r"/service", ServiceHandler),
    ],
      cookie_secret = "H1!VNFpDCcIQZ$OikUlUj!LWQj2$9VOLmYUWnfBQ~8k96NUsTEyLCUpXtVMHIH5H",
      db_async=db_async, services=services, rpc=JSONRPCProtocol(), debug=True)
  
  application.listen(8888)
  ioloop = tornado.ioloop.IOLoop.instance()
  cleanup_timer = tornado.ioloop.PeriodicCallback(fms_cleanup_orphans, 5 * 60 * 1000, ioloop)
  
  print "Starting Forge FMS Daemon"
  cleanup_timer.start()
  ioloop.start()
