"""Optional Firebase Auth + Firestore personal trackers for an ephemeral host.

All Firestore operations use the signed-in person's ID token and security rules.
No service account, owner database or admin credentials are exposed to members.
"""
import asyncio,hashlib,json,os,time
from urllib.parse import quote
import httpx
from fastapi.responses import JSONResponse
from . import db,accounts,personal_backup

_identities={};_locks={}
COOKIE='courtside_cloud_session'
class CloudError(Exception):
    def __init__(self,message,status=503):self.message=message;self.status=status

def enabled():return os.environ.get('EDGE_FIREBASE_ENABLED')=='1'
def config():
    if not enabled():return {'enabled':False}
    values={'projectId':os.environ.get('EDGE_FIREBASE_PROJECT_ID',''),'apiKey':os.environ.get('EDGE_FIREBASE_API_KEY',''),'appId':os.environ.get('EDGE_FIREBASE_APP_ID','')}
    if not all(values.values()):raise CloudError('Cloud sign-in is waiting for the Firebase web-app configuration.')
    values['authDomain']=os.environ.get('EDGE_FIREBASE_AUTH_DOMAIN') or values['projectId']+'.firebaseapp.com'
    return {'enabled':True,'firebase':values}

async def verify(token):
    if not token:raise CloudError('Sign in to access your account.',401)
    cfg=config()['firebase'];key=(cfg['projectId'],hashlib.sha256(token.encode()).hexdigest());old=_identities.get(key)
    if old and old[0]>time.monotonic():return dict(old[1])
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r=await client.post('https://identitytoolkit.googleapis.com/v1/accounts:lookup',params={'key':cfg['apiKey']},json={'idToken':token})
        if r.status_code!=200:raise CloudError('Your sign-in expired. Sign in again.',401)
        users=r.json().get('users',[])
        if len(users)!=1 or not users[0].get('localId') or users[0].get('disabled'):raise CloudError('Sign in to a valid account.',401)
        user=users[0];uid=user['localId']
        result={'id':hashlib.sha256((cfg['projectId']+':'+uid).encode()).hexdigest()[:32],'cloud_uid':uid,'username':user.get('displayName') or user.get('email') or 'Member','is_owner':False}
        if len(_identities)>1000:_identities.clear()
        _identities[key]=(time.monotonic()+30,result);return dict(result)
    except (httpx.HTTPError,ValueError,KeyError):raise CloudError('Cloud sign-in could not be checked. Retry when the connection is available.')

def document_url(user):
    project=config()['firebase']['projectId']
    return f'https://firestore.googleapis.com/v1/projects/{quote(project,safe="")}/databases/(default)/documents/users/{quote(user["cloud_uid"],safe="")}/tracker/main'

async def read(user,token):
    try:
        async with httpx.AsyncClient(timeout=20) as client:r=await client.get(document_url(user),headers={'Authorization':'Bearer '+token})
        if r.status_code==404:return None,None
        if r.status_code in (401,403):raise CloudError('Cloud storage access was denied. Check sign-in and the Firebase security rules.',401 if r.status_code==401 else 503)
        if r.status_code!=200:raise CloudError('Cloud storage is unavailable. Your saved tracker has not been changed.')
        doc=r.json();data=json.loads(doc['fields']['payload']['stringValue'])
        return personal_backup.validate(data),doc['updateTime']
    except (httpx.HTTPError,ValueError,KeyError):raise CloudError('Your cloud tracker could not be loaded safely. Retry; no replacement tracker was saved.')

async def write(user,token,data,revision):
    payload=json.dumps(personal_backup.validate(data),separators=(',',':'),allow_nan=False)
    if len(payload.encode())>750000:raise CloudError('This tracker exceeds the current cloud backup size limit. Save a JSON backup before reducing long notes.',413)
    query={'currentDocument.updateTime':revision} if revision else {'currentDocument.exists':'false'}
    try:
        async with httpx.AsyncClient(timeout=20) as client:r=await client.patch(document_url(user),headers={'Authorization':'Bearer '+token},params=query,json={'fields':{'payload':{'stringValue':payload}}})
        conflict=r.status_code in (409,412)
        if r.status_code==400:
            try:conflict=r.json().get('error',{}).get('status')=='FAILED_PRECONDITION'
            except ValueError:pass
        if conflict:raise CloudError('This tracker changed on another device. Refresh it before retrying.',409)
        if r.status_code!=200:raise CloudError('The cloud save could not be confirmed. Refresh your tracker before retrying.')
    except httpx.HTTPError:
        # A response can be lost after a successful write. Check before reporting failure.
        stored,_=await read(user,token)
        if stored and personal_backup.fingerprint(stored)==personal_backup.fingerprint(data):return
        raise CloudError('The cloud save could not be confirmed. Refresh your tracker before retrying.')

def _response(error):return JSONResponse({'detail':error.message},status_code=error.status,headers={'Cache-Control':'no-store','Vary':'Authorization'})

async def handle(request,call_next):
    path=request.url.path
    request.state.account=None;request.state.onboarding_required=False
    if path in ('/api/cloud/config','/api/health','/api/public/home') or not path.startswith('/api/'):return await call_next(request)
    if path=='/api/cloud/signout' and request.method=='POST':
        response=JSONResponse({'signed_out':True},headers={'Cache-Control':'no-store'})
        response.delete_cookie(COOKIE,httponly=True,samesite='strict');return response
    if path=='/api/cloud/session' and request.method=='POST':
        try:
            bearer=request.headers.get('authorization','').removeprefix('Bearer ').strip();await verify(bearer)
            response=JSONResponse({'signed_in':True},headers={'Cache-Control':'no-store'})
            response.set_cookie(COOKIE,bearer,max_age=3600,httponly=True,samesite='strict',secure=request.url.scheme=='https');return response
        except CloudError as ex:return _response(ex)
    if path.startswith('/api/auth/') and path!='/api/auth/status':return _response(CloudError('Use cloud sign-in for this hosted app.',404))
    token=request.headers.get('authorization','').removeprefix('Bearer ').strip() or request.cookies.get(COOKIE,'')
    if not token and path=='/api/auth/status':return await call_next(request)
    context=None
    try:
        user=await verify(token)
        async with _locks.setdefault(user['id'],asyncio.Lock()):
            if not accounts.profile_path(user).exists():accounts._new_profile(user,1)
            context=db.PROFILE_PATH.set(accounts.profile_path(user));request.state.account=user
            stored,revision=await read(user,token);request.state.cloud_revision=revision;request.state.onboarding_required=stored is None
            if stored is None and path not in ('/api/auth/status','/api/cloud/onboard'):raise CloudError('Choose your unit size to finish creating your account.',428)
            before=personal_backup.capture()
            if stored is not None:personal_backup.apply(stored)
            response=await call_next(request)
            mutation=request.method in ('POST','PUT','DELETE') and (path.startswith('/api/bets') or path in ('/api/settings','/api/account/backup-restore','/api/cloud/onboard'))
            if mutation and response.status_code<400:
                try:await write(user,token,personal_backup.capture(),revision)
                except CloudError:
                    personal_backup.apply(stored or before);raise
            response.headers['Cache-Control']='no-store';response.headers['Vary']='Authorization';return response
    except CloudError as ex:return _response(ex)
    finally:
        if context is not None:db.PROFILE_PATH.reset(context)
