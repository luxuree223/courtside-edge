"""Portable personal JSON backups; no passwords, sessions, keys or public logs."""
import datetime as dt
import hashlib
import json
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel,ConfigDict,Field,field_validator
from . import db

FIELDS=('id','placed_at','sport','market','selection','odds','stake','status','payout','note','sportsbook')
class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    starting_bankroll:float=Field(ge=0,le=1e12)
    unit_size:float=Field(ge=.01,le=1e6)
    timezone:str=Field(max_length=80)
    @field_validator('timezone')
    @classmethod
    def timezone_exists(cls,value):ZoneInfo(value);return value

class Bet(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    id:int=Field(gt=0)
    placed_at:str=Field(min_length=10,max_length=40)
    sport:str=Field(min_length=1,max_length=20)
    market:str=Field(max_length=200)
    selection:str=Field(max_length=2000)
    odds:int=Field(ge=-1000000,le=1000000)
    stake:float=Field(gt=0,le=1e12)
    status:Literal['won','lost','pending','push','cashed_out']
    payout:float=Field(ge=0,le=1e12)
    note:str=Field(default='',max_length=20000)
    sportsbook:str=Field(default='',max_length=200)
    @field_validator('placed_at')
    @classmethod
    def valid_date(cls,value):dt.date.fromisoformat(value[:10]);return value
    @field_validator('odds')
    @classmethod
    def american_odds(cls,value):
        if abs(value)<100:raise ValueError('American odds must be at least +100 or at most -100.')
        return value

class PersonalFile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    format:Literal['courtside-edge-personal-backup']
    version:Literal[1]
    saved_at:str
    settings:Settings
    bets:list[Bet]=Field(max_length=10000)

def validate(data):
    try:
        result=PersonalFile.model_validate(data).model_dump()
        ids=[b['id'] for b in result['bets']]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate bet records.')
        if len(json.dumps(result).encode())>8_000_000:raise ValueError('Backup is too large.')
        return result
    except Exception as ex:raise ValueError('Choose a valid Courtside JSON backup. It must contain bets, bankroll, unit size and timezone, with no account secrets.') from ex

def capture(connection=None):
    def read(c):
        settings={r['key']:r['value'] for r in c.execute("SELECT key,value FROM settings WHERE key IN ('starting_bankroll','unit_size','timezone')")}
        bets=[{k:dict(r)[k] for k in FIELDS} for r in c.execute('SELECT * FROM bets ORDER BY id')]
        return {'format':'courtside-edge-personal-backup','version':1,'saved_at':dt.datetime.now(dt.timezone.utc).isoformat(),'settings':Settings.model_validate(settings).model_dump(),'bets':bets}
    if connection is not None:return read(connection)
    with db.connect() as c:return read(c)

def fingerprint(data):
    return hashlib.sha256(json.dumps({k:data[k] for k in ('settings','bets')},sort_keys=True,separators=(',',':')).encode()).hexdigest()

def preview(data):
    incoming=validate(data);current=capture()
    return {'bets':len(incoming['bets']),'current_bets':len(current['bets']),'settings':incoming['settings'],'saved_at':incoming['saved_at'],'current_fingerprint':fingerprint(current),'note':'Loading replaces this account’s bets, bankroll, unit size and timezone. Your current tracker is backed up first. Sign-in credentials and API keys stay unchanged.'}

def restore(data,current_fingerprint,confirmed=False):
    incoming=validate(data)
    if confirmed is not True:raise ValueError('Review the backup preview, then choose Replace my tracker to load it.')
    if fingerprint(capture())!=current_fingerprint:raise ValueError('Your tracker changed after the preview. Choose the file again to review the current tracker.')
    saved=db.backup_database()
    if not saved:raise OSError('The current tracker could not be backed up.')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if fingerprint(capture(c))!=current_fingerprint:raise ValueError('Your tracker changed after the preview. Choose the file again to review the current tracker.')
        apply(incoming,c)
    return {'restored':True,'bets':len(incoming['bets']),'backup_saved':True}

def apply(data,connection=None):
    incoming=validate(data)
    def write(c):
        c.execute('DELETE FROM bets')
        for bet in incoming['bets']:c.execute('INSERT INTO bets('+','.join(FIELDS)+') VALUES ('+','.join('?' for _ in FIELDS)+')',[bet[k] for k in FIELDS])
        for key,value in incoming['settings'].items():c.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
    if connection is not None:write(connection)
    else:
        with db.connect() as c:write(c)
