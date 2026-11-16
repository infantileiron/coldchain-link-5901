from pydantic import BaseModel,Field,field_validator
from typing import Optional,Literal,List
class Login(BaseModel):
 email:str;password:str
class ShipmentInput(BaseModel):
 code:str=Field(min_length=1,max_length=60);route:str=Field(min_length=1,max_length=60);zone:Literal['冷藏','冷冻','常温对照'];driver:str=Field(min_length=1,max_length=60)
class SampleInput(BaseModel):
 shipment_id:int;code:str=Field(min_length=1,max_length=60);exposure:Optional[float]=Field(default=None,ge=0,le=1440);excursions:Optional[int]=Field(default=None,ge=0,le=100);loss:Optional[float]=Field(default=None,ge=0,le=100)
class StudyInput(BaseModel):
 name:str=Field(min_length=1,max_length=100);zone:Literal['冷藏','冷冻','常温对照'];feature:Literal['exposure','excursions']='exposure'
class RecommendationInput(BaseModel):
 study_id:int;note:str=Field(min_length=10,max_length=2000);owner:str=Field(min_length=1,max_length=60)
class ArchiveInput(BaseModel):
 shipment_ids:List[int]=Field(min_length=1)
 @field_validator('shipment_ids')
 @classmethod
 def unique_ids(cls,v):
  if len(set(v))!=len(v):raise ValueError('所选班次存在重复')
  return v
class RestoreInput(BaseModel):
 task_id:int
 shipment_ids:Optional[List[int]]=None

