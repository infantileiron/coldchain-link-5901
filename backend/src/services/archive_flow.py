import json,os,hashlib
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from src.constants.enums import ARCHIVE_PACKAGE_VERSION
from src.models.entities import (ArchiveTask,ArchivedShipment,ArchivedSample,
 Shipment,Sample)
from src.services.archive import (now,package_path,read_checksum,as_json,
 paired_stats,verify_archived_tables,mark_failed)
from src.services.analysis import analyze
def _start(s,row,stage):
 if row.state!='running':
  row.state='running';row.stage=stage;row.updated=now();s.commit()
def _progress(row,key,val):
 # JSON 列原地变更需显式标记，否则 SQLAlchemy 不会持久化
 p=as_json(row.progress);p[key]=val;row.progress=p;flag_modified(row,'progress')
def _before_stats(ships,samples):
 rows=[{'exposure':r.exposure,'excursions':r.excursions,'loss':r.loss} for r in samples]
 return {f:paired_stats(rows,f) for f in ('exposure','excursions')}
def _after_stats(s,zone):
 from src.services.archive import study_rows
 rows=study_rows(s,zone)
 return {f:paired_stats(rows,f) for f in ('exposure','excursions')}
def run_archiving(s,row):
 try:
  ids=list(as_json(row.shipment_ids) if isinstance(row.shipment_ids,str) else (row.shipment_ids or []))
  ships=s.query(Shipment).filter(Shipment.id.in_(ids)).all()
  got={r.id:r for r in ships}
  if set(got)!=set(ids):mark_failed(s,row,'所选班次已不存在，任务终止');return
  # 允许本任务已部分归档（重试续跑）；被其他任务占用才终止
  foreign={r.id for r in ships if r.archive_task_id and r.archive_task_id!=row.id}
  if foreign:mark_failed(s,row,'部分班次已被其他任务归档，任务终止');return
  samples=s.query(Sample).filter(Sample.shipment_id.in_(ids)).all()
  if any(r.archive_task_id and r.archive_task_id!=row.id for r in samples):
   mark_failed(s,row,'部分样本已被其他任务归档，任务终止');return
  _start(s,row,'packing')
  _progress(row,'before',_before_stats(ships,samples));s.commit()
  # 阶段 1：归档表搬迁，唯一约束兜底，重试不重复
  existing={a.origin_shipment_id for a in s.query(ArchivedShipment).filter_by(task_id=row.id).all()}
  for r in ships:
   if r.id in existing:continue
   s.add(ArchivedShipment(task_id=row.id,origin_shipment_id=r.id,code=r.code,route=r.route,zone=r.zone,driver=r.driver))
  ex_samples={(a.task_id,a.origin_sample_id) for a in s.query(ArchivedSample).filter_by(task_id=row.id).all()}
  for r in samples:
   if (row.id,r.id) in ex_samples:continue
   s.add(ArchivedSample(task_id=row.id,origin_sample_id=r.id,origin_shipment_id=r.shipment_id,
    code=r.code,exposure=r.exposure,excursions=r.excursions,loss=r.loss))
  try:s.commit()
  except IntegrityError:s.rollback();mark_failed(s,row,'归档写入冲突，任务终止');return
  # 刷新会话，丢弃可能过期的在线 ORM 状态（重试时在线行可能已被本任务清空）
  s.expire_all()
  # 阶段 2 起一切以归档表为唯一事实来源：快照、编号集合、数量均从归档表重建，重试天然幂等
  a_ships=s.query(ArchivedShipment).filter_by(task_id=row.id).all()
  a_samples=s.query(ArchivedSample).filter(ArchivedSample.task_id==row.id,
   ArchivedSample.origin_shipment_id.in_(ids)).all()
  ship_codes={a.code for a in a_ships};sample_codes={a.code for a in a_samples}
  # 阶段 2：归档包先写临时文件，校验通过后原子替换；已存在且校验一致则跳过（重试不重复搬迁）
  path=package_path(row.id);tmp=path+'.tmp'
  if not (os.path.exists(path) and not os.path.exists(tmp) and _package_ok(row,path,sample_codes,len(a_ships))):
   pkg={'version':ARCHIVE_PACKAGE_VERSION,'task_id':row.id,'kind':'archiving','created':now(),
    'snapshot':{
     'shipments':[{'id':a.origin_shipment_id,'code':a.code,'route':a.route,'zone':a.zone,'driver':a.driver} for a in a_ships],
     'samples':[{'id':a.origin_sample_id,'shipment_id':a.origin_shipment_id,'code':a.code,
      'exposure':a.exposure,'excursions':a.excursions,'loss':a.loss} for a in a_samples]}}
   body=json.dumps(pkg,ensure_ascii=False,indent=2).encode('utf-8')
   digest=hashlib.sha256(body).hexdigest()  # 校验和覆盖正文，写在末行之外
   with open(tmp,'wb') as f:
    f.write(body);f.write(b'\n"checksum":"'+digest.encode()+b'"\n')
    f.flush();os.fsync(f.fileno())
   os.replace(tmp,path)
  digest,_=read_checksum(path)
  row.stage='verifying';row.package_path=path;row.checksum=digest;row.updated=now();s.commit()
  # 核验归档表与归档包完整（此时在线明细尚未清理，不检查在线）
  ok,msg=verify_archived_tables(s,row.id,ids,check_online=False)
  pkg_ok,pkg_msg=_verify_package(row,path,sample_codes,len(a_ships))
  if not (ok and pkg_ok):mark_failed(s,row,'归档核验失败：'+(msg or pkg_msg));return
  # 先在「在线仍活跃」状态下算好迁移后配对数与关联结果：在线+归档数据一致，读数完整且无窗口
  row.stage='cleaning'
  after={}
  zones={a.zone for a in a_ships}
  for zone in sorted(zones):after[zone]=_after_stats(s,zone)
  _progress(row,'after',after)
  compare={}
  rows=_task_union_rows(s,row.id,ids)
  for feat in ('exposure','excursions'):
   try:compare[feat]=analyze(rows,feat)
   except ValueError as e:compare[feat]={'error':str(e)}
  _progress(row,'association',compare)
  # 阶段 3 与收尾合并为单事务原子提交：打在线归档标记与置 done 同时可见，杜绝交接窗口漏样本
  live_ships=s.query(Shipment).filter(Shipment.id.in_(ids)).all()
  live_samples=s.query(Sample).filter(Sample.shipment_id.in_(ids)).all()
  for r in live_ships:
   if r.archive_task_id==row.id:continue
   r.archive_task_id=row.id
  for r in live_samples:
   if r.archive_task_id==row.id:continue
   r.archive_task_id=row.id
  # 提交前复核（同会话可见未提交的标记）：在线不得残留活跃明细，归档表与包仍须完整
  ok,msg=verify_archived_tables(s,row.id,ids,check_online=True)
  pkg_ok,pkg_msg=_verify_package(row,path,sample_codes,len(a_ships))
  if not (ok and pkg_ok):
   s.rollback();mark_failed(s,row,'清理后复核失败：'+(msg or pkg_msg));return
  row.state='done';row.stage='finished';row.error='';row.updated=now()
  try:s.commit()
  except IntegrityError:s.rollback();mark_failed(s,row,'在线清理冲突，任务终止');return
 except Exception as e:
  s.rollback();mark_failed(s,row,f'归档中断：{e}')
def _task_union_rows(s,task_id,ids):
 # 迁移后该任务班次样本的唯一视图：归档表为主，在线恢复记录优先，按样本编号去重
 rows={}
 for a in s.query(ArchivedSample).filter(ArchivedSample.task_id==task_id,
   ArchivedSample.origin_shipment_id.in_(ids)).all():
  rows[a.code]={'code':a.code,'exposure':a.exposure,'excursions':a.excursions,'loss':a.loss}
 for r in s.query(Sample).filter(Sample.shipment_id.in_(ids)).all():
  if r.code:rows[r.code]={'code':r.code,'exposure':r.exposure,'excursions':r.excursions,'loss':r.loss}
 return list(rows.values())
def _package_ok(row,path,sample_codes,ship_count):
 try:return _verify_package(row,path,sample_codes,ship_count)[0]
 except OSError:return False
def _verify_package(row,path,sample_codes,ship_count):
 from src.services.archive import read_checksum
 try:digest,pkg=read_checksum(path)
 except ValueError as e:return False,str(e)
 except (OSError,json.JSONDecodeError):return False,'归档包无法读取'
 snap=pkg.get('snapshot') or {}
 if pkg.get('version')!=ARCHIVE_PACKAGE_VERSION:return False,'归档包版本不支持'
 if len(snap.get('shipments') or [])!=ship_count:return False,'归档中班次数量不一致'
 if len(snap.get('samples') or [])!=len(sample_codes):return False,'归档中样本数量不一致'
 if {x['code'] for x in snap['samples']}!=sample_codes:return False,'归档样本编号不一致'
 return True,''
def run_restoring(s,row):
 try:
  ids=set(as_json(row.shipment_ids) if isinstance(row.shipment_ids,str) else (row.shipment_ids or []))
  # 白名单：本恢复任务自身，以及来源归档任务（在线占位行正常由其持有）
  source=as_json(row.progress).get('source_task_id')
  if not source:mark_failed(s,row,'恢复任务缺少来源归档任务标识，拒绝执行');return
  allowed={None,row.id,source}
  # 并发守卫：在线占位行若被其他任务占用，直接失败，绝不覆盖更正/其他归档
  for sid in ids:
   online=s.get(Shipment,sid)
   if online and online.archive_task_id not in allowed:
    mark_failed(s,row,f'班次 {online.code or sid} 正被其他任务占用，恢复终止');return
  # 重试幂等：只处理来源归档任务中、仍在归档表的班次；已恢复的自然跳过，重试不重复搬迁
  arch_ships=s.query(ArchivedShipment).filter(ArchivedShipment.task_id==source,
   ArchivedShipment.origin_shipment_id.in_(ids)).all()
  if row.state!='running':
   row.state='running';row.stage='verifying';row.updated=now();s.commit()
  # 恢复先核验归档包；缺失或损坏拒绝恢复，不能悄悄放行
  from src.services.archive import load_package
  pkg,_=load_package(s,row.package_path or package_path(row.id))
  snap=pkg.get('snapshot') or {}
  if arch_ships:
   want_codes={a.code for a in arch_ships}
   if not want_codes.issubset({x['code'] for x in snap.get('shipments') or []}):
    mark_failed(s,row,'归档包内容与归档表不一致，拒绝恢复');return
   row.stage='restoring'
   source_task_ids={a.task_id for a in arch_ships}
   before_rows=[{'exposure':a.exposure,'excursions':a.excursions,'loss':a.loss} for a in
    s.query(ArchivedSample).filter(ArchivedSample.task_id.in_(source_task_ids),
     ArchivedSample.origin_shipment_id.in_(ids)).all()]
   before={f:paired_stats(before_rows,f) for f in ('exposure','excursions')}
   # 恢复整班次：占位行编号本就保留，回填业务字段并清除归档标记
   for a in arch_ships:
    online=s.get(Shipment,a.origin_shipment_id)
    if not online:mark_failed(s,row,f'在线班次占位 {a.origin_shipment_id} 缺失，无法恢复');return
    if online.archive_task_id not in allowed:
     mark_failed(s,row,f'班次 {a.code} 已被其他任务占用，恢复终止');return
    online.route=a.route;online.zone=a.zone;online.driver=a.driver
    online.archive_task_id=None
   arch_samples=s.query(ArchivedSample).filter(ArchivedSample.task_id.in_(source_task_ids),
    ArchivedSample.origin_shipment_id.in_(ids)).all()
   for a in arch_samples:
    online=s.get(Sample,a.origin_sample_id)
    if not online:
     s.add(Sample(id=a.origin_sample_id,shipment_id=a.origin_shipment_id,code=a.code,
      exposure=a.exposure,excursions=a.excursions,loss=a.loss))
     continue
    if online.archive_task_id not in allowed:
     mark_failed(s,row,f'样本 {a.code} 已被其他任务占用，恢复终止');return
    online.shipment_id=a.origin_shipment_id
    online.exposure=a.exposure;online.excursions=a.excursions;online.loss=a.loss
    online.archive_task_id=None
   # 删除归档表记录；任务与归档包保留为审计轨迹（与在线回填同一事务，失败整体回滚）
   restored_samples=len(arch_samples);restored_ships=len(arch_ships)
   for a in arch_samples:s.delete(a)
   for a in arch_ships:s.delete(a)
  else:
   # 全部班次此前已恢复：直接收尾，不报错、不重复搬迁
   before=None;restored_ships=0;restored_samples=0
  after_rows=[{'exposure':r.exposure,'excursions':r.excursions,'loss':r.loss}
   for r in s.query(Sample).filter(Sample.shipment_id.in_(ids)).all()]
  after={f:paired_stats(after_rows,f) for f in ('exposure','excursions')}
  compare={f:{'before':(before or {}).get(f),'after':after[f]} for f in ('exposure','excursions')}
  # 合并写回，保留 source_task_id 等既有字段，保证重试仍可定位来源归档
  progress=as_json(row.progress)
  progress.update({'restored_shipments':restored_ships,'restored_samples':restored_samples,'compare':compare})
  row.progress=progress;flag_modified(row,'progress')
  # 单事务原子提交：在线回填、归档表删除、任务 done 同时可见，交接窗口不漏不重
  row.state='done';row.stage='finished';row.error='';row.updated=now()
  try:s.commit()
  except IntegrityError as e:s.rollback();mark_failed(s,row,f'恢复写入冲突（编号可能已被新班次占用）：{e.orig}');return
 except Exception as e:
  s.rollback();mark_failed(s,row,f'恢复中断：{e}')
