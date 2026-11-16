import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {field,select} from '../components/common/fields.js';
export function render(){
 const onlineShips=state.ships.filter(s=>!s.archive_task_id);
 const cell=(v)=>v==null?'—':esc(v);
 return `<div class=split><section class=panel><h2>原始记录 / ${state.samples.filter(s=>!s.archive_task_id).length} 条在线（共 ${state.samples.length} 行含归档占位）</h2><p>缺失保留为空；相关计算只排除当前变量与货损的缺失配对。已归档样本不在在线明细更正，需先在「班次归档」恢复整班次。</p>
 <div class=scroll><table><thead><tr><th>样本号</th><th>暴露分钟</th><th>超温次数</th><th>货损 %</th></tr></thead><tbody>
 ${state.samples.map(s=>`<tr><td>${s.archive_task_id?`${esc(s.code||'—')} <span class="tag tag-ok">已归档</span>`:esc(s.code||'—')}</td><td>${cell(s.exposure)}</td><td>${cell(s.excursions)}</td><td>${cell(s.loss)}</td></tr>`).join('')}</tbody></table></div>
 </section><aside class=side><h2>采集样本</h2><form id=sample>${select('所属班次',onlineShips.map(s=>[s.id,s.code]))}${field('样本编号','code','text','required')}${field('暴露分钟（可空）','exposure','number','min=0 max=1440 step=0.1')}${field('超温次数（可空）','excursions','number','min=0 max=100')}${field('损耗率 %（可空）','loss','number','min=0 max=100 step=0.01')}<button class=primary>保存样本</button></form></aside></div>`}
