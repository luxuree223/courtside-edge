"""Private accounts: each friend gets a separate database, keys, bets and settings."""
import datetime as dt
import hashlib
import hmac
import math
import secrets
import sqlite3
import time
import zipfile
from contextlib import closing,contextmanager
from . import db

SCHEMA='''CREATE TABLE IF NOT EXISTS account_users (
 id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,salt TEXT NOT NULL,password_hash TEXT NOT NULL,is_owner INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS account_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS account_invites(token_hash TEXT PRIMARY KEY,expires_at REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS next_team_schedule(sport TEXT NOT NULL,team TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(sport,team));'''
COOKIE='courtside_session';_attempts={}

@contextmanager
def registry():
    context=db.PROFILE_PATH.set(None)
    try:
        with db.connect() as c:yield c
    finally:db.PROFILE_PATH.reset(context)

def configured():
    with registry() as c:return bool(c.execute('SELECT 1 FROM account_users WHERE is_owner=1').fetchone())

def session(token):
    if not token:return None
    with registry() as c:
        row=c.execute('SELECT u.* FROM account_sessions s JOIN account_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    return dict(row) if row else None

def profile_path(user):return db.DB_PATH if user['is_owner'] else db.DB_PATH.parent/'accounts'/user['id']/'edge.sqlite3'
def digest(password,salt):return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()

def _new_profile(user,unit_size):
    token=db.PROFILE_PATH.set(profile_path(user))
    try:
        db.init_db(seed=False)
        with db.connect() as c:
            c.execute("UPDATE settings SET value='0' WHERE key='starting_bankroll'")
            c.execute("UPDATE settings SET value=? WHERE key='unit_size'",(format(unit_size,'.2f'),))
            # Copy public tables directly, never clone then delete private rows.
            c.execute('ATTACH DATABASE ? AS shared',(str(db.DB_PATH),))
            for table in ('games','player_logs','player_search','team_logs','team_rankings_cache','live_scoreboards','next_team_schedule'):
                c.execute('INSERT OR REPLACE INTO main.'+table+' SELECT * FROM shared.'+table)
    finally:db.PROFILE_PATH.reset(token)

def credentials(username,password,setup=False,register=False,unit_size=None):
    username=username.strip()
    if not 1<=len(username)<=60 or not 10<=len(password)<=256:raise ValueError('Use a name and a password with 10–256 characters.')
    if setup or register:
        try:unit_size=float(unit_size)
        except (TypeError,ValueError):raise ValueError('Enter your unit size in dollars, such as 5 or 10.')
        if not math.isfinite(unit_size) or not .01<=unit_size<=1_000_000 or round(unit_size,2)!=unit_size:raise ValueError('Enter a unit size from $0.01 to $1,000,000, using dollars and cents.')
    if setup or register:
        salt=secrets.token_hex(16);user={'id':secrets.token_hex(16),'username':username,'salt':salt,'password_hash':digest(password,salt),'is_owner':int(setup)}
        with registry() as c:
            c.execute('BEGIN IMMEDIATE')
            if setup and c.execute('SELECT 1 FROM account_users').fetchone():raise ValueError('Sign-in is already set up. Use your existing account.')
            if register and not c.execute('SELECT 1 FROM account_users WHERE is_owner=1').fetchone():raise ValueError('The site owner is finishing setup. Please try again shortly.')
            if c.execute('SELECT 1 FROM account_users WHERE username=?',(username,)).fetchone():raise ValueError('That name is already taken. Choose another name.')
            c.execute('INSERT INTO account_users VALUES (:id,:username,:salt,:password_hash,:is_owner)',user)
            if setup:c.execute("UPDATE settings SET value=? WHERE key='unit_size'",(format(unit_size,'.2f'),))
        if not setup:
            try:_new_profile(user,unit_size)
            except Exception:
                with registry() as c:
                    c.execute('DELETE FROM account_users WHERE id=?',(user['id'],))
                raise
    else:
        now=time.monotonic();key=str(db.DB_PATH.resolve());recent=[x for x in _attempts.get(key,[]) if now-x<900]
        if len(recent)>=6:raise ValueError('Too many sign-in attempts. Wait 15 minutes, then try again.')
        with registry() as c:row=c.execute('SELECT * FROM account_users WHERE username=?',(username,)).fetchone()
        user=dict(row) if row else None
        valid=hmac.compare_digest(digest(password,user['salt'] if user else '00'*16),user['password_hash'] if user else '00'*64)
        if not user or not valid:_attempts[key]=recent+[now];raise ValueError('The name or password is incorrect.')
        _attempts.pop(key,None)
    token=secrets.token_urlsafe(48)
    with registry() as c:
        c.execute('DELETE FROM account_sessions WHERE expires_at<?',(time.time(),))
        c.execute('INSERT INTO account_sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],time.time()+7*86400))
    return token,user

def backup_and_sign_out(token):
    user=session(token)
    if not user:raise ValueError('Sign in before signing out.')
    path=profile_path(user);root=path.parent.resolve();folder=root/'backups';folder.mkdir(exist_ok=True)
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    snapshot=folder/f'.signout-{stamp}.sqlite3';target=folder/f'Courtside_Backup_{stamp}.zip'
    try:
        with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(snapshot)) as dest:src.backup(dest)
        with closing(sqlite3.connect(snapshot)) as saved:
            saved.execute('DELETE FROM account_sessions');saved.execute('DELETE FROM account_invites');saved.execute('DELETE FROM account_users')
            saved.execute('INSERT INTO account_users VALUES (?,?,?,?,1)',(user['id'],user['username'],user['salt'],user['password_hash']));saved.commit()
            saved.execute('VACUUM')
            if saved.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise OSError('Backup verification failed.')
            images=[r[0] for r in saved.execute('SELECT filename FROM covers_snapshots')]
        with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot,'data/edge.sqlite3')
            for name in ('ai-config.json','openai-key.dpapi'):
                source=root/name
                if source.is_file():archive.write(source,'data/'+name)
            for name in images:
                source=(root/'covers'/name).resolve()
                if source.is_relative_to(root/'covers') and source.is_file():archive.write(source,'data/covers/'+name)
            archive.writestr('RESTORE.txt','Personal Courtside Edge backup: close the app and restore data/ into a separate project installation. Keep this archive private. Encrypted API keys may work only on the Windows account that saved them. Active sessions and other accounts are excluded. Sign in with your existing password.')
        with zipfile.ZipFile(target) as verified:
            if verified.testzip() is not None:raise OSError('Backup verification failed.')
        with registry() as c:c.execute('DELETE FROM account_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
        return target
    except Exception:
        target.unlink(missing_ok=True);raise
    finally:snapshot.unlink(missing_ok=True)
