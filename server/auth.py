import hashlib, secrets, hmac, time
from datetime import timedelta
from .db import uid
from .domain import stamp,dt

def password_hash(password):
    if len(password)<12:raise ValueError('Use at least 12 characters for passwords.')
    salt=secrets.token_hex(16);digest=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    return salt+':'+digest

def verify(password,encoded):
    salt,digest=encoded.split(':');actual=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    return hmac.compare_digest(actual,digest)
def token_hash(token):return hashlib.sha256(token.encode()).hexdigest()
def login(db,name,password):
    user=db.execute('SELECT * FROM users WHERE name=? AND active=1',(name,)).fetchone()
    if not user:
        hashlib.scrypt(password.encode(),salt=b'missing-account',n=16384,r=8,p=1)
        raise ValueError('Incorrect username or password.')
    if not verify(password,user['password_hash']):raise ValueError('Incorrect username or password.')
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
    db.execute('DELETE FROM sessions WHERE expires_at<?',(stamp(),))
    db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(token_hash(token),user['id'],csrf,stamp(dt(stamp())+timedelta(hours=12))))
    return token,csrf,dict(user)
