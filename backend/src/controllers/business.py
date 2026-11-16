from fastapi import HTTPException
from src.models.entities import Shipment,Study
from src.services.archive import study_rows as archived_study_rows
def ensure_shipment(s,i):
 row=s.get(Shipment,i)
 if not row:raise HTTPException(404,'班次不存在')
 if row.archive_task_id:raise HTTPException(409,f'班次 {row.code or i} 已归档，请先恢复整班次再更正')
 return row
def study_rows(s,zone):
 # 在线 + 归档合并去重；归档包缺失/损坏时由服务层抛 409，研究无法静默排除样本
 return archived_study_rows(s,zone)
def ensure_study(s,i):
 row=s.get(Study,i)
 if not row:raise HTTPException(404,'研究不存在')
 return row
