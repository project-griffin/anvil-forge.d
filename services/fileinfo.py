import time
import subprocess
import json
import os

def initialize():
  print "FileInfo Service Initialzed"

def sleep(user):
  time.sleep(10)
  return  u"FileInfo: I'm up!"

def ls(user):
  return subprocess.check_output(["ls", "-l"])

def hello(user):
  return "Hello"

def ls_home(user):
  assert isinstance(user, dict)
  home = user['home']
  listing = []
  def walk(dir_list, currdir):
    for file in os.listdir(currdir):
      path = os.path.join(currdir, file)
      if os.path.isdir(path):
        sublist = []
        walk(sublist, path)
        dir_list.append({file: sublist})
      else:
        dir_list.append(file)
  walk(listing, home)
  root_listing = {u'/': listing}
  #print json.dumps(root_listing, indent=4)
  return json.dumps(root_listing, separators=(',', ':'), indent=4)

def get_file(user, filename):
  assert isinstance(user, dict)
  home = user['home']

  path = os.path.join(home, filename)

  if not os.access(path, os.R_OK):
    return u"Permission error. Cannot access file: " + filename

  filetype = subprocess.check_output(["file", "-b", path])
  if filetype.find('text') != -1:
    f = open(path)
    return json.JSONEncoder().encode({'name' : filename, 'path': path, 'type': filetype, 'text': f.read()})
  else:
    return u"File not text. Cannot transmit."

def get_forge_listing(user):
  return get_file(user, "forge/forge.d.py")

def get_fileinfo_pyc(user):
  return get_file(user, "forge/services/fileinfo.pyc")

def get_profile(user):
  return get_file(user, ".profile")