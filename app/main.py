"""Courtside Edge API. Run: uvicorn app.main:app --reload"""
import os, asyncio, datetime, csv, io, time, sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import db,providers,markets,history,covers,covers_odds,rankings,ai,props,live,player_opportunities,ai_research,stat_logs,leader_slates,research_index,accounts,next_opponent,discovery,personal_backup,cloud_accounts
from . import game_research, position_index, index_questions, odds_sources, pace

ROOT=Path(__file__).resolve().parent.parent
_sync_lock=asyncio.Lock()
_collection_status={'running':False,'sport':None,'completed_days':0,'total_days':0,'games':0,'player_logs':0,'errors':[],'message':'No download running'}
_collection_task=None
_last_odds_search={}
_covers_lock=asyncio.Lock()

def current_season_dates(sport, today=None):
    """Season-to-date window, without asking the user for dates."""
    if sport not in ('NBA','NFL'):raise ValueError('Choose NBA or NFL')
    today=today or tz_today().date()
    if sport=='NFL':
        # Opening games need not be on Thursday (the 2026 schedule starts Sep 9).
        # Start at September 1 and let the provider's season-type labels decide.
        year=today.year if today.month>=9 else today.year-1
        start=datetime.date(year,9,1)
    else:
        season_year=today.year if today.month>=10 else today.year-1
        start=datetime.date(season_year,10,1)  # Includes the earliest October games
    return start,today

def espn_season_dates(sport,season,today=None):
    if sport not in ('NBA','NFL'):raise ValueError('Choose NBA or NFL.')
    if not 2002<=season<=2100:raise ValueError('Choose a season from 2002 onward.')
    today=today or tz_today().date()
    start=datetime.date(season-1,10,1) if sport=='NBA' else datetime.date(season,8,1)
    end=datetime.date(season,9,30) if sport=='NBA' else datetime.date(season+1,3,1)
    if start>today:raise ValueError('That season has not started yet.')
    return start,min(end,today)


def date_chunks(start,end,size=14):
    """Small source-friendly batches. Do not make people choose batches themselves."""
    current=start
    while current<=end:
        stop=min(current+datetime.timedelta(days=size-1),end)
        yield current,stop
        current=stop+datetime.timedelta(days=1)

async def _run_collection(sport,start,end,sports=None):
    global _collection_status
    try:
        async with _sync_lock:
            for current_sport in sports or [sport]:
                for a,b in date_chunks(start,end):
                    _collection_status['current_sport']=current_sport
                    _collection_status['message']=f'Getting {current_sport} games from {a.isoformat()} to {b.isoformat()}…'
                    try:
                        result=await providers.sync_dates(current_sport,a.isoformat(),b.isoformat())
                        _collection_status['games']+=result['games']
                        _collection_status['player_logs']+=result['player_logs']
                        _collection_status['errors'].extend(result.get('errors',[])[:10])
                    except Exception as ex:
                        _collection_status['errors'].append(f'{current_sport} {a}–{b}: {str(ex)[:150]}')
                    _collection_status['completed_days']+=(b-a).days+1
        _collection_status['message']='Finished getting games' if not _collection_status['errors'] else 'Finished, but some games could not be downloaded'
    except Exception as ex:
        _collection_status['message']='Download stopped because of an error'
        _collection_status['errors'].append(str(ex)[:180])
    finally:
        _collection_status['running']=False

async def start_collection(sport,start,end,both=False):
    global _collection_status,_collection_task
    if sport not in ('NBA','NFL'):raise HTTPException(400,'Choose NBA or NFL')
    if end<start:raise HTTPException(400,'End date must be after start date')
    if (end-start).days>366:raise HTTPException(400,'You can download up to one year at a time')
    if _collection_status['running'] or _sync_lock.locked():raise HTTPException(409,'A download is already running. Wait for it to finish.')
    label='NBA + NFL' if both else sport
    _collection_status={'running':True,'sport':label,'mode':'tonight' if both else 'range','start':start.isoformat(),'end':end.isoformat(),
        'completed_days':0,'total_days':((end-start).days+1)*(2 if both else 1),'games':0,'player_logs':0,'errors':[],
        'message':f'Starting your {label} download…'}
    _collection_task=asyncio.create_task(_run_collection(sport,start,end,['NBA','NFL'] if both else None))
    return dict(_collection_status)


def tz_today():
    try:
        return datetime.datetime.now(ZoneInfo(db.get_settings().get('timezone','America/Chicago')))
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)

async def nightly_scheduler():
    while True:
        try:
            now=tz_today()
            if os.environ.get('EDGE_AUTO_SYNC','1')=='1' and (now.hour,now.minute)>=(2,15):
                today=now.date().isoformat()
                with db.connect() as connection:
                    marker=connection.execute("SELECT value FROM settings WHERE key='last_nightly_success'").fetchone()
                if (not marker or marker[0]!=today) and not _sync_lock.locked() and not _collection_status['running']:
                    async with _sync_lock:
                        with db.connect() as connection:
                            connection.execute("INSERT INTO settings(key,value) VALUES ('last_nightly_attempt',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(today,))
                        success=True
                        for sport in ['NBA','NFL']:
                            result=await providers.sync_dates(sport,(now.date()-datetime.timedelta(days=2)).isoformat(),now.date().isoformat())
                            success=success and not result.get('errors')
                            await position_index.refresh(sport)
                        if success:
                            with db.connect() as connection:
                                connection.execute("INSERT INTO settings(key,value) VALUES ('last_nightly_success',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(today,))
        except asyncio.CancelledError:raise
        except Exception as ex:
            with db.connect() as connection:
                connection.execute('INSERT INTO sync_runs(sport,result,errors) VALUES (?,?,?)',('AUTO','error',str(ex)[:500]))
        await asyncio.sleep(60*20)

@asynccontextmanager
async def lifespan(app):
    db.init_db(seed=os.environ.get('EDGE_SEED_BETS','1')=='1')
    task=asyncio.create_task(nightly_scheduler())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError:pass
    if _collection_task and not _collection_task.done():
        _collection_task.cancel()
        try:await _collection_task
        except asyncio.CancelledError:pass

app=FastAPI(title='Courtside Edge',version='0.18.4',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=str(ROOT/'static')),name='static')

@app.middleware('http')
async def private_accounts(request:Request,call_next):
    public=('/api/auth/status','/api/auth/setup','/api/auth/login','/api/auth/register','/api/health','/api/cloud/config','/api/public/home')
    path=request.url.path
    user=accounts.session(request.cookies.get(accounts.COOKIE,''))
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        expected=str(request.base_url).rstrip('/')
        if origin and origin!=expected:return JSONResponse({'detail':'This action must be made from Courtside Edge.'},status_code=403,headers={'Cache-Control':'no-store','Vary':'Cookie'})
    if cloud_accounts.enabled():return await cloud_accounts.handle(request,call_next)
    if path.startswith('/api/') and path not in public and not user and (accounts.configured() or os.environ.get('EDGE_REQUIRE_AUTH')=='1'):
        return JSONResponse({'detail':'Sign in to access your account.'},status_code=401,headers={'Cache-Control':'no-store','Vary':'Cookie'})
    request.state.account=user
    token=db.PROFILE_PATH.set(accounts.profile_path(user) if user and not user['is_owner'] else None)
    try:
        response=await call_next(request)
        if path.startswith('/api/'):
            response.headers['Cache-Control']='no-store';response.headers['Vary']='Cookie'
        return response
    finally:db.PROFILE_PATH.reset(token)

class SignIn(BaseModel):
    username:str=Field(min_length=1,max_length=60)
    password:str=Field(min_length=10,max_length=256)
    unit_size:float|None=Field(default=None,ge=.01,le=1_000_000)
    setup_code:str=Field(default='',max_length=160)

@app.get('/api/auth/status')
def account_status(request:Request):
    user=request.state.account
    if cloud_accounts.enabled():return {'configured':True,'setup_required':False,'cloud':True,'onboarding_required':getattr(request.state,'onboarding_required',False),'user':{'name':user['username'],'owner':False} if user else None}
    configured=accounts.configured()
    return {'configured':configured,'setup_required':not configured and os.environ.get('EDGE_REQUIRE_AUTH')=='1','setup_code_required':bool(os.environ.get('EDGE_SETUP_TOKEN')),'user':{'name':user['username'],'owner':bool(user['is_owner'])} if user else None}

def establish_session(body,response,request,setup=False,register=False):
    try:
        if setup and os.environ.get('EDGE_REQUIRE_AUTH')=='1':
            import hmac
            expected=os.environ.get('EDGE_SETUP_TOKEN','')
            if not expected or not hmac.compare_digest(body.setup_code,expected):raise ValueError('Enter the owner setup code configured on the server.')
        token,user=accounts.credentials(body.username,body.password,setup,register,body.unit_size)
    except (ValueError,sqlite3.IntegrityError) as ex:raise HTTPException(400,str(ex))
    response.set_cookie(accounts.COOKIE,token,max_age=7*86400,httponly=True,samesite='strict',secure=request.url.scheme=='https')
    return {'name':user['username'],'owner':bool(user['is_owner'])}

@app.post('/api/auth/setup')
def account_setup(body:SignIn,response:Response,request:Request):return establish_session(body,response,request,True)

@app.post('/api/auth/login')
def account_login(body:SignIn,response:Response,request:Request):return establish_session(body,response,request)

@app.post('/api/auth/register')
def account_register(body:SignIn,response:Response,request:Request):return establish_session(body,response,request,register=True)

@app.post('/api/auth/logout')
def account_logout(request:Request):
    try:backup=accounts.backup_and_sign_out(request.cookies.get(accounts.COOKIE,''))
    except ValueError as ex:raise HTTPException(401,str(ex))
    except (OSError,sqlite3.Error):raise HTTPException(503,'Your backup could not be saved. You are still signed in; check device storage and retry.')
    response=FileResponse(backup,media_type='application/zip',filename=backup.name,headers={'Cache-Control':'no-store'})
    response.delete_cookie(accounts.COOKIE,httponly=True,samesite='strict')
    return response

@app.get('/api/teams/next-game')
async def next_team_game(sport:str,team:str,refresh:bool=False):
    try:return await next_opponent.lookup(sport,team,refresh)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/')
def index():return FileResponse(ROOT/'static'/'index.html',headers={'Cache-Control':'no-store'})

@app.get('/api/health')
def health(request:Request):return {'ok':True,'version':'0.18.4',**({'data':db.data_counts()} if not cloud_accounts.enabled() and (request.state.account or not accounts.configured()) else {})}

@app.get('/api/cloud/config')
def cloud_config():
    try:return cloud_accounts.config()
    except cloud_accounts.CloudError as ex:raise HTTPException(ex.status,ex.message)

@app.get('/api/public/home')
async def public_home():
    today=tz_today().date();games={};dates={};issues={}
    async def slate(sport):
        board=await live.scoreboard(sport,today.isoformat())
        rows=board['games'];chosen=today
        # Keep a still-live late game, never a completed previous-day slate.
        yesterday=await live.scoreboard(sport,(today-datetime.timedelta(days=1)).isoformat())
        late=[g for g in yesterday['games'] if g['status']=='live']
        if late:rows=yesterday['games'];chosen=today-datetime.timedelta(days=1)
        elif rows and not board.get('stale') and all(g['status']=='final' for g in rows):
            chosen=today+datetime.timedelta(days=1);board=await live.scoreboard(sport,chosen.isoformat());rows=board['games']
        games[sport]=rows;dates[sport]=chosen.isoformat();issues[sport]=board.get('error','')
    await asyncio.gather(*(slate(sport) for sport in ('NBA','NFL')))
    return {'date':today.isoformat(),'dates':dates,'games':games,'issues':issues}


class CloudUnit(BaseModel):
    unit_size:float=Field(ge=.01,le=1_000_000)

@app.post('/api/cloud/onboard')
def cloud_onboard(body:CloudUnit,request:Request):
    if not cloud_accounts.enabled():raise HTTPException(404,'Cloud sign-in is not enabled.')
    if not request.state.onboarding_required:raise HTTPException(409,'This account is already set up. Change its unit size in Settings.')
    if round(body.unit_size,2)!=body.unit_size:raise HTTPException(400,'Enter your unit size in dollars and cents.')
    db.save_settings({'unit_size':body.unit_size,'starting_bankroll':0})
    return {'name':request.state.account['username'],'owner':False}

@app.get('/api/account/backup-json')
def json_backup():
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return JSONResponse(personal_backup.capture(),headers={'Content-Disposition':f'attachment; filename="Courtside_Backup_{stamp}.json"'})

@app.post('/api/account/backup-preview')
def json_backup_preview(data:dict):
    try:return personal_backup.preview(data)
    except ValueError as ex:raise HTTPException(400,str(ex))

class RestoreJSON(BaseModel):
    backup:dict
    current_fingerprint:str=Field(min_length=64,max_length=64)
    confirmed:bool=False

@app.post('/api/account/backup-restore')
def json_backup_restore(body:RestoreJSON):
    try:return personal_backup.restore(body.backup,body.current_fingerprint,body.confirmed)
    except ValueError as ex:raise HTTPException(400,str(ex))
    except (OSError,sqlite3.Error):raise HTTPException(503,'The current tracker could not be safely backed up. Nothing was loaded; check storage and retry.')

@app.get('/api/dashboard')
def dashboard():return {'summary':db.bet_summary(),'bets':db.all_bets()[:15],'data':db.data_counts()}

@app.get('/api/settings')
def settings():return db.get_settings()

class SettingsIn(BaseModel):
    starting_bankroll:float=Field(ge=0)
    unit_size:float=Field(gt=0)
    timezone:str='America/Chicago'
    current_bankroll:float|None=Field(default=None,ge=0,le=1e12)

@app.put('/api/settings')
def settings_save(body:SettingsIn):
    try:
        values=body.model_dump(exclude={'current_bankroll'})
        if body.current_bankroll is not None:
            if any(round(v,2)!=v for v in (body.current_bankroll,body.starting_bankroll,body.unit_size)):raise ValueError('Enter dollar amounts with no more than two decimal places.')
            # A balance correction is separate from wins/losses and never edits bets.
            values['bankroll_adjustment']=round(body.current_bankroll-body.starting_bankroll-db.bet_summary()['profit'],2)
        db.save_settings(values)
    except ValueError as ex:raise HTTPException(400,str(ex))
    return db.get_settings()

@app.get('/api/bets')
def bets():return db.all_bets()

class BetIn(BaseModel):
    placed_at:str
    sport:str='NBA'
    market:str
    selection:str
    odds:int
    stake:float=Field(gt=0)
    status:str='pending'
    payout:float=Field(default=0,ge=0)
    note:str=''
    sportsbook:str=''

@app.post('/api/bets')
def bets_add(bet:BetIn):
    try:
        datetime.date.fromisoformat(bet.placed_at[:10]);id=db.upsert_bet(bet.model_dump());return {'id':id}
    except (ValueError,KeyError) as ex:raise HTTPException(400,str(ex))

@app.put('/api/bets/{bet_id}')
def bets_update(bet_id:int, bet:BetIn):
    try:db.upsert_bet(bet.model_dump(),bet_id);return {'id':bet_id}
    except ValueError as ex:raise HTTPException(400,str(ex))
    except KeyError as ex:raise HTTPException(404,str(ex))

@app.delete('/api/bets/{bet_id}')
def bets_delete(bet_id:int):
    try:db.delete_bet(bet_id);return {'deleted':True}
    except KeyError as ex:raise HTTPException(404,str(ex))

@app.get('/api/bets/export')
def export_bets():return PlainTextResponse(db.bets_csv(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="courtside_bets.csv"'})

@app.get('/api/games')
def games(sport:str='NBA',start:str|None=None,end:str|None=None):
    if sport not in ['NBA','NFL']:raise HTTPException(400,'Sport must be NBA or NFL')
    return db.games_list(sport,start,end,300)

@app.post('/api/schedule/refresh')
async def refresh_schedule(sport:str='NBA',date:str=Query(...)):
    if sport not in providers.SPORT_PATH:raise HTTPException(400,'Choose NBA or NFL')
    try:chosen=datetime.date.fromisoformat(date)
    except ValueError:raise HTTPException(400,'Choose a valid date')
    return await live.scoreboard(sport,chosen.isoformat(),force=True)

@app.get('/api/covers/snapshots')
def covers_list(sport:str,game_id:str):
    try:return covers.list_snapshots(sport,game_id)
    except ValueError as ex:raise HTTPException(400,str(ex))

class SnapshotIn(BaseModel):
    sport:str
    game_id:str
    source_url:str=Field(default='',max_length=300)

@app.post('/api/covers/odds/refresh')
async def covers_prices(body:SnapshotIn):
    try:return await covers_odds.refresh(body.sport,body.game_id,body.source_url)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/covers/odds')
def saved_covers_prices(sport:str,game_id:str):
    try:covers.game(sport,game_id)
    except ValueError as ex:raise HTTPException(400,str(ex))
    return covers_odds.saved(sport,game_id)

@app.post('/api/covers/capture')
async def covers_capture(body:SnapshotIn):
    if _covers_lock.locked():raise HTTPException(409,'A Covers snapshot is already being captured. Please wait.')
    try:
        async with _covers_lock:
            return await asyncio.wait_for(asyncio.to_thread(covers.capture_page,body.source_url,body.sport,body.game_id),timeout=60)
    except ValueError as ex:raise HTTPException(400,str(ex))
    except asyncio.TimeoutError:raise HTTPException(504,'Covers took too long. Open the page and upload a screenshot instead.')

@app.post('/api/covers/upload')
async def covers_upload(sport:str=Form(...),game_id:str=Form(...),source_url:str=Form(...),note:str=Form(''),file:UploadFile=File(...)):
    try:return covers.save_image(await file.read(12*1024*1024+1),sport,game_id,source_url,note=note)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/covers/images/{snapshot_id}')
def covers_image(snapshot_id:str):
    with db.connect() as connection:
        row=connection.execute('SELECT filename FROM covers_snapshots WHERE id=?',(snapshot_id,)).fetchone()
    if not row:raise HTTPException(404,'Snapshot not found')
    return FileResponse(db.database_path().parent/'covers'/row['filename'],media_type='image/png')

@app.get('/api/consistency')
def consistency(sport:str='NBA',teams:str='',stat:str='pts',threshold:float=20,
      min_rate:float=50,max_rate:float=100,last:int=10,venue:str='all',season_type:str='regular',min_minutes:float=0,
      comparison:str='at_least',opponent:str='',before:str|None=None,season:int|None=None,player:str=Query(default='',max_length=150)):
    try:
        return {'results':db.consistency(sport,teams.split(',') if teams else None,stat,threshold,min_rate,max_rate,last,venue,season_type,min_minutes,
                    comparison=comparison,opponent=opponent,before=before,season=season,player=player),
                'filters':{'sport':sport,'teams':teams,'stat':stat,'threshold':threshold,'last':last,'min_rate':min_rate,'max_rate':max_rate,'comparison':comparison,'before':before,'season':season,'opponent':opponent,'player':player}}
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/thresholds')
def thresholds(sport:str,player_id:str,stat:str,last:int=10,season_type:str='regular'):
    try:return db.threshold_ladder(sport,player_id,stat,last,season_type)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/matchup')
def matchup(home:str,away:str,last:int=10,season_type:str='regular',before:str|None=None):
    if last<1 or last>100:raise HTTPException(400,'Choose 1 to 100 games')
    try:return db.nba_matchup(home.upper(),away.upper(),last,season_type,before)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/dvp')
def dvp(team:str,last:int=10,season_type:str='regular',before:str|None=None):
    if last<1 or last>100:raise HTTPException(400,'Choose 1 to 100 games')
    try:return db.defense_vs_position(team.upper(),last,season_type,before)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/data')
def data_status():return db.data_counts()

@app.get('/api/data/collection-status')
def collection_status():
    return dict(_collection_status)

@app.post('/api/data/season-sync')
async def season_sync(sport:str=Query('NFL')):
    """Get the full current season to today, automatically batched."""
    try:start,end=current_season_dates(sport.upper())
    except ValueError as ex:raise HTTPException(400,str(ex))
    return await start_collection(sport.upper(),start,end)

@app.post('/api/data/collect')
async def custom_collect(sport:str=Query('NFL'),start:str=Query(...),end:str=Query(...)):
    try:
        a=datetime.date.fromisoformat(start);b=datetime.date.fromisoformat(end)
    except ValueError:raise HTTPException(400,'Choose valid dates')
    return await start_collection(sport.upper(),a,b)

@app.post('/api/data/sync')
async def sync(sport:str=Query('NBA'),start:str=Query(...),end:str=Query(...)):
    if _sync_lock.locked():raise HTTPException(409,'A synchronization is already running')
    try:
        async with _sync_lock:result=await providers.sync_dates(sport,start,end)
        return result
    except ValueError as ex:raise HTTPException(400,str(ex))


async def _login_collection(plans):
    try:
        async with _sync_lock:
            for sport,start,end in plans:
                _collection_status['message']='Checking '+sport+' season game logs…'
                def progress(date):
                    _collection_status['completed_days']+=1
                    _collection_status['message']=f'{sport}: checked games through {date}'
                for a,b in date_chunks(start,end):
                    result=await providers.sync_dates(sport,a.isoformat(),b.isoformat(),skip_saved=True,progress=progress)
                    _collection_status['games']+=result['games'];_collection_status['player_logs']+=result['player_logs']
                    _collection_status['errors'].extend(result.get('errors',[])[:10])
                _collection_status['message']='Verifying '+sport+' player positions against ESPN rosters…'
                result=await position_index.refresh(sport)
                _collection_status['errors'].extend(result['issues'][:10])
        counts=db.data_counts()
        _collection_status['failed']=bool(_collection_status['errors']) and not any(counts[s]['player_logs'] for s in ('NBA','NFL'))
        _collection_status['outcome']='failed' if _collection_status['failed'] else 'partial' if _collection_status['errors'] else 'complete'
        _collection_status['message']='Sync complete' if not _collection_status['errors'] else 'Sync finished with source gaps. Review the details before researching.'
    except Exception as ex:
        _collection_status['failed']=True;_collection_status['outcome']='failed'
        _collection_status['errors'].append(str(ex)[:180]);_collection_status['message']='Sync could not finish. Retry to complete the update.'
    finally:_collection_status['running']=False

@app.post('/api/data/login-sync')
async def login_sync():
    global _collection_status,_collection_task
    if _collection_status['running']:return dict(_collection_status)
    if _sync_lock.locked():raise HTTPException(409,'A scheduled stats update is finishing. Retry the sign-in sync shortly.')
    plans=[(sport,*current_season_dates(sport)) for sport in ('NBA','NFL')]
    _collection_status={'running':True,'mode':'login','sport':'NBA + NFL','completed_days':0,
        'total_days':sum((end-start).days+1 for _,start,end in plans),'games':0,'player_logs':0,'errors':[],
        'message':'Checking this season’s ESPN NBA and NFL game logs…'}
    _collection_task=asyncio.create_task(_login_collection(plans))
    return dict(_collection_status)

@app.post('/api/data/sync-tonight')
async def sync_tonight():
    today=tz_today().date()
    # Include recent dates for late-finishing games and official corrections.
    return await start_collection('NBA',today-datetime.timedelta(days=2),today,both=True)

@app.post('/api/data/import')
async def csv_import(sport:str=Form('NBA'),season_type:str=Form('regular'),file:UploadFile=File(...)):
    if not file.filename.lower().endswith('.csv'):raise HTTPException(400,'Please upload a .csv file')
    try:
        raw=await file.read(90*1024*1024+1)
        return providers.ingest_csv(raw,sport.upper(),season_type)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.post('/api/data/bootstrap')
async def bootstrap(sport:str=Query('NBA'),season:int=Query(2026,ge=2002,le=2027)):
    """Optional historical import. Sources may be unavailable; error is made explicit."""
    if _sync_lock.locked():raise HTTPException(409,'Another import or sync is running')
    try:
        async with _sync_lock:
            result=await history.import_season(sport.upper(),season)
        with db.connect() as connection:
            connection.execute('INSERT INTO sync_runs(sport,result,players,games) VALUES (?,?,?,?)',
                (sport.upper(),'success',result['imported'],result.get('games',0)))
        return result
    except (ValueError,httpx.HTTPError) as ex:
        message='The source could not supply this season. Check your connection or try another year.' if isinstance(ex,httpx.HTTPError) else str(ex)
        with db.connect() as connection:
            connection.execute('INSERT INTO sync_runs(sport,result,errors) VALUES (?,?,?)',(sport.upper(),'error',message))
        raise HTTPException(502,message)

@app.get('/api/data/template')
def csv_template(sport:str='NBA'):
    if sport=='NBA':line='game_id,game_date,player_id,player,team,opponent,minutes,pts,reb,ast,fg3m\n'
    else:line='game_id,game_date,player_id,player,team,opponent,rec,rec_yds,targets,rush_att,rush_yds,pass_yds,pass_td,rush_td,rec_td\n'
    return PlainTextResponse(line,media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{sport.lower()}_import_template.csv"'})


# Free bookmaker comparisons and saved team betting trends.
class OddsSourceIn(BaseModel):
    provider:str
    key:str=Field(default='',max_length=250)
@app.get('/api/odds/sources')
def odds_source_status():return odds_sources.status()
@app.put('/api/odds/sources')
def odds_source_configure(body:OddsSourceIn):
    try:return odds_sources.configure(body.provider,body.key)
    except ValueError as ex:raise HTTPException(400,str(ex))
@app.get('/api/odds/status')
def odds_status():return markets.key_status()

class ApiKeyIn(BaseModel):
    key:str

@app.post('/api/odds/key')
def odds_key(body:ApiKeyIn):
    try:markets.set_key(body.key)
    except ValueError as ex:raise HTTPException(400,str(ex))
    return markets.key_status()

@app.post('/api/odds/refresh')
async def odds_refresh(sport:str=Query('NBA'),market:str=Query('h2h')):
    if market not in ('h2h','spreads','totals'):raise HTTPException(400,'Choose moneyline, spread, or total')
    try:return await markets.fetch_live_odds(sport.upper(),market)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/odds/compare')
def odds_compare(sport:str=Query('NBA'),books:str='',include_finished:bool=False):
    if sport.upper() not in ('NBA','NFL'):raise HTTPException(400,'Choose NBA or NFL')
    return markets.compare(sport.upper(),books=books.split(',') if books else None,include_finished=include_finished)

class ManualLineIn(BaseModel):
    sport:str='NBA'
    game_date:str
    home:str
    away:str
    market:str='h2h'
    selection:str
    point:float|None=None
    book:str
    price:int

@app.post('/api/odds/manual')
def odds_manual(q:ManualLineIn):
    try:
        datetime.date.fromisoformat(q.game_date)
        n=markets.save_quotes([{**q.model_dump(),'source':'manual'}])
        if n<1:raise ValueError('Fill in both teams, the book and selection')
        return {'saved':n}
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/teams/list')
def teams_list(sport:str='NFL'):
    if sport.upper() not in ('NBA','NFL'):raise HTTPException(400,'Choose NBA or NFL')
    return {'teams':markets.saved_team_names(sport.upper())}

@app.get('/api/teams/trends')
def team_trends(sport:str='NFL',team:str='',last:int=10,venue:str='all'):
    try:return markets.game_trends(sport,team,last,venue)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/teams/trends/league')
def league_trend_screen(sport:str='NBA',last:int=Query(5,ge=1,le=100),venue:str='all',include_previous:bool=False):
    try:return discovery.league_trends(sport,last,venue,include_previous)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/research/opportunities')
def research_opportunities(sport:str='NBA',stat:str='',game_id:str='',include_previous:bool=False):
    try:return discovery.prop_opportunities(sport,stat,game_id,include_previous)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.post('/api/research/opportunities/refresh')
async def refresh_research_opportunities(sport:str='NBA',stat:str='pts',game_id:str='',include_previous:bool=False):
    if stat not in props.MARKETS.get(sport,{}):raise HTTPException(400,'Choose one prop category to refresh.')
    if _props_lock.locked():raise HTTPException(409,'A price refresh is already running. Wait for it to finish.')
    async with _props_lock:
        board=await live.scoreboard(sport,tz_today().date().isoformat())
        games=[g for g in board['games'] if g['status'] in ('scheduled','live') and (not game_id or g['id']==game_id)]
        issues=[];updated=0
        for g in games[:6]:
            try:await props.refresh(sport,g['id'],stat,include_previous);updated+=1
            except ValueError as ex:issues.append({'game_id':g['id'],'message':str(ex)})
        return {**discovery.prop_opportunities(sport,stat,game_id,include_previous),'updated_games':updated,'unrefreshed_games':max(0,len(games)-6),'issues':issues}

class GameLineIn(BaseModel):
    sport:str='NFL'
    game_id:str
    home_spread:float|None=None
    total_line:float|None=None

@app.post('/api/teams/line')
def team_line(q:GameLineIn):
    try:markets.save_game_line(q.sport,q.game_id,q.home_spread,q.total_line)
    except ValueError as ex:raise HTTPException(400,str(ex))
    return {'saved':True}

class AskIn(BaseModel):
    question:str=Field(min_length=3,max_length=600)
    sport:str='NBA'

@app.post('/api/ask')
async def ask(q:AskIn):
    # Explicit searches for market prices should check the connected bookmaker feed.
    note=None
    if any(x in q.question.lower() for x in ('find value','best odds','best price','different books','which book','market value')):
        if markets.get_key() and time.monotonic()-_last_odds_search.get(q.sport.upper(),0)>600:
            try:
                await markets.fetch_live_odds(q.sport.upper(),'h2h')
                _last_odds_search[q.sport.upper()]=time.monotonic()
            except ValueError as ex:note='Could not refresh sportsbook prices: '+str(ex)
    try:
        answer=index_questions.answer(q.question,q.sport) or markets.question_answer(q.question,q.sport)
        if note:answer['answer']=note+'\n'+answer['answer']
        return answer
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.get('/api/rankings/config')
def rankings_config():
    return rankings.config()

@app.get('/api/rankings/positions')
def position_rankings(sport:str='NFL',position:str='TE',stat:str='rec_td',season:int|None=None,season_type:str='regular',period:str='season'):
    try:return research_index.defense(sport,position,stat,research_window=research_index.defense_window(sport,season,season_type,period))
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/rankings/pace')
async def pace_rankings(season:int|None=None,season_type:str='regular',last:int|None=Query(None,ge=1,le=100),refresh:bool=False):
    try:return await pace.rankings(season,season_type,last,refresh)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/rankings/positions/full')
def position_full_table(sport:str='NFL',position:str='TE',stat:str='rec_td',season:int|None=None,season_type:str='regular',period:str='season'):
    try:return research_index.defense_table(sport,position,stat,season,season_type,period)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/search/entities')
def entity_search(q:str,sport:str='NFL',season:int|None=None,season_type:str='regular',entity:str='',entity_id:str=''):
    try:return research_index.search(sport,q,season,season_type,entity,entity_id)
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.get('/api/game/player-opportunities')
def td_player_opportunities(game_id:str,last:int=Query(10,ge=1,le=100),season:int|None=None,season_type:str='regular'):
    try:return player_opportunities.opportunities(game_id,last,season,season_type)
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.get('/api/rankings')
def team_rankings(sport:str='NFL',season:int=2026,season_type:str='regular',metric:str='pass_yds',view:str='offense',order:str='most'):
    try:
        payload=rankings.cached(sport,season,season_type)
        return rankings.ranked(payload,metric,view,order) if payload else {'teams':[],'rows':[],'missing':True}
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.post('/api/rankings/refresh')
async def refresh_rankings(sport:str='NFL',season:int=2026,season_type:str='regular',metric:str='pass_yds',view:str='offense',order:str='most'):
    try:
        if metric not in {m['key'] for m in rankings.metrics(sport.upper())}:raise ValueError('Choose a category for this league')
        payload=await rankings.refresh(sport,season,season_type)
        return rankings.ranked(payload,metric,view,order)
    except (ValueError,httpx.HTTPError,KeyError) as ex:raise HTTPException(400,'Could not update rankings: '+str(ex)[:200])


class AIConfigIn(BaseModel):
    key:str=Field(default='',max_length=512)
    model:str=Field(default=ai.AI_MODEL,max_length=100)

@app.get('/api/ai/status')
def ai_status():return ai.status()

@app.post('/api/ai/config')
def ai_config(body:AIConfigIn):
    try:return ai.configure(body.key,body.model)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/covers/snapshots/{snapshot_id}/reading')
def snapshot_reading(snapshot_id:str):return ai.saved_reading(snapshot_id)

@app.post('/api/covers/snapshots/{snapshot_id}/read')
async def read_snapshot(snapshot_id:str):
    if ai._lock.locked():raise HTTPException(409,'An AI request is already running. Please wait.')
    try:
        async with ai._lock:return await ai.read_snapshot(snapshot_id)
    except ValueError as ex:raise HTTPException(400,str(ex))

class ChatHistoryIn(BaseModel):
    role:str=Field(pattern='^(user|assistant)$')
    content:str=Field(max_length=6000)

class AIChatIn(BaseModel):
    question:str=Field(min_length=3,max_length=4000)
    sport:str='NBA'
    game_id:str=Field(default='',max_length=80)
    history:list[ChatHistoryIn]=Field(default_factory=list,max_length=8)
    refresh_odds:bool=False


class AIRulesIn(BaseModel):
    text:str=Field(max_length=12000)
    enabled:bool=True


@app.get('/api/ai/rules')
def ai_rules():return ai_research.rules()


@app.post('/api/ai/rules')
def save_ai_rules(body:AIRulesIn):return ai_research.save_rules(body.text,body.enabled)

@app.post('/api/ai/chat')
async def ai_chat(body:AIChatIn):
    if ai._lock.locked():raise HTTPException(409,'An AI request is already running. Please wait.')
    try:
        async with ai._lock:return await ai.chat(body.question,body.sport,body.game_id,[x.model_dump() for x in body.history],body.refresh_odds)
    except ValueError as ex:raise HTTPException(400,str(ex))


class PropIn(BaseModel):
    sport:str
    game_id:str=Field(max_length=80)
    player:str=Field(min_length=1,max_length=150)
    stat:str
    side:str='Over'
    line:float=Field(ge=0,le=10000)
    price:int
    book:str='FanDuel'
    source_url:str=Field(default='',max_length=500)

@app.get('/api/props')
def game_props(sport:str,game_id:str,include_previous:bool=False):
    try:return props.listed(sport,game_id,include_previous)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.post('/api/props/manual')
def manual_prop(body:PropIn):
    try:
        game=covers.game(body.sport,body.game_id)
        quote=props.validate_quote(game,body.player,body.stat,body.side,body.line,body.price,body.book,body.source_url)
        return props.save(quote)
    except ValueError as ex:raise HTTPException(400,str(ex))

_props_lock=asyncio.Lock()
@app.post('/api/props/refresh')
async def refresh_props(sport:str,game_id:str,stat:str='',include_previous:bool=False):
    if _props_lock.locked():raise HTTPException(409,'A prop update is already running. Please wait.')
    try:
        async with _props_lock:return await props.refresh(sport,game_id,stat,include_previous)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/props/{quote_id}/history')
def prop_history(quote_id:str,last:int=10,season_type:str='regular',player_id:str='',include_previous:bool=False):
    try:return props.history(quote_id,last,season_type,player_id,include_previous=include_previous)
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.get('/api/scoreboard')
async def live_scoreboard(sport:str,date:str):
    try:return await live.scoreboard(sport,date)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/game/overview')
async def saved_game_overview(sport:str,game_id:str):
    try:return await live.overview(sport,game_id)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.post('/api/game/overview')
async def refresh_game_overview(sport:str,game_id:str):
    try:return await live.overview(sport,game_id,refresh_odds=True)
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.get('/api/stats/search')
def search_stat_logs(q:str=Query(...,max_length=250),sport:str='auto',last:int|None=Query(None,ge=1,le=100),stat:str='',opponent:str='',season_type:str='regular',player_id:str='',season_scope:str='auto',venue:str='all',rest:str='all'):
    try:return stat_logs.search(q,sport,last,stat,opponent,season_type,player_id,season_scope,venue,rest)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/game/boxscore')
async def game_boxscore(sport:str,game_id:str,refresh:bool=False):
    try:return await stat_logs.box_score(sport,game_id,refresh)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/game/research')
async def game_research_players(sport:str,game_id:str):
    try:return await game_research.overview(sport,game_id)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/game/research/player')
async def game_research_player(sport:str,game_id:str,player_id:str):
    try:return await game_research.player(sport,game_id,player_id)
    except ValueError as ex:raise HTTPException(400,str(ex))

@app.get('/api/stats/leaders')
async def daily_leaders(sport:str,date:str,stat:str,refresh:bool=False):
    try:return await stat_logs.leaders(sport,date,stat,refresh)
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.get('/api/stats/game')
def logged_game(sport:str,game_id:str):
    try:return covers.game(sport,game_id)
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.get('/api/stats/leaderboard')
def recent_stat_leaders(sport:str,window:str,stat:str,as_of:str='',season_type:str='regular',include_previous:bool=False):
    try:return stat_logs.historical_leaders(sport,window,stat,as_of or tz_today().date().isoformat(),season_type,include_previous)
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.get('/api/stats/tonight')
def retained_tonight_leaders(sport:str,stat:str):
    try:return leader_slates.leaders(sport,stat)
    except ValueError as ex:raise HTTPException(400,str(ex))


@app.post('/api/data/espn-season-sync')
async def collect_espn_season(sport:str,season:int):
    try:start,end=espn_season_dates(sport,season)
    except ValueError as ex:raise HTTPException(400,str(ex))
    return await start_collection(sport,start,end)


