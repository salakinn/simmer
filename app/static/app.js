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
  try {
    const recipes=await api('/api/recipes');
    const search=document.getElementById('recipe-search');
    const normalize=value=>value.normalize('NFKD').replace(/\p{M}/gu,'').toLocaleLowerCase('de');
    const render=()=>{
      const terms=normalize(search.value).trim().split(/\s+/).filter(Boolean);
      const matches=recipes.filter(r=>{
        const text=normalize([r.title,...r.ingredients.map(x=>x.text)].join(' '));
        return terms.every(term=>text.includes(term));
      });
      list.innerHTML=matches.length?matches.map(card).join(''):`<p class="empty">${recipes.length?'Keine passenden Rezepte gefunden.':'Noch keine Rezepte gespeichert. Füge dein erstes Rezept hinzu.'}</p>`;
      document.getElementById('search-status').textContent=`${matches.length} ${matches.length===1?'Rezept':'Rezepte'}`;
    };
    search.addEventListener('input',render);render();
  } catch(e){list.textContent=e.message;}
}

function metadata(r){return [['Portionen',r.servings],['Vorbereitung',minutes(r.prep_minutes)],['Kochen',minutes(r.cook_minutes)],['Gesamt',minutes(r.total_minutes)],['Backtemperatur',r.oven_temperature == null?'':`${r.oven_temperature} °C`],['Backzeit',minutes(r.bake_minutes)],['Heizart',r.oven_mode],['Autor',r.author]].filter(x=>x[1]).map(x=>`<span>${esc(x[0])}: ${esc(x[1])}</span>`).join('');}
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
  root.innerHTML=`<div class="recipe-heading"><h1>${esc(r.title)}</h1><div class="metadata">${metadata(r)}</div></div><div class="recipe-content"><section><h2>Zutaten</h2><div id="portion-calculator"></div><ul id="scaled-ingredients">${ingredientGroups(r.ingredients)}</ul></section><section><h2>Zubereitung</h2><ol>${r.steps.map(x=>`<li>${esc(x.text)}</li>`).join('')}</ol></section></div><div class="actions"><a class="button" href="/api/recipes/${r.id}/pdf">PDF herunterladen ↓</a><button class="button secondary" id="edit-button">Rezept bearbeiten</button><button class="button danger" id="delete-button">Löschen</button></div>${r.has_image?`<img class="recipe-photo" src="/api/recipes/${r.id}/image?v=${r.version}" alt="${esc(r.title)}">`:''}${r.source_url?`<p class="source">Quelle: <a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">${esc(r.source_name||r.source_url)}</a></p>`:''}`;
  setupPortionCalculator(r);
   document.getElementById('edit-button').onclick=()=>renderEdit(r);
  document.getElementById('delete-button').onclick=async()=>{if(!confirm('Dieses Rezept wirklich löschen?'))return;try{await api(`/api/recipes/${r.id}`,{method:'DELETE'});location.href='/';}catch(e){document.getElementById('page-error').textContent=e.message;}};
}
function setupPortionCalculator(r) {
  const base=originalServings(r.servings);
  const root=document.getElementById('portion-calculator');
  if(base===null) {
    root.innerHTML='<p class="portion-hint">Zum Umrechnen bitte die Portionszahl unter „Rezept bearbeiten“ ergänzen.</p>';
    return;
  }
  root.innerHTML=`<div class="portion-inputs"><div><label for="target-portions">Gewünschte Portionen</label><input id="target-portions" type="number" min="0.1" step="any" value="${base}" aria-describedby="portion-status"></div></div><p class="portion-hint" id="portion-status" role="status"></p><button type="button" class="button secondary portion-reset">Zurücksetzen</button>`;
  const target=root.querySelector('#target-portions');
  function update() {
    const to=Number(target.value);
    const valid=Number.isFinite(to)&&to>0&&Number.isFinite(to/base);
    document.getElementById('scaled-ingredients').innerHTML=ingredientGroups(r.ingredients.map(item=>({...item,text:valid?scaleIngredient(item.text,to/base):item.text})));
    root.querySelector('#portion-status').textContent=valid?`Originalrezept: ${base.toLocaleString('de-DE')} Portionen. Angaben ohne Menge bleiben unverändert.`:'Bitte eine gültige Portionszahl eingeben.';
  }
  target.addEventListener('input',update);
  root.querySelector('.portion-reset').onclick=()=>{target.value=base;update();};
  update();
}
function field(label,name,value='',type='text'){return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}"></div>`;}
function area(label,name,value='',hint='',long=false){return `<div class="field"><label for="${name}">${label}</label>${hint?`<p class="hint">${hint}</p>`:''}<textarea id="${name}" name="${name}" class="${long?'long':''}">${esc(value)}</textarea></div>`;}
function imagePickerMarkup(r) {
  const limit=Number(document.body.dataset.maxImageBytes || 5242880);
  const image=r.image_upload || (r.has_image?`/api/recipes/${r.id}/image?v=${r.version}`:null);
  return `<div class="field image-picker"><label for="recipe-image">Rezeptbild</label><div id="image-drop" class="image-drop"><input id="recipe-image" type="file" accept="image/jpeg,image/png,image/webp" aria-describedby="image-hint image-error"><label for="recipe-image" class="image-drop-label"><img id="image-preview" ${image?`src="${esc(image)}"`:'hidden'} alt="Vorschau des Rezeptbilds"><span>Bild hierher ziehen oder <strong>Datei auswählen</strong></span><span id="image-hint" class="hint">JPG, PNG oder WebP · bis ${Math.round(limit/1024/1024*10)/10} MB · ein Bild pro Rezept</span></label></div><button id="remove-image" class="button secondary" type="button" ${image?'':'hidden'}>Bild entfernen</button><p id="image-error" class="error" role="alert"></p></div>`;
}
function setupImagePicker(root,r) {
  const state={upload:r.image_upload||null,remove:false,reading:Promise.resolve()};
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
function linkImportMarkup(r) {
  return `<form id="import-form" class="import-panel"><label for="url">Rezeptlink (optional)</label><div class="input-row"><input id="url" type="url" placeholder="https://…" value="${esc(r.source_url||'')}" required><button type="submit">Daten übernehmen</button></div><p id="form-error" class="error" role="alert"></p>${r.source_url?'<p class="import-status" role="status">Daten übernommen. Du kannst sie jetzt anpassen und speichern.</p>':''}</form>`;
}
function renderEdit(r, creating=false) {
  const root=document.getElementById('detail-content');
  root.innerHTML=`<div class="recipe-entry">${creating?'<h1>Rezept erfassen</h1>'+linkImportMarkup(r):''}<form id="edit-form" class="edit-form">${creating?'':`<h1>${esc(r.title)}</h1>`}${field('Rezeptname','title',r.title)}${area('Zutaten','ingredients',ingredientLines(r.ingredients),'Eine Zutat pro Zeile; Gruppenüberschriften in [eckigen Klammern].',true)}${area('Zubereitungsschritte','steps',r.steps.map(x=>x.text).join('\n'),'Ein Schritt pro Zeile',true)}<div class="edit-grid">${field('Portionen','servings',r.servings||'')}${field('Vorbereitung (Minuten)','prep_minutes',r.prep_minutes??'','number')}${field('Kochzeit (Minuten)','cook_minutes',r.cook_minutes??'','number')}${field('Gesamtzeit (Minuten)','total_minutes',r.total_minutes??'','number')}</div><fieldset class="baking-fields"><legend>Backen (optional)</legend><div class="edit-grid">${field('Temperatur (°C)','oven_temperature',r.oven_temperature??'','number')}${field('Backdauer (Minuten)','bake_minutes',r.bake_minutes??'','number')}<div class="field"><label for="oven_mode">Heizart</label><select id="oven_mode" name="oven_mode"><option value="">Bitte wählen</option>${['Ober-/Unterhitze','Umluft'].map(mode=>`<option ${r.oven_mode===mode?'selected':''}>${mode}</option>`).join('')}</select></div></div></fieldset>${imagePickerMarkup(r)}<div class="actions"><button class="button" type="submit">${creating?'Rezept speichern':'Änderungen speichern'}</button><button class="button secondary" id="cancel-button" type="button">Abbrechen</button></div><p id="edit-error" class="error" role="alert"></p></form></div>`;
  const form=root.querySelector('#edit-form');
  const imageState=setupImagePicker(root,r);
  let dirty=false;
  form.addEventListener('input',()=>{dirty=true;});
  form.addEventListener('change',()=>{dirty=true;});
  root.querySelector('#image-drop').addEventListener('drop',()=>{dirty=true;});
  root.querySelector('#remove-image').addEventListener('click',()=>{dirty=true;});
  root.querySelector('#cancel-button').onclick=()=>{if(creating)location.href='/';else renderDetail(r);};
  for(const name of ['title','ingredients','steps']) form.elements[name].required=true;
  form.elements.title.maxLength=500;
  for(const input of form.querySelectorAll('input[type=number]')) {input.min='0';input.step='1';}

  form.elements.oven_temperature.min='1';form.elements.oven_temperature.max='500';

  if(creating) {
    const importForm=root.querySelector('#import-form');
    importForm.onsubmit=async event=>{
      event.preventDefault();
      if(dirty&&!confirm('Vorhandene Eingaben durch die Daten aus dem Rezeptlink ersetzen?'))return;
      const button=importForm.querySelector('button');
      const error=root.querySelector('#form-error');
      error.textContent='';
      const controls=[...form.querySelectorAll('input, textarea, select, button')];
      controls.forEach(control=>{control.disabled=true;});
      button.disabled=true;button.textContent='Wird geladen…';
      try {
        const preview=await api('/api/recipes/preview',{method:'POST',body:JSON.stringify({url:importForm.elements.url.value.trim()})});
        renderEdit(preview,true);
      } catch(err) {
        error.textContent=err.message;
      } finally {
        controls.forEach(control=>{control.disabled=false;});
        button.disabled=false;button.textContent='Daten übernehmen';
      }
    };
  }

  form.onsubmit=async event=>{
    event.preventDefault();
    const value=key=>form.elements[key].value.trim();
    const lines=key=>value(key).split('\n').map(x=>x.trim()).filter(Boolean);
    const number=key=>value(key)===''?null:Number(value(key));
    const body={...r,title:value('title'),
      servings:value('servings')||null,prep_minutes:number('prep_minutes'),
      cook_minutes:number('cook_minutes'),total_minutes:number('total_minutes'),
      oven_temperature:number('oven_temperature'),bake_minutes:number('bake_minutes'),oven_mode:value('oven_mode')||null,
      ingredients:parseIngredients(value('ingredients')),steps:lines('steps').map(text=>({text}))};
    const error=root.querySelector('#edit-error');
    error.textContent='';
    if(!body.ingredients.length||!body.steps.length) {
      error.textContent='Bitte mindestens eine Zutat und einen Zubereitungsschritt eingeben.';
      return;
    }
    const button=form.querySelector('[type=submit]');
    button.disabled=true;button.textContent='Wird gespeichert…';
    const importButton=root.querySelector('#import-form button');
    if(importButton)importButton.disabled=true;
    try {
      await imageState.reading;
      body.image_upload=imageState.upload;body.remove_image=imageState.remove;
      const updated=await api(creating?'/api/recipes':`/api/recipes/${r.id}`,{method:creating?'POST':'PUT',body:JSON.stringify(body)});
      if(creating)location.href=`/recipes/${updated.id}`;else renderDetail(updated);
    } catch(err) {
      error.textContent=err.message;
    } finally {
      button.disabled=false;button.textContent=creating?'Rezept speichern':'Änderungen speichern';
      if(importButton)importButton.disabled=false;
    }
  };
}
async function loadDetail(){try{renderDetail(await api(`/api/recipes/${document.body.dataset.recipeId}`));}catch(e){document.getElementById('page-error').textContent=e.message;}}
if(document.body.dataset.newRecipe)renderEdit({title:'',source_type:'manual',ingredients:[],steps:[],categories:[],tags:[]},true);else if(document.getElementById('recipe-list'))loadHome();else if(document.body.dataset.recipeId)loadDetail();
