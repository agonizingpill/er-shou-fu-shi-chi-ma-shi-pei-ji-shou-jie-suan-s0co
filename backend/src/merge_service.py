from .models import *
from .common import *

def _ready_map(s,pid):
 out={}
 for a in rows(s,FitAssessment):
  if a.profile_id==pid and a.state=='ready' and a.result:out[a.garment_id]=a
 return out

def similarity(s,p1,p2):
 # 同批在售衣物：两件档案都对同一件仍在售（在架或留衣中）的衣物算出过 ready 预测；售出/撤回/复检衣物不计
 m1,m2=_ready_map(s,p1.id),_ready_map(s,p2.id)
 on_sale={g.id for g in rows(s,Garment) if g.state in ('listed','held')}
 shared=sorted(set(m1)&set(m2)&on_sale)
 evidence=[];same=0;dist_sum=0.0
 for gid in shared:
  r1,r2=m1[gid].result,m2[gid].result
  g=get(s,Garment,gid)
  labels=sorted(set(r1.get('probabilities',{}))|set(r2.get('probabilities',{})))
  d=sum(abs(r1.get('probabilities',{}).get(k,0.0)-r2.get('probabilities',{}).get(k,0.0)) for k in labels)/2
  match=r1.get('label')==r2.get('label');same+=1 if match else 0;dist_sum+=d
  evidence.append({'garment_id':gid,'garment_code':g.code,'label_a':r1.get('label'),'label_b':r2.get('label'),'label_match':match,'prob_distance':round(d,6)})
 n=len(shared)
 return {'shared_garments':n,'same_labels':same,'avg_prob_distance':round(dist_sum/n,6) if n else None,
  'chest_gap':round(abs(p1.chest-p2.chest),2),'shoulder_gap':round(abs(p1.shoulder-p2.shoulder),2),'evidence':evidence}

def candidates(s):
 ps=[p for p in rows(s,FitProfile) if not p.merged_into_id]
 merged_ids={m.secondary_id for m in rows(s,ProfileMerge)}|{m.primary_id for m in rows(s,ProfileMerge)}
 out=[]
 for i in range(len(ps)):
  for j in range(i+1,len(ps)):
   a,b=ps[i],ps[j]
   if a.id in merged_ids or b.id in merged_ids:continue
   sim=similarity(s,a,b)
   if sim['shared_garments']==0:continue
   open_a=any(x.state=='reserved' for x in rows(s,Fitting) if x.profile_id==a.id)
   open_b=any(x.state=='reserved' for x in rows(s,Fitting) if x.profile_id==b.id)
   out.append({'a':dump(a),'b':dump(b),**sim,'both_open':open_a and open_b})
 out.sort(key=lambda x:(-x['shared_garments'],x['avg_prob_distance'] if x['avg_prob_distance'] is not None else 9))
 return out

def merge(s,d):
 c=lock(s)
 pid,sid=d['primary_id'],d['secondary_id']
 if pid==sid:fail('不能将档案与自身合档')
 # 幂等重试：这两份档案已有合档结论，直接返回原记录，不改变已定主档
 for m in rows(s,ProfileMerge):
  if {m.primary_id,m.secondary_id}=={pid,sid}:return m
 p=get(s,FitProfile,pid);q=get(s,FitProfile,sid)
 participated={x.primary_id for x in rows(s,ProfileMerge)}|{x.secondary_id for x in rows(s,ProfileMerge)}
 if pid in participated or sid in participated:fail('其中一份档案已参与过合档，不能再次合档')
 # 两边都有未结束预约：暂缓，等预约结束后再合
 open_p=any(x.state=='reserved' for x in rows(s,Fitting) if x.profile_id==pid)
 open_q=any(x.state=='reserved' for x in rows(s,Fitting) if x.profile_id==sid)
 if open_p and open_q:fail('两份档案均有未结束预约，暂缓合档')
 sim=similarity(s,p,q)
 if sim['shared_garments']==0:fail('两份档案缺少同批在售衣物的适配预测，无法认定相近')
 m=ProfileMerge(primary_id=pid,secondary_id=sid,shared_garments=sim['shared_garments'],same_labels=sim['same_labels'],avg_prob_distance=sim['avg_prob_distance'],chest_gap=sim['chest_gap'],shoulder_gap=sim['shoulder_gap'],evidence=sim['evidence'],merged_at=c.now)
 s.add(m);q.merged_into_id=pid;s.flush();return m
