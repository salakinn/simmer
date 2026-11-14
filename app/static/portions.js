// Only leading ingredient quantities are scaled; sizes and preparation notes stay intact.
const quantityToken = String.raw`(?:\d+\s+\d+\s*\/\s*\d+|\d+\s*\/\s*\d+|\d*\s*[½¼¾⅓⅔⅛⅜⅝⅞]|\d+(?:[.,]\d+)?)`;
const leadingQuantity = new RegExp(`^(\\s*(?:ca\\.?\\s*|etwa\\s*)?)(${quantityToken})(?:\\s*([–−-]|bis)\\s*(${quantityToken}))?`, 'i');
function quantityNumber(value) {
  const fractions={'½':1/2,'¼':1/4,'¾':3/4,'⅓':1/3,'⅔':2/3,'⅛':1/8,'⅜':3/8,'⅝':5/8,'⅞':7/8};
  const text=value.trim();
  const last=text.slice(-1);
  if(last in fractions)return Number(text.slice(0,-1).trim()||0)+fractions[last];
  const fraction=text.match(/^(?:(\d+)\s+)?(\d+)\s*\/\s*(\d+)$/);
  if(fraction)return Number(fraction[1]||0)+Number(fraction[2])/Number(fraction[3]);
  return Number(text.replace(',','.'));
}
function originalServings(value) {
  const match=String(value??'').trim().match(/^(\d+(?:[.,]\d+)?)(?:\s+(?:Portionen?|Personen?|Stück|servings?|portions?|people))?\s*$/i);
  const number=match?Number(match[1].replace(',','.')):NaN;
  return Number.isFinite(number)&&number>0?number:null;
}
function scaleIngredient(text, factor) {
  if(factor===1)return text;
  return text.replace(leadingQuantity,(match,prefix,first,separator,last)=>{
    const values=[first,...(last?[last]:[])].map(quantityNumber);
    if(values.some(value=>!Number.isFinite(value)))return match;
    const format=value=>new Intl.NumberFormat('de-DE',{maximumFractionDigits:3}).format(value*factor);
    return prefix+format(values[0])+(last?` ${separator} ${format(values[1])}`:'');
  });
}
if(typeof module!=='undefined')module.exports={quantityNumber,originalServings,scaleIngredient};
