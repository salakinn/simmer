const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const minutes = n => n == null ? '' : `${n} Min.`;
async function api(path, options={}) {
  const res = await fetch(path, {headers:{'Content-Type':'application/json'},...options});
  if (!res.ok) {
    const body = await res.json().catch(()=>({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : body.fields?.map(x=>x.message).join(', ') || 'Ein Fehler ist aufgetreten.');
  }
  return res.status === 204 ? null : res.json();
}
function card(r) {
  const image = r.has_image ? `<img class="card-image" src="/api/recipes/${r.id}/image?v=${r.version}" alt="">` : '';
  return `<a class="recipe-card" href="/recipes/${r.id}">${image}<div class="card-body"><h3>${esc(r.title)}</h3><p>${r.total_minutes != null ? `${minutes(r.total_minutes)} · ` : ''}${r.ingredients.length} Zutaten</p></div></a>`;
}
async function loadHome() {
  const list=document.getElementById('recipe-list');
  try { const recipes=await api('/api/recipes'); list.innerHTML=recipes.length?recipes.map(card).join(''):'<p class="empty">Noch keine Rezepte gespeichert. Importiere einen Link oder erfasse dein erstes Rezept manuell.</p>'; }
  catch(e){list.textContent=e.message;}
  const form=document.getElementById('import-form');
  form.addEventListener('submit',async e=>{
    e.preventDefault(); const button=form.querySelector('button'); const error=document.getElementById('form-error'); error.textContent=''; button.disabled=true; button.firstChild.textContent='Import läuft… ';
    try {const recipe=await api('/api/recipes/import',{method:'POST',body:JSON.stringify({url:document.getElementById('url').value})}); location.href=`/recipes/${recipe.id}`;}
    catch(err){error.textContent=err.message;button.disabled=false;button.firstChild.textContent='Rezept importieren ';}
  });
}
function metadata(r){return [['Portionen',r.servings],['Vorbereitung',minutes(r.prep_minutes)],['Kochen',minutes(r.cook_minutes)],['Gesamt',minutes(r.total_minutes)],['Autor',r.author]].filter(x=>x[1]).map(x=>`<span>${esc(x[0])}: ${esc(x[1])}</span>`).join('');}
function ingredientGroups(items) {
  let previous;
  return items.map((item, index) => {
    const heading = (index === 0 || item.group !== previous) && item.group ? `<li class="ingredient-heading"><strong>${esc(item.group)}</strong></li>` : '';
    previous = item.group;
    return heading + `<li>${esc(item.text)}</li>`;
  }).join('');
}
function ingredientLines(items) {
  let previous;
  return items.flatMap((item, index) => {
    const heading = index === 0 || item.group !== previous ? [`[${item.group || ''}]`] : [];
    previous = item.group;
    return [...heading, item.text];
  }).join('\n');
}
function parseIngredients(text) {
  let group = null;
  return text.split('\n').map(line=>line.trim()).filter(Boolean).flatMap(line=>{
    if (line.startsWith('[') && line.endsWith(']')) {group=line.slice(1,-1).trim() || null; return [];}
    return [{text:line, group}];
  });
}
function renderDetail(r){
  const root=document.getElementById('detail-content');
  root.innerHTML=`<div class="detail-hero ${r.has_image?'':'no-image'}">${r.has_image?`<img src="/api/recipes/${r.id}/image?v=${r.version}" alt="${esc(r.title)}">`:''}<div><p class="eyebrow">${esc(r.categories.join(' · ')||r.source_name||'Rezept')}</p><h1>${esc(r.title)}</h1>${r.description?`<p class="description">${esc(r.description)}</p>`:''}<div class="metadata">${metadata(r)}</div><div class="actions"><a class="button" href="/api/recipes/${r.id}/pdf">PDF herunterladen ↓</a><button class="button secondary" id="edit-button">Rezept bearbeiten</button><button class="button danger" id="delete-button">Löschen</button></div></div></div><div class="recipe-content"><section><h2>Zutaten</h2><ul>${r.ingredients.map(x=>`<li>${esc(x.text)}</li>`).join('')}</ul></section><section><h2>Zubereitung</h2><ol>${r.steps.map(x=>`<li>${esc(x.text)}</li>`).join('')}</ol></section></div>${r.source_url?`<p class="source">Quelle: <a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">${esc(r.source_name||r.source_url)}</a></p>`:''}`;
   root.querySelector('.recipe-content section ul').innerHTML=ingredientGroups(r.ingredients);
   document.getElementById('edit-button').onclick=()=>renderEdit(r);
  document.getElementById('delete-button').onclick=async()=>{if(!confirm('Dieses Rezept wirklich löschen?'))return;try{await api(`/api/recipes/${r.id}`,{method:'DELETE'});location.href='/';}catch(e){document.getElementById('page-error').textContent=e.message;}};
}
function field(label,name,value='',type='text'){return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}"></div>`;}
function area(label,name,value='',hint='',long=false){return `<div class="field"><label for="${name}">${label}</label>${hint?`<p class="hint">${hint}</p>`:''}<textarea id="${name}" name="${name}" class="${long?'long':''}">${esc(value)}</textarea></div>`;}
function imagePickerMarkup(r) {
  const limit=Number(document.body.dataset.maxImageBytes || 5242880);
  return `<div class="field image-picker"><label for="recipe-image">Rezeptbild</label><div id="image-drop" class="image-drop"><input id="recipe-image" type="file" accept="image/jpeg,image/png,image/webp" aria-describedby="image-hint image-error"><label for="recipe-image" class="image-drop-label"><img id="image-preview" ${r.has_image?`src="/api/recipes/${r.id}/image?v=${r.version}"`: 'hidden'} alt="Vorschau des Rezeptbilds"><span>Bild hierher ziehen oder <strong>Datei auswählen</strong></span><span id="image-hint" class="hint">JPG, PNG oder WebP · bis ${Math.round(limit/1024/1024*10)/10} MB · ein Bild pro Rezept</span></label></div><button id="remove-image" class="button secondary" type="button" ${r.has_image?'':'hidden'}>Bild entfernen</button><p id="image-error" class="error" role="alert"></p></div>`;
}
function setupImagePicker(root,r) {
  const state={upload:null,remove:false,reading:Promise.resolve()};
  const input=root.querySelector('#recipe-image');
  const drop=root.querySelector('#image-drop');
  const preview=root.querySelector('#image-preview');
  const remove=root.querySelector('#remove-image');
  const error=root.querySelector('#image-error');
  const limit=Number(document.body.dataset.maxImageBytes || 5242880);
  let revision=0;
  function select(files) {
    const current=++revision;
    error.textContent='';
    state.reading=(async()=>{
      if(files.length!==1) throw new Error('Bitte genau ein Bild auswählen.');
      const file=files[0];
      if(!['image/jpeg','image/png','image/webp'].includes(file.type)) throw new Error('Bitte ein JPG-, PNG- oder WebP-Bild auswählen.');
      if(file.size>limit) throw new Error('Das Bild ist zu groß. Bitte ein kleineres Bild auswählen.');
      const data=await new Promise((resolve,reject)=>{
        const reader=new FileReader();
        reader.onload=()=>resolve(reader.result);
        reader.onerror=()=>reject(new Error('Das Bild konnte nicht gelesen werden.'));
        reader.readAsDataURL(file);
      });
      const image=new Image();image.src=data;
      await image.decode().catch(()=>{throw new Error('Die Datei ist kein gültiges Bild.');});
      if(current!==revision)return;
      state.upload=data;state.remove=false;
      preview.src=data;preview.hidden=false;remove.hidden=false;
    })().catch(e=>{if(current===revision)error.textContent=e.message;});
    input.value='';
  }
  input.onchange=()=>{if(input.files.length)select(Array.from(input.files));};
  for(const name of ['dragenter','dragover'])drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('dragging');});
  drop.addEventListener('dragleave',e=>{if(!drop.contains(e.relatedTarget))drop.classList.remove('dragging');});
  drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('dragging');select(Array.from(e.dataTransfer.files));});
  remove.onclick=()=>{revision++;state.upload=null;state.remove=true;preview.hidden=true;preview.removeAttribute('src');remove.hidden=true;error.textContent='';input.value='';};
  return state;
}
function renderEdit(r, creating=false){
 const root=document.getElementById('detail-content');
 root.innerHTML=`<form id="edit-form" class="edit-form"><p class="eyebrow">${creating?'Dein eigenes Rezept':'Rezept bearbeiten'}</p><h1>${creating?'Neues Rezept':esc(r.title)}</h1><p>${creating?'Rezeptname, Zutaten und Zubereitung sind Pflichtfelder. Alle weiteren Angaben sind optional.':''}</p>${field('Rezeptname','title',r.title)}${area('Beschreibung','description',r.description||'')}<div class="edit-grid">${field('Portionen','servings',r.servings||'')}${field('Vorbereitung (Minuten)','prep_minutes',r.prep_minutes??'','number')}${field('Kochzeit (Minuten)','cook_minutes',r.cook_minutes??'','number')}${field('Gesamtzeit (Minuten)','total_minutes',r.total_minutes??'','number')}</div>${imagePickerMarkup(r)}${field('Kategorien, kommagetrennt','categories',r.categories.join(', '))}${field('Tags, kommagetrennt','tags',r.tags.join(', '))}${area('Zutaten','ingredients',r.ingredients.map(x=>x.text).join('\n'),'Eine Zutat pro Zeile',true)}${area('Zubereitungsschritte','steps',r.steps.map(x=>x.text).join('\n'),'Ein Schritt pro Zeile',true)}<div class="actions"><button class="button" type="submit">${creating?'Rezept speichern':'Änderungen speichern'}</button><button class="button secondary" id="cancel-button" type="button">Abbrechen</button></div><p id="edit-error" class="error" role="alert"></p></form>`;
  root.querySelector('#ingredients').value=ingredientLines(r.ingredients);
  root.querySelector('#ingredients').previousElementSibling.textContent='Eine Zutat pro Zeile; Gruppenüberschriften in [eckigen Klammern].';
  document.getElementById('cancel-button').onclick=()=>{if(creating)location.href='/';else renderDetail(r);};
  for(const name of ['title','ingredients','steps']) root.querySelector(`#${name}`).required=true;
  root.querySelector('#title').maxLength=500;
  for(const input of root.querySelectorAll('input[type=number]')) {input.min='0';input.step='1';}
  const imageState=setupImagePicker(root,r);
  if(creating) root.querySelector('#title').focus();
  document.getElementById('edit-form').onsubmit=async e=>{e.preventDefault();const form=e.target;const value=k=>form.elements[k].value.trim(); const lines=k=>value(k).split('\n').map(x=>x.trim()).filter(Boolean);const number=k=>value(k)===''?null:Number(value(k));const body={...r,title:value('title'),description:value('description')||null,servings:value('servings')||null,prep_minutes:number('prep_minutes'),cook_minutes:number('cook_minutes'),total_minutes:number('total_minutes'),categories:value('categories').split(',').map(x=>x.trim()).filter(Boolean),tags:value('tags').split(',').map(x=>x.trim()).filter(Boolean),ingredients:parseIngredients(value('ingredients')),steps:lines('steps').map(x=>({text:x}))};const error=document.getElementById('edit-error');error.textContent='';if(!body.ingredients.length||!body.steps.length){error.textContent='Bitte mindestens eine Zutat und einen Zubereitungsschritt eingeben.';return;}const button=form.querySelector('[type=submit]');button.disabled=true;button.textContent='Wird gespeichert…';try{await imageState.reading;body.image_upload=imageState.upload;body.remove_image=imageState.remove;const updated=await api(creating?'/api/recipes':`/api/recipes/${r.id}`,{method:creating?'POST':'PUT',body:JSON.stringify(body)});if(creating)location.href=`/recipes/${updated.id}`;else renderDetail(updated);}catch(err){error.textContent=err.message;}finally{button.disabled=false;button.textContent=creating?'Rezept speichern':'Änderungen speichern';}};
}
async function loadDetail(){try{renderDetail(await api(`/api/recipes/${document.body.dataset.recipeId}`));}catch(e){document.getElementById('page-error').textContent=e.message;}}
if(document.body.dataset.newRecipe)renderEdit({title:'',source_type:'manual',ingredients:[],steps:[],categories:[],tags:[]},true);else if(document.getElementById('import-form'))loadHome();else if(document.body.dataset.recipeId)loadDetail();
