const assert = require('node:assert/strict');
const {layout, coordinate} = require('./agenda.js');
const base = {date:'2026-09-30',timeZone:'America/Sao_Paulo',windows:[{start:32400,end:43200},{start:46800,end:64800}],appointments:[]};
assert.deepEqual(layout({...base,windows:[]}).blocks, []);
const plan=layout(base);
assert.deepEqual(plan.blocks.map(b=>[b.kind,b.start,b.end]), [['free',32400,43200],['closed',43200,46800],['free',46800,64800]]);
assert.equal(coordinate('2026-09-30T12:15:00Z',base.date,base.timeZone),33300);
const appointments=[20,40,60].map((duration,i)=>({cliente:'Cliente',servico:'Serviço',valor:'40,00',status:'CONFIRMADO',inicio:`2026-09-30T${String(9+i).padStart(2,'0')}:00:00-03:00`,fim:`2026-09-30T${String(9+i+Math.floor(duration/60)).padStart(2,'0')}:${String(duration%60).padStart(2,'0')}:00-03:00`}));
const blocks=layout({...base,appointments}).blocks.filter(b=>b.kind==='booked');
assert.equal(blocks[1].height,blocks[0].height*2);assert.equal(blocks[2].height,blocks[0].height*3);
assert(blocks[1].top>blocks[0].top);
const real=layout({...base,windows:[{start:32820,end:35220}]});
assert(Math.abs(real.height-56)<1e-8); // 40 real minutes, not a multiple of any fixed slot.
console.log('Agenda JS: intervalos, lacunas, timezone e proporções 20/40/60 min OK.');

// No-show remains visible and retains its real interval in the day's history.
{
  const noShowPlan = require('./agenda.js').layout({date:'2026-09-30', timeZone:'America/Sao_Paulo', windows:[{start:32400,end:36000}], appointments:[{inicio:'2026-09-30T12:00:00Z',fim:'2026-09-30T12:40:00Z',status:'NAO_COMPARECEU'}]});
  const absent = noShowPlan.blocks.find(b => b.kind === 'no-show');
  if (!absent || absent.end - absent.start !== 2400 || noShowPlan.blocks.filter(b=>b.kind==='free').some(b=>b.start<34800)) throw new Error('Invalid no-show layout');
}
