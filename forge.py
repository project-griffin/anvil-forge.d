import tornado.ioloop
#import tornado.web
#import tornado.websocket
import tornado.gen
import logging
#import uuid
import datetime
import time
import motor
import os
import imp
from tornado.options import define, options
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
#from tinyrpc.protocols.jsonrpc import JSONRPCSuccessResponse
#from tinyrpc import BadRequestError, RPCBatchRequest
from handlers import LoginHandler, LogoutHandler, ServiceHandler, AdminHandler, BinaryUploadHandler

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
  os.chdir(os.path.dirname(os.path.realpath(__file__)))
  # define command-line and configuration options
  define("config", type=str, help="path to config file",
       callback=lambda path: tornado.options.parse_config_file(path, final=False))
  define("port", default=8900, help="port number to listen on")
  define("cleanup_interval", default=5, help="time interval to run orphaned token cleanup in minutes. 0 to supress cleanup (useful for multiple instances)")
  define("admin_ips", default="127.0.0.1", help="ip addresses allowed to access the admin services without user authenctication")

  # check that tmp directory for socket notifications exists and is read/write
  if os.path.isdir('/tmp/forge.d'):
    if not os.access('/tmp/forge.d', os.W_OK | os.R_OK):
      #print "Permission error: Unable to access /tmp/forge.d"
      raise Exception("Permission error: Unable to access /tmp/forge.d/")
  else:
    print("Creating temporary directory: /tmp/forge.d.\n")
    os.mkdir('/tmp/forge.d')

  # check that tmp directory for user uploads exists and is read/write
  if os.path.isdir('/tmp/user_uploads'):
    if not os.access('/tmp/user_uploads', os.W_OK | os.R_OK):
      #print "Permission error: Unable to access /tmp/forge.d"
      raise Exception("Permission error: Unable to access /tmp/user_uploads/")
  else:
    print("Creating temporary directory: /tmp/user_uploads.\n")
    os.mkdir('/tmp/user_uploads')

  # open an async MongoDB client for registering the security tokens
  db_async = motor.MotorClient().open_sync().fms_auth

  # load service modules and initialize
  if not os.path.isdir('./services'):
    #print "no services directory"
    print("No services directory found. No services loaded.\n")
  else:
    services = {}
    for file in os.listdir('./services'):
      if os.path.splitext(file)[-1].lower() == '.py':
        svc_name = os.path.splitext(file)[0]
        services[svc_name] = imp.load_source('services_' + svc_name, './services/' + file)
        func_init = getattr(services[svc_name], "initialize", None)
        if callable(func_init):
          func_init()
        logging.info('%s service loaded' % svc_name)

  # load admin service modules and initialize
  if not os.path.isdir('./admin_services'):
    print("No admin services directory found. No admin services loaded.\n")
  else:
    admin_services = {}
    for file in os.listdir('./admin_services'):
      if os.path.splitext(file)[-1].lower() == '.py':
        svc_name = os.path.splitext(file)[0]
        admin_services[svc_name] = imp.load_source('admin_services_' + svc_name, './admin_services/' + file)
        func_init = getattr(admin_services[svc_name], "initialize", None)
        if callable(func_init):
          func_init()
        logging.info('%s admin service loaded' % svc_name)

  # this has to be called after service modules are loaded, in case they define options
  tornado.options.parse_command_line()

  application = tornado.web.Application([
      (r"/login", LoginHandler),
      (r"/logout", LogoutHandler),
      (r"/service", ServiceHandler),
      (r"/admin", AdminHandler),
      (r"/upload", BinaryUploadHandler)
    ],
      cookie_secret = "H1!VNFpDCcIQZ$OikUlUj!LWQj2$9VOLmYUWnfBQ~8k96NUsTEyLCUpXtVMHIH5H",
      db_async=db_async, services=services, admin_services=admin_services, rpc=JSONRPCProtocol(), debug=True, xheaders=True)
  
  application.listen(options.port)
  ioloop = tornado.ioloop.IOLoop.instance()

  if options.cleanup_interval > 0:
    cleanup_timer = tornado.ioloop.PeriodicCallback(fms_cleanup_orphans, options.cleanup_interval * 60 * 1000, ioloop)
    cleanup_timer.start()
  else:
    logging.info("No orphaned token cleanup scheduled for this instance.")
  
  print("Starting Forge FMS Daemon on port: " + str(options.port) + "\n")
  ioloop.start()
