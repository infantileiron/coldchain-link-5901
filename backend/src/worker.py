import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import Study,ArchiveTask
from src.services.analysis import analyze
from src.constants.enums import ARCHIVE_QUEUE,RESTORE_QUEUE
from src.services.archive_flow import run_archiving,run_restoring
r=redis.Redis.from_url(os.environ['REDIS_URL'])
with Session() as recovery:
 for pending in recovery.query(Study).filter(Study.state.in_(['queued','running'])).all():
  pending.state='queued';r.rpush('studies',pending.id)
 # 归档/恢复任务启动恢复：中断的 running 重新入队，重试走幂等阶段不重复搬迁
 for pending in recovery.query(ArchiveTask).filter(ArchiveTask.state.in_(['queued','running'])).all():
  queue=ARCHIVE_QUEUE if pending.kind=='archiving' else RESTORE_QUEUE
  pending.state='queued';r.rpush(queue,pending.id)
 recovery.commit()
def run_study(item_id):
 with Session() as s:
  row=s.get(Study,item_id)
  if not row or row.state!='queued':return
  snapshot=row.result['snapshot'];row.state='running';s.commit()
  try:
   row.result={**analyze(snapshot,row.feature),'snapshot':snapshot};row.state='done'
   Path('/artifacts/'+str(row.id)+'.json').write_text(json.dumps(row.result,ensure_ascii=False))
  except Exception as e:row.state='failed';row.error=str(e)
  s.commit()
def run_archive_task(item_id):
 with Session() as s:
  row=s.get(ArchiveTask,item_id)
  if not row or row.state=='done':return  # 已完成任务重复投递直接跳过，不重复搬迁
  if row.kind=='archiving':run_archiving(s,row)
  else:run_restoring(s,row)
QUEUES=(ARCHIVE_QUEUE,RESTORE_QUEUE,'studies')  # 归档优先；单 worker 串行避免同班次并发覆盖
while True:
 Path('/tmp/heartbeat').touch()
 try:
  # blpop 按给定键顺序返回首个非空队列，保留队列名与优先级；redis 默认返回 bytes 需解码
  packed=r.blpop(QUEUES,timeout=3)
  if not packed:continue
  queue,raw=packed
  if isinstance(queue,bytes):queue=queue.decode()
  item_id=int(raw)
  if queue=='studies':run_study(item_id)
  else:run_archive_task(item_id)
 except Exception:logging.exception('worker');time.sleep(2)
