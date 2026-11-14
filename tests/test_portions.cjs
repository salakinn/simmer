const {test}=require('node:test');
const assert=require('node:assert/strict');
const {scaleIngredient,originalServings}=require('../app/static/portions.js');
test('scales decimals, fractions, ranges and quantities without spaces',()=>{
 for(const [input,output] of [
 ['250 g Mehl','375 g Mehl'],['1,5 l Wasser','2,25 l Wasser'],
 ['1/2 TL Salz','0,75 TL Salz'],['1 1/2 EL Öl','2,25 EL Öl'],
 ['½ Zitrone','0,75 Zitrone'],['1½ Äpfel','2,25 Äpfel'],
 ['2–3 Eier','3 – 4,5 Eier'],['2 bis 4 EL Milch','3 bis 6 EL Milch'],
 ['200g Mehl','300g Mehl'],['ca. 100 g Butter','ca. 150 g Butter'],
 ['Salz nach Geschmack','Salz nach Geschmack'],['2 Eier (Größe 3)','3 Eier (Größe 3)']
 ])assert.equal(scaleIngredient(input,1.5),output);
});
test('keeps originals and safely handles invalid fractions',()=>{
 assert.equal(scaleIngredient('½ TL Salz',1),'½ TL Salz');
 assert.equal(scaleIngredient('1/0 TL Salz',2),'1/0 TL Salz');
 assert.equal(scaleIngredient('100 g Mehl',.5),'50 g Mehl');
});
test('recognizes unambiguous servings and requires input for ranges',()=>{
 assert.equal(originalServings('4 Portionen'),4);
 assert.equal(originalServings('2 servings'),2);
 assert.equal(originalServings('2,5'),2.5);
 for(const text of [null,'','4–6 Portionen','1 Kuchen','0'])assert.equal(originalServings(text),null);
});
