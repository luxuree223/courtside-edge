"""Saved screenshot evidence. AI reading is an explicit optional action, separate from odds."""
import datetime
import io
import re
import uuid
from urllib.parse import urlsplit
from . import db

def validate_url(url,sport):
    parsed=urlsplit(url.strip())
    league='basketball/nba' if sport=='NBA' else 'football/nfl' if sport=='NFL' else None
    if (not league or parsed.scheme!='https' or parsed.hostname!='www.covers.com' or
        parsed.port not in (None,443) or parsed.username or parsed.password or
        not re.fullmatch('/sport/'+league+r'/matchup/\d+(?:/odds)?/?',parsed.path) or parsed.query or parsed.fragment):
        raise ValueError('Paste the Covers.com matchup link for this game (https://www.covers.com/sport/…/matchup/12345).')
    return 'https://www.covers.com'+parsed.path.rstrip('/').removesuffix('/odds')

def game(sport,game_id):
    with db.research_connect() as connection:
        row=connection.execute('SELECT * FROM games WHERE sport=? AND id=?',(sport,game_id)).fetchone()
    if not row:raise ValueError('Choose a saved game first.')
    return dict(row)

def list_snapshots(sport,game_id):
    game(sport,game_id)
    with db.connect() as connection:
        rows=[dict(r) for r in connection.execute('SELECT * FROM covers_snapshots WHERE sport=? AND game_id=? ORDER BY captured_at DESC',(sport,game_id))]
    for row in rows:
        row.pop('filename')
        row['image_url']='/api/covers/images/'+row['id']
        from . import ai
        row['analysis']=ai.saved_reading(row['id'])
    return rows

def save_image(raw,sport,game_id,source_url,method='uploaded',note=''):
    from PIL import Image,UnidentifiedImageError
    game(sport,game_id);source_url=validate_url(source_url,sport)
    if len(raw)>12*1024*1024:raise ValueError('Choose a screenshot smaller than 12 MB.')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('PNG','JPEG','WEBP') or im.width*im.height>30_000_000:raise ValueError('Choose a PNG, JPG or WebP screenshot under 30 million pixels.')
            im.load()
            output=io.BytesIO();im.convert('RGB').save(output,format='PNG')
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise ValueError('That file is not a readable screenshot.')
    identity=uuid.uuid4().hex
    folder=db.database_path().parent/'covers';folder.mkdir(exist_ok=True)
    filename=identity+'.png';(folder/filename).write_bytes(output.getvalue())
    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with db.connect() as connection:
        connection.execute('INSERT INTO covers_snapshots(id,sport,game_id,source_url,captured_at,method,filename,note) VALUES (?,?,?,?,?,?,?,?)',
            (identity,sport,game_id,source_url,timestamp,method,filename,note[:300]))
    return next(r for r in list_snapshots(sport,game_id) if r['id']==identity)

def capture_page(url,sport,game_id):
    """Runs in a worker thread, using a fresh public browser without account cookies."""
    url=validate_url(url,sport);selected=game(sport,game_id)
    try:from playwright.sync_api import sync_playwright
    except ImportError:raise ValueError('Automatic snapshots need the optional browser setup. Run enable_covers_snapshots.bat once, or upload a screenshot below.')
    try:
        with sync_playwright() as p:
            with p.chromium.launch(headless=True) as browser:
                context=browser.new_context(viewport={'width':1280,'height':900},device_scale_factor=1,accept_downloads=False)
                # Never follow a top-level redirect to another site or a private address.
                def guard(route):
                    req=route.request
                    if req.is_navigation_request() and req.frame.parent_frame is None:
                        try:validate_url(req.url,sport)
                        except ValueError:return route.abort()
                    return route.continue_()
                context.route('**/*',guard)
                page=context.new_page()
                response=page.goto(url,wait_until='domcontentloaded',timeout=30000)
                if not response or response.status>=400:raise ValueError('Covers did not allow this capture. Open the page normally and upload a screenshot instead.')
                title=page.title().lower()
                if any(x in title for x in ('just a moment','access denied','captcha','verify')):raise ValueError('Covers requires a browser check. Upload a screenshot instead; the app will not bypass it.')
                # Title must identify both teams and the game date; do not archive a generic page.
                tokens=[selected[k].split()[-1].lower() for k in ('home','away')]
                day=datetime.datetime.fromisoformat(selected['starts_at'].replace('Z','+00:00'))
                if day.tzinfo:
                    from zoneinfo import ZoneInfo
                    day=day.astimezone(ZoneInfo(db.get_settings().get('timezone','America/Chicago')))
                expected=f'{day.strftime("%B")} {day.day}, {day.year}'.lower()
                if not all(token in title for token in tokens) or expected not in title:
                    raise ValueError('The Covers page could not be matched to both teams and this date. Check the link, or upload a screenshot with a note.')
                page.locator('body').wait_for(state='visible')
                # Capture the actual matchup content, rather than a thumbnail of a
                # very tall page dominated by navigation and unrelated tickers.
                heading=page.locator('h1').first
                if heading.count():heading.evaluate('(element) => element.scrollIntoView({block:"start"})')
                raw=page.screenshot(full_page=False,type='png',timeout=15000)
                return save_image(raw,sport,game_id,url,'automatic','Visible matchup section. Matched both teams and date in page title. Capture time is not the time a sportsbook updated its price.')
    except ValueError:raise
    except Exception:
        # Never return browser traces or request URLs that could contain other data.
        raise ValueError('Automatic capture is unavailable. Run the optional browser setup, or open Covers and upload a screenshot. Your research still works.')
