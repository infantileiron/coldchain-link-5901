import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {api,post} from '../api/client.js';
import {ARCHIVE_STATE_LABEL,ARCHIVE_KIND_LABEL,ARCHIVE_STAGE_LABEL} from '../constants/enums.js';
function fail(e){const el=document.querySelector('#error');if(el)el.textContent=e.message;}
function badge(s){const tone=s==='failed'?'tag-danger':s==='done'?'tag-ok':'tag';return `<span class="${tone}">${esc(ARCHIVE_STATE_LABEL[s]||s)}</span>`}
function stat(v){return v==null?'—':`配对 ${v.paired} / 共 ${v.total}（排除 ${v.excluded}）`}
function compareBlock(cmp,assoc){
 if(!cmp)return '<p class=notice>暂无对比数据。</p>';
 const rows=['exposure','excursions'].map(f=>{
  const label=f==='exposure'?'暴露时长':'超温次数';
  const a=(assoc&&assoc[f])||null;
  const assocText=a? (a.error?`关联诊断：${esc(a.error)}`:`Pearson r=${a.pearson}，ρ=${a.spearman}，n=${a.n}`):'关联结果随归档计算';
  return `<tr><td>${label}</td><td>${stat(cmp[f]&&cmp[f].before)}</td><td>${stat(cmp[f]&&cmp[f].after)}</td><td>${esc(assocText)}</td></tr>`;
 }).join('');
 return `<div class=scroll><table><thead><tr><th>变量</th><th>迁移前</th><th>迁移后</th><th>关联结果</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function taskCard(t){
 const active=t.state==='queued'||t.state==='running';
 const readonly=state.user.role==='viewer';
 const canRestore=!readonly&&t.kind==='archiving'&&t.state==='done';
 const canRetry=!readonly&&t.state==='failed';
 const assoc=(t.progress&&t.progress.association)||null;
 const restoreShips=t.kind==='archiving'
  ? (state.archiveOverview.archived.filter(a=>a.task_id===t.id).map(a=>a.origin_shipment_id)):[];
 return `<article class="rec">
  <h3>#${t.id} ${esc(ARCHIVE_KIND_LABEL[t.kind]||t.kind)}任务 ${badge(t.state)} <span class=eyebrow>${esc(ARCHIVE_STAGE_LABEL[t.stage]||t.stage||'')}</span></h3>
  <p>班次 ${(t.shipment_ids||[]).length} 个 · 创建人 ${esc(t.actor||'—')} · 校验和 <code>${esc((t.checksum||'').slice(0,16)||'—')}</code></p>
  ${t.error?`<p class="error">${esc(t.error)}</p>`:''}
  ${active?'<p class=notice>任务进行中，页面会自动刷新进度；中断后可在失败时重试，已搬迁数据不会重复。</p>':''}
  ${compareBlock(t.compare,assoc)}
  <p class=actions>
   ${canRetry?`<button data-retry="${t.id}" data-kind="${esc(t.kind)}">重试任务</button>`:''}
   ${canRestore&&restoreShips.length?`<button data-restore="${t.id}">恢复整班次</button>`:''}
   ${canRestore&&!restoreShips.length?'<span class=eyebrow>该任务班次均已恢复</span>':''}
   ${readonly?'<span class=eyebrow>观察员只读，不能归档或恢复</span>':''}
  </p></article>`;
}
export function render(){
 const online=state.ships.filter(s=>!s.archive_task_id);
 const archived=state.archiveOverview.archived||[];
 const doneArchive=state.archiveTasks.filter(t=>t.kind==='archiving'&&t.state==='done');
 return `<div class=split>
 <section class=panel>
  <h2>归档任务与迁移对比 / ${state.archiveTasks.length}</h2>
  <p class=notice>归档先写归档包并核验完整，再清理在线明细；编号占用保留。新研究同时纳入在线与归档样本，每条只计一次。</p>
  ${state.archiveTasks.length?state.archiveTasks.map(taskCard).join(''):'<p>暂无归档任务。在右侧选择班次创建。</p>'}
  <h3 style="margin-top:26px">已归档班次 / ${archived.length}</h3>
  <div class=scroll><table><thead><tr><th>班次号</th><th>线路</th><th>温区</th><th>样本数</th><th>来源任务</th></tr></thead>
  <tbody>${archived.map(a=>`<tr><td>${esc(a.code)}</td><td>${esc(a.route)}</td><td>${esc(a.zone)}</td><td>${a.samples}</td><td>#${a.task_id}</td></tr>`).join('')||'<tr><td>暂无已归档班次。</td></tr>'}</tbody></table></div>
 </section>
 <aside class=side>
  <h2>归档所选班次</h2>
  <p class=eyebrow>仅列出仍在线的班次，可多选</p>
  <form id=archive-form>
   <div class=checklist>${online.map(s=>`<label class=check><input type=checkbox name=shipment_ids value="${s.id}"> ${esc(s.code)} · ${esc(s.zone)} · ${esc(s.route)}</label>`).join('')||'<p>没有可归档的在线班次。</p>'}</div>
   <button class=primary>创建归档任务</button>
  </form>
  <h2 style="margin-top:24px">恢复整班次</h2>
  <p class=eyebrow>归档后更正样本需先恢复整班次；恢复与归档并发不会覆盖更正。</p>
  <form id=restore-form>
   <label>来源归档任务<select name=task_id id=restore-task>${doneArchive.map(t=>`<option value="${t.id}">#${t.id}（${(t.shipment_ids||[]).length} 班次）</option>`).join('')||'<option value="">无可恢复任务</option>'}</select></label>
   <div class=checklist id=restore-ships></div>
   <p class=eyebrow>不勾选则恢复该任务下全部仍归档班次</p>
   <button class=primary>创建恢复任务</button>
  </form>
 </aside></div>`;
}
export async function bind(){
 const af=document.querySelector('#archive-form');
 if(af)af.onsubmit=async e=>{e.preventDefault();
  const ids=[...new FormData(af).getAll('shipment_ids').map(Number)];
  if(!ids.length)return document.querySelector('#error').textContent='请至少选择一个班次';
  try{await post('/archives',{shipment_ids:ids});await refresh();}catch(err){fail(err);}};
 const rt=document.querySelector('#restore-task');
 const box=document.querySelector('#restore-ships');
 async function drawRestoreShips(){
  if(!rt||!box)return;
  const tid=Number(rt.value);if(!tid){box.innerHTML='';return;}
  const ships=(state.archiveOverview.archived||[]).filter(a=>a.task_id===tid);
  box.innerHTML=ships.map(a=>`<label class=check><input type=checkbox name=shipment_ids value="${a.origin_shipment_id}" checked> ${esc(a.code)} · ${esc(a.zone)}</label>`).join('')||'<p>该任务班次均已恢复。</p>';
 }
 if(rt){rt.onchange=drawRestoreShips;drawRestoreShips();}
 const rf=document.querySelector('#restore-form');
 if(rf)rf.onsubmit=async e=>{e.preventDefault();
  const fd=new FormData(rf);const task_id=Number(fd.get('task_id'));
  if(!task_id)return document.querySelector('#error').textContent='请选择来源归档任务';
  const shipment_ids=fd.getAll('shipment_ids').map(Number);
  try{await post('/restores',{task_id,shipment_ids:shipment_ids.length?shipment_ids:null});await refresh();}catch(err){fail(err);}};
 document.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async()=>{
  const kind=b.dataset.kind;
  try{await post(kind==='archiving'?`/archives/${b.dataset.retry}/retry`:`/restores/${b.dataset.retry}/retry`,{});await refresh();}catch(err){fail(err);}});
 document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=async()=>{
  try{await post('/restores',{task_id:Number(b.dataset.restore),shipment_ids:null});await refresh();}catch(err){fail(err);}});
}
async function refresh(){
 const [tasks,overview]=await Promise.all([api('/archives/tasks'),api('/archives/overview')]);
 state.archiveTasks=tasks;state.archiveOverview=overview;
 const main=document.querySelector('main');
 main.innerHTML=render();await bind();
}
