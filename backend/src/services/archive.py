import json,hashlib,os,re,hmac
from datetime import datetime,timezone
from fastapi import HTTPException
from src.constants.enums import ACTIVE_ARCHIVE_STATES,ARCHIVE_PACKAGE_VERSION,ARTIFACT_DIR
from src.models.entities import (ArchiveTask,ArchivedShipment,ArchivedSample,
 Shipment,Sample)
def now():return datetime.now(timezone.utc).isoformat()
def as_json(value):
 # MySQL JSON 列返回对象，SQLite 等以字符串存储；统一归一化，避免重试时取不到任务字段
 if value is None:return {}
 if isinstance(value,str):
  try:return json.loads(value)
  except json.JSONDecodeError:return {}
 return value
_CHECKSUM_TAIL=re.compile(rb'\n"checksum":"([0-9a-f]{64})"\n?\Z')
def read_checksum(path):
 # 归档包为「JSON 正文 + 末行校验和」；校验和只覆盖正文，自身不参与哈希
 with open(path,'rb') as f:raw=f.read()
 m=_CHECKSUM_TAIL.search(raw)
 if not m:raise ValueError('归档包缺少校验和尾行')
 body=raw[:m.start()]
 digest=hashlib.sha256(body).hexdigest()
 got=m.group(1).decode()
 if not hmac.compare_digest(digest,got):raise ValueError('归档包校验和不匹配（内容损坏）')
 return got,json.loads(body.decode('utf-8'))
def package_path(task_id):return os.path.join(ARTIFACT_DIR,f'archive-{task_id}.json')
def task_dump(row):return {c.name:getattr(row,c.name) for c in row.__table__.columns}
def active_tasks(s):
 return s.query(ArchiveTask).filter(ArchiveTask.state.in_(ACTIVE_ARCHIVE_STATES)).all()
def assert_no_conflict(s,shipment_ids):
 ids=set(shipment_ids)
 for t in active_tasks(s):
  if ids.intersection(set(as_json(t.shipment_ids) if isinstance(t.shipment_ids,str) else (t.shipment_ids or []))):
   raise HTTPException(409,f'班次存在进行中的归档/恢复任务 #{t.id}，请等待完成后再操作')
def online_shipment(s,ship_id):
 row=s.get(Shipment,ship_id)
 if not row:raise HTTPException(404,f'班次 {ship_id} 不存在')
 return row
def paired_stats(rows,feature):
 # 与研究口径一致：feature 与货损均非空的配对才计数
 n=sum(1 for r in rows if r.get(feature) is not None and r.get('loss') is not None)
 return {'total':len(rows),'paired':n,'excluded':len(rows)-n}
def load_package(s,path):
 if not path or not os.path.exists(path):
  raise HTTPException(409,'归档包缺失，相关研究无法计算，请先恢复或重新归档')
 try:
  digest,pkg=read_checksum(path)
 except (json.JSONDecodeError,OSError,ValueError,UnicodeDecodeError) as e:
  raise HTTPException(409,f'归档包损坏（{e}），相关研究被拒绝，不能静默排除')
 if pkg.get('version')!=ARCHIVE_PACKAGE_VERSION:
  raise HTTPException(409,'归档包版本不支持，相关研究被拒绝')
 return pkg,digest
def verify_archived_tables(s,task_id,shipment_ids,check_online=False):
 ids=set(shipment_ids)
 ships=s.query(ArchivedShipment).filter_by(task_id=task_id).all()
 if {a.origin_shipment_id for a in ships}!=ids:return False,'归档班次数量不匹配'
 samples=s.query(ArchivedSample).filter(ArchivedSample.task_id==task_id,
  ArchivedSample.origin_shipment_id.in_(ids)).all()
 if any(a.origin_shipment_id not in ids for a in samples):return False,'归档样本归属越界'
 if check_online:
  # 清理后复核：不能留下未归档的活跃明细（code 非空且无任务标记）
  left=s.query(Sample).filter(Sample.shipment_id.in_(ids),
   Sample.archive_task_id.is_(None),Sample.code.isnot(None)).count()
  if left:return False,'在线明细尚未清理干净'
 return True,''
def done_archive_tasks(s):
 return {t.id:t for t in s.query(ArchiveTask).filter_by(kind='archiving',state='done').all()}
def ensure_study_archives_healthy(s):
 # 研究创建前：系统内存在的每个归档包都必须可读且校验通过，缺失/损坏明确拒绝，不静默排除
 for t in done_archive_tasks(s).values():
  if s.query(ArchivedSample).filter_by(task_id=t.id).first():load_package(s,t.package_path)
def archived_rows_for_zone(s,zone):
 # 仅汇总已完成归档任务中该温区的样本；失败/进行中任务的半成品不进入研究，避免交接窗口漏算或重算
 tasks=done_archive_tasks(s)
 ship_zones={a.origin_shipment_id:a.zone for a in s.query(ArchivedShipment)
  .filter(ArchivedShipment.task_id.in_(list(tasks))).all()}
 seen=set();out=[]
 for a in s.query(ArchivedSample).order_by(ArchivedSample.id).all():
  if a.task_id not in tasks or ship_zones.get(a.origin_shipment_id)!=zone or a.code in seen:continue
  load_package(s,tasks[a.task_id].package_path)  # 缺失/损坏即抛 409，不静默排除
  seen.add(a.code)
  out.append({'id':a.origin_sample_id,'shipment_id':a.origin_shipment_id,'code':a.code,
   'exposure':a.exposure,'excursions':a.excursions,'loss':a.loss,'source':'archive'})
 return out
def online_rows_for_zone(s,zone):
 ship_ids=[r.id for r in s.query(Shipment).filter_by(zone=zone).all() if not r.archive_task_id]
 if not ship_ids:return []
 return [{'id':r.id,'shipment_id':r.shipment_id,'code':r.code,
  'exposure':r.exposure,'excursions':r.excursions,'loss':r.loss,'source':'online'}
  for r in s.query(Sample).filter(Sample.shipment_id.in_(ship_ids),Sample.archive_task_id.is_(None)).all()]
def study_rows(s,zone):
 # 在线 + 归档同口径合并，样本编号去重，在线优先；交接窗口创建研究也不漏样本
 rows={r['code']:r for r in archived_rows_for_zone(s,zone)}
 for r in online_rows_for_zone(s,zone):rows[r['code']]=r
 return list(rows.values())
def archived_overview(s):
 # 仅统计已完成归档任务的数据，失败/进行中的半成品不展示为已归档
 done=done_archive_tasks(s)
 ships=s.query(ArchivedShipment).filter(ArchivedShipment.task_id.in_(list(done))).order_by(ArchivedShipment.id).all()
 counts={}
 for a in s.query(ArchivedSample).filter(ArchivedSample.task_id.in_(list(done))).all():
  counts[a.origin_shipment_id]=counts.get(a.origin_shipment_id,0)+1
 return [{'origin_shipment_id':a.origin_shipment_id,'task_id':a.task_id,'code':a.code,
  'route':a.route,'zone':a.zone,'driver':a.driver,'samples':counts.get(a.origin_shipment_id,0)} for a in ships]
def task_compare(s,task):
 feats=('exposure','excursions')
 if task.kind=='archiving':
  before=as_json(task.progress).get('before') or {}
  after=as_json(task.progress).get('after') or {}
  return {f:{'before':before.get(f),'after':_zone_merge(after,f)} for f in feats}
 p=as_json(task.progress);c=p.get('compare') or {}
 return {f:{'before':(c.get(f) or {}).get('before'),'after':(c.get(f) or {}).get('after')} for f in feats}
def _zone_merge(after,feat):
 if not after:return None
 tot=sum(v.get(feat,{}).get('total',0) for v in after.values())
 paired=sum(v.get(feat,{}).get('paired',0) for v in after.values())
 return {'total':tot,'paired':paired,'excluded':tot-paired}
def mark_failed(s,row,msg):
 row.state='failed';row.error=msg;row.updated=now();s.commit()
