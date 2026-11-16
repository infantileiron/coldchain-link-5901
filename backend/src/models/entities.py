from sqlalchemy import Column,Integer,String,Float,JSON,Text,UniqueConstraint
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True);password=Column(String(200));role=Column(String(20))
class Shipment(Base):
 __tablename__='shipments'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True);route=Column(String(60));zone=Column(String(20));driver=Column(String(60))
 # 归档后行保留为占位：编号与自增 ID 不释放（唯一约束禁止复用），仅打归档标记退出在线明细
 archive_task_id=Column(Integer,index=True,nullable=True)
class Sample(Base):
 __tablename__='samples'
 id=Column(Integer,primary_key=True);shipment_id=Column(Integer,index=True);code=Column(String(60),unique=True);exposure=Column(Float,nullable=True);excursions=Column(Integer,nullable=True);loss=Column(Float,nullable=True)
 archive_task_id=Column(Integer,index=True,nullable=True)
class Study(Base):
 __tablename__='studies'
 id=Column(Integer,primary_key=True);name=Column(String(100));zone=Column(String(20));feature=Column(String(30));state=Column(String(20),default='queued');result=Column(JSON,nullable=True);error=Column(Text,default='')
class Recommendation(Base):
 __tablename__='recommendations'
 id=Column(Integer,primary_key=True);study_id=Column(Integer);note=Column(Text);owner=Column(String(60));status=Column(String(20),default='draft')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
class ArchiveTask(Base):
 __tablename__='archive_tasks'
 id=Column(Integer,primary_key=True);kind=Column(String(20));state=Column(String(20),default='queued');stage=Column(String(30),default='')
 shipment_ids=Column(JSON);package_path=Column(String(260),default='');checksum=Column(String(64),default='')
 progress=Column(JSON);error=Column(Text,default='');actor=Column(String(100),default='');created=Column(String(40));updated=Column(String(40))
class ArchivedShipment(Base):
 __tablename__='archived_shipments'
 id=Column(Integer,primary_key=True)
 task_id=Column(Integer,index=True);origin_shipment_id=Column(Integer,index=True);code=Column(String(60));route=Column(String(60));zone=Column(String(20));driver=Column(String(60))
 __table_args__=(UniqueConstraint('task_id','origin_shipment_id',name='uq_archived_shipment_task_origin'),)
class ArchivedSample(Base):
 __tablename__='archived_samples'
 id=Column(Integer,primary_key=True)
 task_id=Column(Integer,index=True);origin_sample_id=Column(Integer);origin_shipment_id=Column(Integer,index=True)
 code=Column(String(60));exposure=Column(Float,nullable=True);excursions=Column(Integer,nullable=True);loss=Column(Float,nullable=True)
 __table_args__=(UniqueConstraint('task_id','origin_sample_id',name='uq_archived_sample_task_origin'),)
