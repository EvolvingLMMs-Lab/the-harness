import {harness} from './figures/harness.js?v=activity4';
if(!document.querySelector('[data-home-figure]'))await new Promise(resolve=>document.addEventListener('DOMContentLoaded',resolve,{once:true}));
const instances=[...document.querySelectorAll('[data-home-figure]')].map(el=>harness(el,{hold:Number(el.dataset.homeFigure),activity:el.dataset.homeFigure==='-1'}));
addEventListener('pagehide',event=>{if(!event.persisted)instances.forEach(instance=>instance.destroy())});
