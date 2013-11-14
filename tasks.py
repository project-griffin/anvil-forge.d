import uuid
import tornado.ioloop
import socket
import functools
import os
import multiprocessing
import logging

class UserTask:
  def __init__(self, user, taskname):
    assert isinstance(user, dict)
    self.user = user
    self.taskname = taskname

  def start_task_as_user(self, *args, **kwargs):
    task_cb = kwargs.pop('callback')
    assert callable(task_cb)
    user = self.user
    taskname = self.taskname

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

class AdminTask:
  def __init__(self, taskname):
    self.taskname = taskname

  def start_task_as_admin(self, *args, **kwargs):
    task_cb = kwargs.pop('callback')
    assert callable(task_cb)
    taskname = self.taskname

    ioloop = tornado.ioloop.IOLoop.instance()
    socket_file = '/tmp/forge.d/forge_user_task_notify_%s' % uuid.uuid4()

    sox = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sox.bind(socket_file)
    sox.listen(1)

    cb = functools.partial(self.__on_complete, task_cb, socket_file)
    ioloop.add_handler(sox.fileno(), cb, ioloop.READ)
    self.tornado_conn, proc_conn = multiprocessing.Pipe()
    self.__run_process_as_admin(socket_file, proc_conn, taskname=taskname, args=args, kwargs=kwargs)
    
    self.process_sox = sox
  
  def __run_process_as_admin(self, socket_file, pipe, taskname=None, args=None, kwargs=None):
      assert callable(taskname)

      def as_admin():
        #os.chdir(user[u'home'])
        pipe.send(taskname(*args, **kwargs))

        #notify
        sox = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sox.connect(socket_file)
        sox.close()
        pipe.close()

      proc = multiprocessing.Process(target=as_admin)
      proc.start()

  def __on_complete(self, callback, socket_file, *args):
    logging.debug('ForgeD __run_process_as_admin events: %s', str(args))
    ioloop = tornado.ioloop.IOLoop.instance()
    ioloop.remove_handler(self.process_sox.fileno())
    socket_file = self.process_sox.getsockname()
    self.process_sox.close()
    os.remove(socket_file)

    assert self.tornado_conn.poll()
    result = self.tornado_conn.recv()
    self.tornado_conn.close()
    callback(result)