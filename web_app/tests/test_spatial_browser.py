"""Opt-in Chromium smoke test for the actual shared modal and JavaScript."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from flask import render_template


@pytest.mark.skipif(os.environ.get('ARCHEODB_TEST_BROWSER')!='1' or not shutil.which('chromium'),
                    reason='Set ARCHEODB_TEST_BROWSER=1 and install Chromium')
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
          document.getElementById('geometrySave').click();await sleep(50);
          const saved=calls.find(c=>c.options.method==='POST');
          if(!saved) throw Error('Save did not call the API');
          const payload=JSON.parse(saved.options.body);
          if(payload.id_geometry!==7 || payload.points.length!==4 || !payload.replace_manual) throw Error('Invalid save payload');
          if(errors.length) throw Error(errors.join('; '));
          document.getElementById('result').textContent='PASS: existing polygon, ordered points, confirmed save';
        } catch(error) { document.getElementById('result').textContent='FAIL: '+error.message; }
      });
      </script>'''
    page=tmp_path/'spatial.html'
    page.write_text(html)
    profile=tmp_path/'chrome-profile'
    result=subprocess.run(['chromium','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
        '--allow-file-access-from-files','--no-first-run','--no-default-browser-check',
        '--user-data-dir='+str(profile),'--virtual-time-budget=1500','--dump-dom',page.as_uri()],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr[-2000:]
    assert 'PASS: existing polygon, ordered points, confirmed save' in result.stdout,result.stdout[-5000:]
