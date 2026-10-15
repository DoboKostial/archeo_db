/* Shared editor for the common spatial representation model. */
(function () {
  'use strict';
  const config = window.ArcheoSpatialConfig;
  if (!config) return;
  const el = id => document.getElementById(id);
  const root = config.root.replace(/\/$/,'');
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let kind, key, data, previewMap, previewLayer;
  let loading = 0;
  const representations = () => data ? data.geometries : [];
  const chosen = () => representations().find(r=>String(r.id_geometry)===el('geometryRepresentation').value);
  const entityUrl = () => root+'/entities/'+kind+'/'+encodeURIComponent(key);
  const geometryUrl = row => entityUrl()+'/geometries/'+row.id_geometry;
  function showError(error) {
    el('geometryError').textContent = error.message || String(error);
    el('geometryError').classList.remove('d-none');
  }
  async function api(url,method='GET',body) {
    const options = {method,headers:{Accept:'application/json','X-CSRFToken':csrf}};
    if (body instanceof FormData) options.body = body;
    else if (body!==undefined) {options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body);}
    const response = await fetch(url,options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Spatial request failed.');
    return result;
  }
  async function action(fn) {
    el('geometryError').classList.add('d-none');
    document.querySelectorAll('#geometryModal button[data-spatial-write]').forEach(b=>b.disabled=true);
    try { await fn(); }
    catch(error) { showError(error); }
    finally { document.querySelectorAll('#geometryModal button[data-spatial-write]').forEach(b=>b.disabled=false); setButtons(); }
  }
  function setOptions(select,values,value) {
    select.replaceChildren();
    values.forEach(v=>select.add(new Option(v,v)));
    if (values.includes(value)) select.value=value;
  }
  function typeChanged() {
    const type = el('geometryType').value;
    const methods = type.includes('Point')?['point']:type.includes('Line')?['ordered_line']:['ordered_polygon','convex_hull'];
    setOptions(el('geometryMethod'),methods,el('geometryMethod').value);
  }
  function setButtons() {
    const row=chosen();
    el('geometryRemove').disabled=!row;
    el('geometryRebuild').disabled=!row || !row.build_method;
    const allowSource=!!row || kind==='su';
    el('geometryUpload').disabled=!allowSource;
    el('geometryLinkFile').disabled=!allowSource;
    document.querySelectorAll('[data-spatial-write]').forEach(b=>b.hidden=!config.canWrite);
  }
  function fileLink(file,target,remove) {
    const wrapper=document.createElement('div');
    const link=document.createElement('a');
    link.href=root+'/files/'+file.id_file;
    link.textContent='#'+file.id_file+' '+file.original_name;
    wrapper.append(link);
    if (file.source_software) wrapper.append(document.createTextNode(' · '+file.source_software+' '+(file.source_software_version||'')));
    if (remove && config.canWrite) {
      const button=document.createElement('button'); button.type='button';button.className='btn btn-sm btn-link text-danger';button.textContent='Unlink';
      button.addEventListener('click',()=>action(async()=>{
        await api(entityUrl()+'/files','DELETE',{id_geometry:remove==='geometry'?chosen().id_geometry:null,id_file:file.id_file});
        await load(el('geometryRepresentation').value); await refreshSummaries();
      }));
      wrapper.append(button);
    }
    target.append(wrapper);
  }
  function render() {
    const row=chosen();
    const types=kind==='polygon'?['Polygon']:['find','sample'].includes(kind)?['Point']:kind==='section'?['LineString']:['Polygon','LineString','Point','MultiPoint','MultiLineString','MultiPolygon'];
    const roles=kind==='polygon'?['top','bottom']:['find','sample'].includes(kind)?['location']:kind==='section'?['section_trace']:['outline','extent','location','other'];
    setOptions(el('geometryType'),types,row?(row.build_geometry_type || ({POINT:'Point',MULTIPOINT:'MultiPoint',LINESTRING:'LineString',MULTILINESTRING:'MultiLineString',POLYGON:'Polygon',MULTIPOLYGON:'MultiPolygon'}[row.geometry_type])):types[0]);
    setOptions(el('geometryRole'),roles,row?.geometry_role);
    typeChanged();
    if (row && row.build_method!=='legacy_line') el('geometryMethod').value=row.build_method || el('geometryMethod').value;
    el('geometryProxy').checked=row?row.is_proxy:kind!=='polygon';
    el('geometryNotes').value=row?.notes || '';
    el('geometryProvenance').textContent=row?('Source: '+row.source_method+' · '+(row.source_software || 'software unspecified')+' '+(row.source_software_version || '')):'New representation from measured points';
    const groups=new Map();
    (row?.points || []).forEach(p=>{const name=p.part_no+','+p.ring_no;if (!groups.has(name)) groups.set(name,[]);groups.get(name).push(p.ref_geopt);});
    el('geometryPoints').value=Array.from(groups,([name,ids])=>name+': '+ids.join(', ')).join('\n');
    el('geometryLegacy').textContent=row?.legacy_point_ranges?'Historical recipe: '+row.legacy_point_ranges.map(r=>r.from+'–'+r.to).join(', ')+'. Use Rebuild saved recipe, or select explicit ordered points to replace it.':'';
    el('geometryFiles').replaceChildren();
    (row?.files || []).forEach(f=>fileLink(f,el('geometryFiles'),'geometry'));
    if (kind==='su') {
      const label=document.createElement('div');label.className='text-muted mt-2';label.textContent='Files attached to the SU:';el('geometryFiles').append(label);
      data.files.forEach(f=>fileLink(f,el('geometryFiles'),'su'));
    }
    el('geometryFileScope').textContent=row?'The source file will be linked to representation #'+row.id_geometry:kind==='su'?'The source file will be linked to this SU.':'Save a representation before uploading its source file.';
    el('geometryWorldPanel').classList.toggle('d-none',kind!=='photogram');
    el('geometryWorldFile').replaceChildren();
    el('geometryHasWorld').checked=kind==='photogram' && data.files.length>0;
    if (kind==='photogram') {
      data.files.forEach(f=>fileLink(f,el('geometryWorldFile'),'world'));
      if (data.files.length) {
        const link=document.createElement('a');link.href=root+'/photograms/'+encodeURIComponent(key)+'/pair';link.textContent='Download photogram + world file (ZIP)';el('geometryWorldFile').append(link);
      }
    }
    setButtons();
    if (!previewMap && window.L) {
      previewMap=L.map('geometryPreview').setView([49.8,15.5],7);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:22}).addTo(previewMap);
    }
    if (previewLayer) previewMap.removeLayer(previewLayer);
    if (row?.preview && previewMap) {
      previewLayer=L.geoJSON(row.preview,{style:{dashArray:row.is_proxy?'5 5':null}}).addTo(previewMap);
      const bounds=previewLayer.getBounds();if(bounds.isValid()) previewMap.fitBounds(bounds,{maxZoom:20});
    }
  }
  async function load(selected=null) {
    data=await api(entityUrl());
    const select=el('geometryRepresentation');select.replaceChildren(new Option('New representation',''));
    representations().forEach(r=>select.add(new Option('#'+r.id_geometry+' · '+r.geometry_role+' · '+(r.geometry_type || 'pending')+(r.is_proxy?' · proxy':''),r.id_geometry)));
    select.value=selected===null?(representations().length?String(representations()[0].id_geometry):''):selected;
    render();
  }
  function parsePoints() {
    const points=[];
    el('geometryPoints').value.split('\n').filter(line=>line.trim()).forEach(line=>{
      const bits=line.split(':');
      if (bits.length>2) throw new Error('Use part,ring: point IDs.');
      const header=bits.length===2?bits[0].split(','):['1','0'];
      const part=Number(header[0]),ring=Number(header[1]);
      if (header.length!==2 || !Number.isInteger(part) || part<1 || !Number.isInteger(ring) || ring<0) throw new Error('Invalid part or ring number.');
      bits[bits.length-1].trim().split(/[\s,;]+/).forEach(value=>{
        const id=Number(value);if(!Number.isInteger(id) || !value) throw new Error('Enter numeric point IDs in vertex order.');
        points.push({part_no:part,ring_no:ring,ref_geopt:id});
      });
    });
    return points;
  }
  let searchTimer,searchVersion=0;
  async function searchPoints() {
    const version=++searchVersion;
    try {
      const result=await api(root+'/points?q='+encodeURIComponent(el('geometryPointSearch').value)+'&code='+encodeURIComponent(el('geometryPointCode').value));
      if(version!==searchVersion) return;
      const target=el('geometryPointResults');target.replaceChildren();
      result.rows.forEach(p=>{
        const button=document.createElement('button');button.type='button';button.className='list-group-item list-group-item-action py-1 small';
        button.textContent=p.id_pts+' · '+(p.code||'')+' · '+(p.notes||'')+' · Z '+(p.h ?? 'unknown');
        button.disabled=!config.canWrite;
        button.addEventListener('click',()=>{const textarea=el('geometryPoints');textarea.value+=(textarea.value.trim()?', ':'')+p.id_pts;});
        target.append(button);
      });
    } catch(error) {showError(error);}
  }
  async function refreshSummaries() {
    const nodes=Array.from(document.querySelectorAll('[data-geometry-status]'));
    await Promise.all(Array.from(new Set(nodes.map(n=>n.dataset.geometryStatus))).map(async type=>{
      try {
        const result=await api(root+'/summary/'+type);
        const rows=new Map(result.rows.map(r=>[r.entity_id,r]));
        nodes.filter(n=>n.dataset.geometryStatus===type).forEach(node=>{
          const r=rows.get(node.dataset.geometryKey);
          node.textContent=r?(r.count?r.types.join(', ')+' ('+r.count+')':'NO')+(r.pending?' · '+r.pending+' pending':'')+(r.has_world_file?' · world file':''):'NO';
          node.title='Geometry stored in the common spatial model';
        });
      } catch(error) {
        nodes.filter(n=>n.dataset.geometryStatus===type).forEach(n=>{n.textContent='Unavailable';n.title=error.message;});
      }
    }));
  }
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-geometry-kind]');
    if(button) {
      const version=++loading;kind=button.dataset.geometryKind;key=button.dataset.geometryKey;
      ['geometrySoftware','geometrySoftwareVersion','geometryExistingFile','geometryFile','geometryWorldUpload'].forEach(id=>el(id).value='');
      el('geometryTitle').textContent='Define geometry · '+kind+' '+key;
      el('geometryError').classList.add('d-none');
      bootstrap.Modal.getOrCreateInstance(el('geometryModal')).show();
      el('geometryRepresentation').replaceChildren();
      const defaults={polygon:'EP',su:'SU',section:'PR',find:'FI',sample:'SP',photogram:'FO',drawing:'FX'};
      el('geometryPointCode').value=defaults[kind];
      try {await load();if(version===loading) await searchPoints();} catch(error) {showError(error);}
    }
    const bulk=event.target.closest('[data-spatial-rebuild]');
    if(bulk) {
      bulk.disabled=true;
      try {
        const url=root+'/rebuild/'+bulk.dataset.spatialRebuild;
        const scope=await api(url);
        if (!confirm('Rebuild '+scope.buildable+' of '+scope.total+' representations for ALL '+bulk.dataset.spatialRebuild+' entities in this database (all pages and filters)?\n'+scope.manual+' existing representations may contain GIS edits. These edits will be replaced; source method will become survey_points. Geometries without a point recipe will be skipped.')) return;
        const result=await api(url,'POST',{confirmed:true});
        alert('Built: '+result.built+'; no recipe: '+result.skipped+'; failed: '+result.errors.length+(result.errors.length?'\n'+result.errors.map(e=>'#'+e.id+' '+e.entity_id+': '+e.error).join('\n'):''));
        await refreshSummaries();
      } catch(error) {alert(error.message);}
      finally {bulk.disabled=false;}
    }
  });
  document.addEventListener('DOMContentLoaded',()=>{
    if(!el('geometryModal')) return;
    el('geometryModal').addEventListener('shown.bs.modal',()=>{if(previewMap) previewMap.invalidateSize();});
    el('geometryRepresentation').addEventListener('change',render);
    el('geometryType').addEventListener('change',typeChanged);
    el('geometryPointSearch').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(searchPoints,200);});
    el('geometryPointCode').addEventListener('change',searchPoints);
    el('geometrySave').addEventListener('click',()=>action(async()=>{
      const row=chosen();
      if(row?.geometry_type && !confirm('Replace the saved geometry using these points and change its source method to survey_points? Any GIS edits will be overwritten.')) return;
      const result=await api(entityUrl(),'POST',{id_geometry:row?.id_geometry,geometry_type:el('geometryType').value,
        geometry_role:el('geometryRole').value,build_method:el('geometryMethod').value,is_proxy:el('geometryProxy').checked,
        notes:el('geometryNotes').value,points:parsePoints(),replace_manual:!!row});
      await load(String(result.id_geometry));await refreshSummaries();
    }));
    el('geometryRebuild').addEventListener('click',()=>action(async()=>{
      const row=chosen();if(!row || !confirm('Rebuild the saved point recipe? Geometry edits will be replaced and source method will become survey_points.')) return;
      await api(geometryUrl(row)+'/rebuild','POST',{replace_manual:true});await load(String(row.id_geometry));await refreshSummaries();
    }));
    el('geometryRemove').addEventListener('click',()=>action(async()=>{
      const row=chosen();if(!row || !confirm('Remove representation #'+row.id_geometry+'? Source measurements and files are retained.')) return;
      await api(geometryUrl(row),'DELETE');await load();await refreshSummaries();
    }));
    async function uploadFile(world=false,existing=false) {
      const form=new FormData();
      if(existing) form.append('id_file',el('geometryExistingFile').value);
      else {
        const file=el(world?'geometryWorldUpload':'geometryFile').files[0];if(!file) throw new Error('Select a file.');
        form.append('file',file);
      }
      if(!world && chosen()) form.append('id_geometry',chosen().id_geometry);
      form.append('source_software',el('geometrySoftware').value);form.append('source_software_version',el('geometrySoftwareVersion').value);
      await api(entityUrl()+'/files','POST',form);await load(el('geometryRepresentation').value);await refreshSummaries();
    }
    el('geometryUpload').addEventListener('click',()=>action(()=>uploadFile()));
    el('geometryLinkFile').addEventListener('click',()=>action(()=>uploadFile(false,true)));
    el('geometryUploadWorld').addEventListener('click',()=>action(()=>uploadFile(true)));
    refreshSummaries();setButtons();
    const observer=new MutationObserver(records=>{
      if(records.some(r=>Array.from(r.addedNodes).some(n=>n.nodeType===1 && (n.matches('[data-geometry-status]') || n.querySelector('[data-geometry-status]'))))) {
        clearTimeout(observer.timer);observer.timer=setTimeout(refreshSummaries,100);
      }
    });
    document.querySelectorAll('#tbodyFinds,#tbodySamples').forEach(n=>observer.observe(n,{childList:true,subtree:true}));
  });
}());
