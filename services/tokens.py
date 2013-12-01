import motor
import uuid

def initialize():
	print("Token Service Initialized")

def get_user_token(**kwargs):
	settings = kwargs.pop('settings')
	db = settings['db_async']
	token = str(uuid.uuid4())
	new_user = dict(user)
	new_user['_id'] = token

	motor.Op(db.user_tokens.insert, new_user)
	return token

def get_user_upload_token(**kwargs):
	settings = kwargs.pop('settings')
	db = settings['db_async']
	token = str(uuid.uuid4())
	new_token = dict(user)
	new_token['_id'] = token

	motor.Op(db.upload_tokens.insert, new_user)
	return token