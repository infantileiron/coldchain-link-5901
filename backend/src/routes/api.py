import os,json
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import User,Shipment,Sample,Study,Recommendation,Audit,ArchiveTask,ArchivedShipment
from src.schemas.business import (Login,ShipmentInput,SampleInput,StudyInput,
 RecommendationInput,ArchiveInput,RestoreInput)
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.archive import (now,task_dump,assert_no_conflict,online_shipment,
 ensure_study_archives_healthy,archived_overview,task_compare,active_tasks,
 done_archive_tasks,load_package,package_path)
from src.controllers.business import ensure_shipment,ensure_study,study_rows
from src.constants.enums import ARCHIVE_QUEUE,RESTORE_QUEUE
router=APIRouter()
def _rq():return redis.Redis.from_url(os.environ['REDIS_URL'])
def _enqueue(queue,task_id):
 try:_rq().rpush(queue,task_id)
 except redis.RedisError:raise HTTPException(503,'队列暂不可用，请稍后重试')
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/shipments')
def ships(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Shipment).all()]
@router.post('/shipments')
def ship(data:ShipmentInput,u=Depends(editor),s=Depends(db)):
 r=Shipment(**data.model_dump());s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'班次编号重复')
 audit(s,u,'创建班次 '+r.code);return dump(r)
@router.get('/samples')
def samples(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Sample).all()]
@router.post('/samples')
def sample(data:SampleInput,u=Depends(editor),s=Depends(db)):
 ensure_shipment(s,data.shipment_id);r=Sample(**data.model_dump());s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'样本编号重复')
 audit(s,u,'录入样本 '+r.code);return dump(r)
@router.get('/studies')
def studies(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Study).order_by(Study.id.desc()).all()]
@router.post('/studies')
def study(data:StudyInput,u=Depends(editor),s=Depends(db)):
 # 归档包缺失/损坏时拒绝创建研究，绝不静默排除归档样本
 ensure_study_archives_healthy(s)
 rows=study_rows(s,data.zone);r=Study(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:_rq().rpush('studies',r.id)
 except redis.RedisError:
  r.state='failed';r.error='队列暂不可用，请重新创建研究';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交研究 '+str(r.id)+f'（在线+归档样本 {len(rows)} 条）');return dump(r)
@router.get('/studies/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_study(s,i))
@router.get('/studies/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_study(s,i)
 if r.state!='done':raise HTTPException(409,'研究未成功完成')
 # 已有研究导出冻结时的原始快照，归档动作不改变既有下载内容
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="coldchain-link-{i}.json"'})
@router.get('/recommendations')
def recs(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Recommendation).order_by(Recommendation.id.desc()).all()]
@router.post('/recommendations')
def rec(data:RecommendationInput,u=Depends(editor),s=Depends(db)):
 if ensure_study(s,data.study_id).state!='done':raise HTTPException(409,'仅已完成研究可以起草建议')
 r=Recommendation(**data.model_dump());s.add(r);s.commit();audit(s,u,'起草建议 '+str(r.id));return dump(r)
@router.post('/recommendations/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=s.get(Recommendation,i)
 if not r:raise HTTPException(404,'建议不存在')
 r.status='approved';s.commit();audit(s,u,'签核建议 '+str(i));return dump(r)
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]

@router.put('/shipments/{i}')
def edit_ship(i:int,data:ShipmentInput,u=Depends(editor),s=Depends(db)):
 ensure_shipment(s,i);row=s.get(Shipment,i)
 for k,v in data.model_dump().items():setattr(row,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'班次编号重复')
 audit(s,u,'修改班次 '+str(i));return dump(row)
@router.put('/samples/{i}')
def edit_sample(i:int,data:SampleInput,u=Depends(editor),s=Depends(db)):
 row=s.get(Sample,i)
 if not row:raise HTTPException(404,'样本不存在')
 ensure_shipment(s,data.shipment_id)
 if row.archive_task_id:raise HTTPException(409,f'样本 {row.code or i} 已归档，请先恢复整班次再更正')
 for k,v in data.model_dump().items():setattr(row,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'样本编号重复')
 audit(s,u,'修改样本 '+str(i));return dump(row)

# ---- 班次归档 / 恢复 ----
@router.get('/archives/overview')
def archive_overview(u=Depends(current),s=Depends(db)):
 return {'archived':archived_overview(s),
  'active':[task_dump(t) for t in active_tasks(s)],
  'packages':[{'task_id':t.id,'path':t.package_path,'checksum':t.checksum} for t in done_archive_tasks(s).values()]}
@router.get('/archives/tasks')
def archive_tasks(u=Depends(current),s=Depends(db)):
 out=[]
 for t in s.query(ArchiveTask).order_by(ArchiveTask.id.desc()).all():
  d=task_dump(t);d['compare']=task_compare(s,t);out.append(d)
 return out
@router.get('/archives/tasks/{i}')
def archive_task(i:int,u=Depends(current),s=Depends(db)):
 t=s.get(ArchiveTask,i)
 if not t:raise HTTPException(404,'归档任务不存在')
 d=task_dump(t);d['compare']=task_compare(s,t);return d
@router.post('/archives')
def create_archive(data:ArchiveInput,u=Depends(editor),s=Depends(db)):
 ids=data.shipment_ids
 for sid in ids:online_shipment(s,sid)
 assert_no_conflict(s,ids)
 ships=s.query(Shipment).filter(Shipment.id.in_(ids)).all()
 if any(r.archive_task_id for r in ships):
  raise HTTPException(409,'所选班次中包含已归档班次，请先恢复或调整选择')
 t=ArchiveTask(kind='archiving',state='queued',stage='packing',shipment_ids=ids,
  progress={},actor=u.email,created=now(),updated=now())
 s.add(t);s.commit()
 try:_enqueue(ARCHIVE_QUEUE,t.id)
 except HTTPException:
  s.delete(t);s.commit();raise
 audit(s,u,f'创建归档任务 {t.id}，班次 {len(ids)} 个')
 return task_dump(t)
@router.post('/archives/{i}/retry')
def retry_archive(i:int,u=Depends(editor),s=Depends(db)):
 t=s.get(ArchiveTask,i)
 if not t:raise HTTPException(404,'归档任务不存在')
 if t.kind!='archiving':raise HTTPException(409,'该任务不是归档任务')
 if t.state in ('queued','running'):raise HTTPException(409,'任务仍在进行中，无需重试')
 if t.state=='done':raise HTTPException(409,'任务已完成，不能重复搬迁')
 t.state='queued';t.error='';t.updated=now();s.commit()
 _enqueue(ARCHIVE_QUEUE,t.id)
 audit(s,u,f'重试归档任务 {t.id}');return task_dump(t)
@router.post('/restores')
def create_restore(data:RestoreInput,u=Depends(editor),s=Depends(db)):
 src=s.get(ArchiveTask,data.task_id)
 if not src or src.kind!='archiving':raise HTTPException(404,'原归档任务不存在')
 if src.state!='done':raise HTTPException(409,'仅已完成的归档任务可以恢复')
 # 归档包必须存在且校验通过，否则拒绝恢复
 load_package(s,src.package_path or package_path(src.id))
 available={a.origin_shipment_id for a in s.query(ArchivedShipment).filter_by(task_id=src.id).all()}
 if not available:raise HTTPException(409,'该归档任务的班次均已恢复，无可恢复内容')
 ids=data.shipment_ids or sorted(available)
 bad=set(ids)-available
 if bad:raise HTTPException(409,f'班次 {sorted(bad)} 不在归档任务 {src.id} 中或已恢复')
 assert_no_conflict(s,ids)
 t=ArchiveTask(kind='restoring',state='queued',stage='verifying',shipment_ids=ids,
  package_path=src.package_path,progress={'source_task_id':src.id},actor=u.email,
  created=now(),updated=now())
 s.add(t);s.commit()
 try:_enqueue(RESTORE_QUEUE,t.id)
 except HTTPException:
  s.delete(t);s.commit();raise
 audit(s,u,f'创建恢复任务 {t.id}，来源归档 {src.id}，班次 {len(ids)} 个')
 return task_dump(t)
@router.post('/restores/{i}/retry')
def retry_restore(i:int,u=Depends(editor),s=Depends(db)):
 t=s.get(ArchiveTask,i)
 if not t:raise HTTPException(404,'恢复任务不存在')
 if t.kind!='restoring':raise HTTPException(409,'该任务不是恢复任务')
 if t.state in ('queued','running'):raise HTTPException(409,'任务仍在进行中，无需重试')
 if t.state=='done':raise HTTPException(409,'任务已完成，不能重复搬迁')
 load_package(s,t.package_path)
 t.state='queued';t.error='';t.updated=now();s.commit()
 _enqueue(RESTORE_QUEUE,t.id)
 audit(s,u,f'重试恢复任务 {t.id}');return task_dump(t)
