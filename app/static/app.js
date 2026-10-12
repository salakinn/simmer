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
  const image = r.has_image ? `<img class="card-image" src="/api/recipes/${r.id}/image" alt="">` : '<div class="card-placeholder">✦</div>';
  return `<a class="recipe-card" href="/recipes/${r.id}">${image}<div class="card-body"><small>${esc(r.source_name || 'Rezept')}</small><h3>${esc(r.title)}</h3><p>${r.total_minutes != null ? `${minutes(r.total_minutes)} · ` : ''}${r.ingredients.length} Zutaten</p></div></a>`;
}
async function loadHome() {
  const list=document.getElementById('recipe-list');
  try { const recipes=await api('/api/recipes'); list.innerHTML=recipes.length?recipes.map(card).join(''):'<p class="empty">Noch keine Rezepte gespeichert. Importiere deinen ersten Link.</p>'; }
  catch(e){list.textContent=e.message;}
  const form=document.getElementById('import-form');
  form.addEventListener('submit',async e=>{
    e.preventDefault(); const button=form.querySelector('button'); const error=document.getElementById('form-error'); error.textContent=''; button.disabled=true; button.firstChild.textContent='Import läuft… ';
    try {const recipe=await api('/api/recipes/import',{method:'POST',body:JSON.stringify({url:document.getElementById('url').value})}); location.href=`/recipes/${recipe.id}`;}
    catch(err){error.textContent=err.message;button.disabled=false;button.firstChild.textContent='Rezept importieren ';}
  });
}
function metadata(r){return [['Portionen',r.servings],['Vorbereitung',minutes(r.prep_minutes)],['Kochen',minutes(r.cook_minutes)],['Gesamt',minutes(r.total_minutes)],['Autor',r.author]].filter(x=>x[1]).map(x=>`<span>${esc(x[0])}: ${esc(x[1])}</span>`).join('');}
function renderDetail(r){
  const root=document.getElementById('detail-content');
  root.innerHTML=`<div class="detail-hero ${r.has_image?'':'no-image'}">${r.has_image?`<img src="/api/recipes/${r.id}/image" alt="${esc(r.title)}">`:''}<div><p class="eyebrow">${esc(r.categories.join(' · ')||r.source_name||'Rezept')}</p><h1>${esc(r.title)}</h1>${r.description?`<p class="description">${esc(r.description)}</p>`:''}<div class="metadata">${metadata(r)}</div><div class="actions"><a class="button" href="/api/recipes/${r.id}/pdf">PDF herunterladen ↓</a><button class="button secondary" id="edit-button">Rezept bearbeiten</button><button class="button danger" id="delete-button">Löschen</button></div></div></div><div class="recipe-content"><section><h2>Zutaten</h2><ul>${r.ingredients.map(x=>`<li>${esc(x.text)}</li>`).join('')}</ul></section><section><h2>Zubereitung</h2><ol>${r.steps.map(x=>`<li>${esc(x.text)}</li>`).join('')}</ol></section></div>${r.source_url?`<p class="source">Quelle: <a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">${esc(r.source_name||r.source_url)}</a></p>`:''}`;
  document.getElementById('edit-button').onclick=()=>renderEdit(r);
  document.getElementById('delete-button').onclick=async()=>{if(!confirm('Dieses Rezept wirklich löschen?'))return;try{await api(`/api/recipes/${r.id}`,{method:'DELETE'});location.href='/';}catch(e){document.getElementById('page-error').textContent=e.message;}};
}
function field(label,name,value='',type='text'){return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}"></div>`;}
function area(label,name,value='',hint='',long=false){return `<div class="field"><label for="${name}">${label}</label>${hint?`<p class="hint">${hint}</p>`:''}<textarea id="${name}" name="${name}" class="${long?'long':''}">${esc(value)}</textarea></div>`;}
function renderEdit(r){
 const root=document.getElementById('detail-content');
 root.innerHTML=`<form id="edit-form" class="edit-form"><p class="eyebrow">Rezept bearbeiten</p><h1>${esc(r.title)}</h1>${field('Rezeptname','title',r.title)}${area('Beschreibung','description',r.description||'')}<div class="edit-grid">${field('Quelle','source_name',r.source_name||'')}${field('Ursprüngliche URL','source_url',r.source_url||'')}${field('Autor','author',r.author||'')}${field('Portionen','servings',r.servings||'')}${field('Vorbereitung (Minuten)','prep_minutes',r.prep_minutes??'','number')}${field('Kochzeit (Minuten)','cook_minutes',r.cook_minutes??'','number')}${field('Gesamtzeit (Minuten)','total_minutes',r.total_minutes??'','number')}${field('Bild-URL','image_url',r.image_url||'')}</div>${field('Kategorien, kommagetrennt','categories',r.categories.join(', '))}${field('Tags, kommagetrennt','tags',r.tags.join(', '))}${area('Zutaten','ingredients',r.ingredients.map(x=>x.text).join('\n'),'Eine Zutat pro Zeile',true)}${area('Zubereitungsschritte','steps',r.steps.map(x=>x.text).join('\n'),'Ein Schritt pro Zeile',true)}<div class="actions"><button class="button" type="submit">Änderungen speichern</button><button class="button secondary" id="cancel-button" type="button">Abbrechen</button></div><p id="edit-error" class="error" role="alert"></p></form>`;
 document.getElementById('cancel-button').onclick=()=>renderDetail(r);
 document.getElementById('edit-form').onsubmit=async e=>{e.preventDefault();const form=e.target;const value=k=>form.elements[k].value.trim(); const lines=k=>value(k).split('\n').map(x=>x.trim()).filter(Boolean);const number=k=>value(k)===''?null:Number(value(k));const body={...r,title:value('title'),description:value('description')||null,source_name:value('source_name')||null,source_url:value('source_url')||null,author:value('author')||null,servings:value('servings')||null,prep_minutes:number('prep_minutes'),cook_minutes:number('cook_minutes'),total_minutes:number('total_minutes'),image_url:value('image_url')||null,categories:value('categories').split(',').map(x=>x.trim()).filter(Boolean),tags:value('tags').split(',').map(x=>x.trim()).filter(Boolean),ingredients:lines('ingredients').map(text=>({text})),steps:lines('steps').map(text=>({text}))};try{const updated=await api(`/api/recipes/${r.id}`,{method:'PUT',body:JSON.stringify(body)});renderDetail(updated);}catch(err){document.getElementById('edit-error').textContent=err.message;}};
}
async function loadDetail(){try{renderDetail(await api(`/api/recipes/${document.body.dataset.recipeId}`));}catch(e){document.getElementById('page-error').textContent=e.message;}}
if(document.getElementById('import-form'))loadHome();else if(document.body.dataset.recipeId)loadDetail();
