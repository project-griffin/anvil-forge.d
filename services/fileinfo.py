import time
import subprocess
import json
import os
from shutil import copy2

# If a Forge module delcared an initialize() function, it will be
# called as part of the start-up and module loading
def initialize():
  print "FileInfo Service Initialzed"

# All functions declared in a Forge module are accessible over the 
# Forge websocket. They can have any number of arguments, but the
# argument list must end with **kwargs
def sleep(**kwargs):
  time.sleep(10)
  return  u"FileInfo: I'm up!"

def hello(**kwargs):
  return "Hello"

def ls_home(**kwargs):
  user = kwargs.pop('user')
  assert isinstance(user, dict)
  dname = user['home']
  listing = []
  for file in os.listdir(dname):
    path = os.path.join(dname, file)
    if os.path.isdir(path):
      listing.append({"is_dir": True, "name": file })
    else:
      listing.append({"is_dir": False, "name":  file})
  root_listing = {"path": dname, "contents": listing, "pardir": os.path.abspath(os.path.join(dname, os.pardir))}
  return json.dumps(root_listing, separators=(',', ':'), indent=4)

def ls(dname, **kwargs):
  user = kwargs.pop('user')
  assert isinstance(user, dict)
  listing = []
  for file in os.listdir(dname):
    path = os.path.join(dname, file)
    if os.path.isdir(path):
      listing.append({"is_dir": True, "name": file })
    else:
      listing.append({"is_dir": False, "name":  file})
  root_listing = {"path": dname, "contents": listing, "pardir": os.path.abspath(os.path.join(dname, os.pardir))}
  return json.dumps(root_listing, separators=(',', ':'), indent=4)

# Two keyword arguments are passed to each function:
# 'user', a dictionary of information about the current user
# 'settings', a dictionary of application settings
def ls_all(**kwargs):
  user = kwargs.pop('user')
  assert isinstance(user, dict)
  home = user['home']
  listing = []
  def walk(dir_list, currdir):
    for file in os.listdir(currdir):
      path = os.path.join(currdir, file)
      if os.path.isdir(path):
        sublist = []
        walk(sublist, path)
        dir_list.append({path: sublist})
      else:
        dir_list.append(file)
  walk(listing, home)
  root_listing = {home: listing}
  #print json.dumps(root_listing, indent=4)
  return json.dumps(root_listing, separators=(',', ':'), indent=4)

def get_file(filename, **kwargs):
  """filename: file to retrieve with absolute path"""
  user = kwargs.pop('user')
  assert isinstance(user, dict)
  home = user['home']

  #path = os.path.join(home, filename)
  (path, fname) = os.path.split(filename)

  if path == '':
    path = home

  if not os.access(filename, os.R_OK):
    return u"Permission error. Cannot access file: " + filename

  filetype = subprocess.check_output(["file", "-b", filename])
  mimetype = subprocess.check_output(["file", "-b", "--mime-type", filename])
  if filetype.find('text') != -1 or filetype.find('empty') != -1:
    with open(filename) as f:
      contents = f.read()
    return json.JSONEncoder().encode({'fname' : fname, 'path': path, 'type': mimetype, 'text': contents})
  else:
    return u"File not text. Cannot transmit."

def get_forge_listing(**kwargs):
  return get_file("forge/forge.d.py", **kwargs)

def get_fileinfo_pyc(**kwargs):
  return get_file("forge/services/fileinfo.pyc", **kwargs)

def get_profile(**kwargs):
  return get_file(".profile", **kwargs)

def put_file(filename, contents, **kwargs):
  user = kwargs.pop('user')
  assert isinstance(user, dict)
  home = user['home']

  #path = os.path.join(home, filename)

  (path, fname) = os.path.split(filename)

  if not os.access(path, os.W_OK):
    return u"Permission error. Cannot save to file: " + filename

  # create a backup
  backup_name = '.' + fname + '.bak'
  copy2(filename, os.path.join(path, backup_name))
  with open(filename, 'w') as f:
    f.write(contents)

  return u"OK"

def unlink(filename, **kwargs):
  return os.unlink(filename)

def rename(src, dst, **kwargs):
  return os.rename(src, dst)

def rmdir(path, **kwargs):
  return os.rmdir(path)

def get_user(**kwargs):
  user = kwargs.pop('user')
  return user['username']