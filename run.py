"""Start Courtside Edge locally at http://127.0.0.1:8765."""
import sys, os
from pathlib import Path
runtime=Path(__file__).resolve().parent/'.runtime'
if runtime.exists():sys.path.insert(0,str(runtime))
browser_cache=Path(__file__).resolve().parent/'.browsers'
if browser_cache.exists():os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(browser_cache))
import uvicorn
if __name__=='__main__':
    if os.environ.get('EDGE_OPEN_BROWSER')=='1':
        import threading, time, urllib.request, webbrowser
        def open_when_ready():
            for _ in range(80):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=1) as response:
                        if response.status==200:
                            webbrowser.open('http://127.0.0.1:8765');return
                except OSError:pass
                time.sleep(.25)
        threading.Thread(target=open_when_ready,daemon=True).start()
    uvicorn.run('app.main:app',host='127.0.0.1',port=8765,reload=False)
