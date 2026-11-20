"""Opt-in Firefox/Chromium smoke test for the actual shared modal and JavaScript."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
from threading import Thread
import time

import pytest
from flask import render_template


BROWSER = os.environ.get('ARCHEODB_TEST_BROWSER_ENGINE',
                         'chromium' if shutil.which('chromium') else 'firefox')


def _firefox_result(html, assets, tmp_path):
    """Collect the test result over localhost without requiring WebDriver."""
    results = Queue()
    responses = {}
    for name, uri in assets.items():
        route = '/assets/' + name
        html = html.replace(uri, route)
        responses[route] = ('application/javascript', Path(uri.removeprefix('file://')).read_bytes())
    html += '''<script>
      const resultNode=document.getElementById('result');
      const resultObserver=new MutationObserver(()=>{
        if(resultNode.textContent==='RUNNING') return;
        resultObserver.disconnect();
        const request=new XMLHttpRequest();
        request.open('POST','/result');
        request.send(resultNode.textContent);
      });
      resultObserver.observe(resultNode,{childList:true,subtree:true,characterData:true});
      </script>'''
    responses['/'] = ('text/html; charset=utf-8', html.encode())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            response = responses.get(self.path)
            if response is None:
                self.send_error(404)
                return
            content_type, body = response
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/result':
                self.send_error(404)
                return
            body = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode()
            self.send_response(204)
            self.end_headers()
            results.put(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    profile = tmp_path / 'firefox-profile'
    profile.mkdir()
    try:
        with (tmp_path / 'firefox.log').open('w+') as log:
            process = subprocess.Popen([shutil.which('firefox'), '--headless', '--no-remote',
                '--profile', str(profile), f'http://127.0.0.1:{server.server_port}/'],
                stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        return results.get(timeout=0.2)
                    except Empty:
                        pass
                log.seek(0)
                pytest.fail('Firefox did not report a result: ' + log.read()[-4000:])
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.skipif(os.environ.get('ARCHEODB_TEST_BROWSER')!='1' or not shutil.which(BROWSER),
                    reason='Set ARCHEODB_TEST_BROWSER=1 and install Firefox or Chromium')
def test_shared_modal_selects_existing_representation_and_confirms_rebuild(app,tmp_path):
    with app.test_request_context():
        modal=render_template('partials/geometry_modal.html')
    static=Path(app.static_folder)
    bootstrap=(static/'js/bootstrap.bundle.min.js').as_uri()
    spatial=(static/'js/spatial.js').as_uri()
    photograms=(static/'js/photograms.js').as_uri()
    html='''<!doctype html><meta name="csrf-token" content="test">
      <pre id="result">RUNNING</pre>
      <button id="open" data-geometry-kind="su" data-geometry-key="11">Define geometry</button>
      <span data-geometry-status="su" data-geometry-key="11"></span>'''+modal+'''
      <script>
      let calls=[], errors=[];
      window.addEventListener('error',e=>errors.push(e.message));
      window.addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
      window.ArcheoSpatialConfig={root:'/spatial',canWrite:true};
      window.confirm=()=>true;
      window.fetch=async function(url,options) {
        calls.push({url,options});
        let body={};
        if(url.includes('/summary/')) body={rows:[{entity_id:'11',types:['POLYGON'],count:1,pending:0}]};
        else if(url.includes('/points?')) body={rows:[]};
        else if(options.method==='POST') body={id_geometry:7};
        else body={files:[],geometries:[{id_geometry:7,geometry_type:'POLYGON',geometry_role:'outline',source_method:'digitized',
          is_proxy:false,build_geometry_type:'Polygon',build_method:'ordered_polygon',files:[],
          points:[1,2,3,4].map((id,i)=>({ref_geopt:id,part_no:1,ring_no:0,point_order:i+1}))}]};
        return {ok:true,json:async()=>body};
      };
      </script>
      <script src="'''+bootstrap+'''"></script>
      <script src="'''+photograms+'''"></script>
      <script src="'''+spatial+'''"></script>
      <script>
      document.addEventListener('DOMContentLoaded',async()=>{
        const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
        try {
          document.getElementById('open').click();await sleep(50);
          if(document.getElementById('geometryRepresentation').value!=='7') throw Error('Existing representation was not selected');
          if(document.getElementById('geometryType').value!=='Polygon') throw Error('Polygon type was not selected');
          if(document.getElementById('geometryPoints').value!=='1, 2, 3, 4') throw Error('Saved points were not shown as a simple sequence');
          if(document.getElementById('geometryRebuild').textContent!=='Recalculate') throw Error('Recalculate label was not updated');
          document.getElementById('geometryPoints').value='4, 3\\n2 1';
          document.getElementById('geometrySave').click();await sleep(50);
          const saved=calls.find(c=>c.options.method==='POST');
          if(!saved) throw Error('Save did not call the API');
          const payload=JSON.parse(saved.options.body);
          if(payload.id_geometry!==7 || payload.points.length!==4 || !payload.replace_manual) throw Error('Invalid save payload');
          if(payload.points.map(p=>p.ref_geopt).join(',')!=='4,3,2,1' || payload.points.some(p=>p.part_no!==1 || p.ring_no!==0)) throw Error('Point order or grouping changed');
          if(errors.length) throw Error(errors.join('; '));
          document.getElementById('result').textContent='PASS: existing polygon, ordered points, confirmed save';
        } catch(error) { document.getElementById('result').textContent='FAIL: '+error.message; }
      });
      </script>'''
    if BROWSER == 'firefox':
        result = _firefox_result(html, {'bootstrap.js':bootstrap, 'photograms.js':photograms,
                                      'spatial.js':spatial}, tmp_path)
        assert result == 'PASS: existing polygon, ordered points, confirmed save', result
        return
    page=tmp_path/'spatial.html'
    page.write_text(html)
    profile=tmp_path/'chrome-profile'
    result=subprocess.run(['chromium','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
        '--allow-file-access-from-files','--no-first-run','--no-default-browser-check',
        '--user-data-dir='+str(profile),'--virtual-time-budget=1500','--dump-dom',page.as_uri()],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr[-2000:]
    assert 'PASS: existing polygon, ordered points, confirmed save' in result.stdout,result.stdout[-5000:]
