import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {field,select} from '../components/common/fields.js';import {ZONES} from '../constants/enums.js';
function codeCell(s){return s.archive_task_id?`${esc(s.code||'—')} <span class="tag tag-ok">已归档</span>`:esc(s.code||'—')}
export function render(){
 const online=state.ships.filter(s=>!s.archive_task_id);
 return `<div class=split><section class=panel><h2>${online.length} 个在线班次 / 共 ${state.ships.length} 行（含归档占位）</h2>
 <p class=notice>归档后在线明细被清理，但保留自增 ID 与编号占用（编号挪入归档区），新班次不会复用旧编号。归档操作见「班次归档」页。</p>
 <div class=scroll><table><thead><tr><th>班次号</th><th>配送线路</th><th>温区</th><th>驾驶员</th></tr></thead><tbody>
 ${state.ships.map(s=>`<tr><td>${codeCell(s)}</td><td>${esc(s.route||'—')}</td><td>${esc(s.zone||'—')}</td><td>${esc(s.driver||'—')}</td></tr>`).join('')||'<tr><td>暂无记录。请在右侧录入首条数据。</td></tr>'}</tbody></table></div>
 </section><aside class=side><h2>录入运输班次</h2><p>先建立班次，再录入温控与货损样本。</p><form id=ship>${field('班次编号','code','text','required')}${field('配送线路','route','text','required')}${select('温区','zone',ZONES.map(z=>[z,z]))}${field('驾驶员','driver','text','required')}<button class=primary>保存班次</button></form></aside></div>`}
