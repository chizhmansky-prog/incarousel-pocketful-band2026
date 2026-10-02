"""Independent pre-publication black-box contracts, no organizer test source.

Every test resets only disposable isolated instances. Raw states/tokens are never saved.
"""
import concurrent.futures,copy,datetime,json,os,pathlib,random,time,urllib.error,urllib.parse,urllib.request
base=os.environ['POCKETFUL_BASE_URL'];other=os.environ['POCKETFUL_IMPORT_URL'];old=os.environ['POCKETFUL_OLD_URL']
out=pathlib.Path(os.environ['POCKETFUL_EVIDENCE_OUT']);out.mkdir(parents=True,exist_ok=True)
cases=[];utc=datetime.timezone.utc
def instant(n=0):return (datetime.datetime.now(utc)+datetime.timedelta(seconds=n)).isoformat()
def call(path,method='GET',body=None,token=None,key=None,target=None,raw=False):
 h={'Accept':'application/json'}
 if token:h['Authorization']='Bearer '+token
 if key is not None:h['Idempotency-Key']=key
 if body is not None:h['Content-Type']='application/json'
 data=None if body is None else (body.encode() if raw else json.dumps(body).encode())
 try:
  with urllib.request.urlopen(urllib.request.Request((target or base)+path,method=method,data=data,headers=h),timeout=10) as r:s,b=r.status,r.read()
 except urllib.error.HTTPError as r:s,b=r.code,r.read()
 return s,json.loads(b) if b else None
def expect(r,status,code=None):
 actual=r[1].get('error',{}).get('code') if isinstance(r[1],dict) else None
 assert r[0]==status,f'expected HTTP{status}/{code}, observed HTTP{r[0]}/{actual}'
 if code:assert actual==code,f'expected {code}, observed {actual}'
 return r[1]
def case(name,fn):
 try:fn();cases.append({'case':name,'status':'PASS'})
 except Exception as e:cases.append({'case':name,'status':'FAIL','finding':str(e)[:500]})
 print(json.dumps(cases[-1]),flush=True)
def seed(balances=(10000,5000,2000),target=None,payments=None):
 f={'currency':'EUR','minor_units':2,'users':[{'id':'u_'+h,'handle':h,'email':h+'@example.test','password':'fixture password','display_name':h,'balance':b} for h,b in zip(('ada','bob','cy'),balances)],'settlement_operator_ids':['u_ada'],'payments':payments or [],'requests':[],'authorizations':[]}
 expect(call('/_test/reset','POST',f,target=target),204)
 return {h:expect(call('/auth/login','POST',{'email':h+'@example.test','password':'fixture password'},target=target),200)['token'] for h in ('ada','bob','cy')}
def export(target=None):return expect(call('/_test/export',target=target),200)
def money(t,target=None):return [expect(call('/me',token=t[h],target=target),200)['balance'] for h in ('ada','bob','cy')]
def pay(t,amount=1000,fr='ada',to='bob',key='p'):
 return expect(call('/payments','POST',{'to_handle':to,'amount':amount,'note':'original ☕','visibility':'private'},t[fr],key),201)
def item(p,amount,rev=1,at=None):return {'payment_id':p['payment_id'],'expected_revision':rev,'amount':amount,'effective_at':at or p['created_at'],'reason':'independent boundary probe'}
def batch(t,items,key='b'):return call('/correction-batches','POST',{'corrections':items},t['ada'],key)
def refund(t,p,amount,key='r',receiver='bob'):return call('/payments/'+p['payment_id']+'/refunds','POST',{'amount':amount},t[receiver],key)
def unchanged_failure(fn,status,code):
 before=export();expect(fn(),status,code);assert export()==before,'failed write altered exported state'

def refund_race():
 t=seed();p=pay(t);start=money(t)
 with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
  rs=list(pool.map(lambda i:refund(t,p,100,'race-'+str(i)),range(20)))
 assert [r[0] for r in rs].count(201)==10,'exactly ten refunds must fit original1000 ceiling'
 for r in rs:
  if r[0]!=201:expect(r,422,'refund_exceeds_payment')
 assert money(t)==[start[0]+1000,start[1]-1000,start[2]]
 payments=expect(call('/activity?limit=200',token=t['ada']),200)['payments'];assert sum(p.get('amount',0) for p in payments if p.get('refund_of'))==1000
case('20 concurrent distinct refunds cannot exceed cumulative ceiling',refund_race)

def same_key_race():
 t=seed();p=pay(t)
 with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:rs=list(pool.map(lambda i:refund(t,p,300,'same-refund'),range(16)))
 assert [r[0] for r in rs].count(201)==1 and [r[0] for r in rs].count(200)==15
 assert all(r[1]==rs[0][1] for r in rs),'concurrent identical replay receipt differs'
 assert money(t)==[9300,5700,2000]
case('16 identical concurrent refunds create exactly one immutable receipt',same_key_race)

def overlapping_batches():
 for mixed in (False,True):
  t=seed();p=pay(t);q=pay(t,500,key='q');a=item(p,700);b=item(q,400)
  def write(i):
   if mixed and i:return call('/payments/'+p['payment_id']+'/corrections','POST',{k:v for k,v in a.items() if k!='payment_id'},t['ada'],'single')
   return batch(t,[a,b] if i==0 else [a],'batch-'+str(i))
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:rs=list(pool.map(write,range(2)))
  assert sorted(r[0] for r in rs)==[201,409]
  expect(next(r for r in rs if r[0]==409),409,'stale_revision')
  history=expect(call('/payments/'+p['payment_id']+'/revisions',token=t['ada']),200)['revisions'];assert len(history)==2
case('overlapping batch/batch and batch/single have one winning expected revision',overlapping_batches)

def settlement_offsets():
 t=seed((1000,1000,0));body={'transfers':[{'from_handle':'ada','to_handle':'bob','amount':1500},{'from_handle':'bob','to_handle':'ada','amount':1500}]}
 receipt=expect(call('/settlements','POST',body,t['ada'],'settle'),201);ps=receipt['payments'];at=datetime.datetime.now(utc)-datetime.timedelta(seconds=10)
 a=item(ps[1],500,at=at.isoformat());b=item(ps[0],500,at=at.astimezone(datetime.timezone(datetime.timedelta(hours=3))).isoformat())
 result=expect(batch(t,[a,b]),201);assert [x['payment_id'] for x in result['revisions']]==[a['payment_id'],b['payment_id']]
 assert money(t)==[1000,1000,0]
 assert len({x['recorded_at'] for x in result['revisions']})==1
 bad=[item(p,500,2,instant(-10-i)) for i,p in enumerate(ps)]
 unchanged_failure(lambda:batch(t,bad,'offset-error'),422,'validation_failed')
 assert expect(call('/settlements','POST',body,t['ada'],'settle'),200)==receipt
case('settlement net affordability, equivalent offsets, input order and unequal-time refusal',settlement_offsets)

def validation_precedence():
 t=seed();p=pay(t);q=pay(t,400,key='q');expect(batch(t,[item(p,800)]),201)
 stale=item(p,700);unknown=item({'payment_id':'p_missing','created_at':p['created_at']},1)
 unchanged_failure(lambda:batch(t,[stale,unknown],'first-stale'),409,'stale_revision')
 unchanged_failure(lambda:batch(t,[unknown,stale],'first-unknown'),404,'not_found')
 good=item(p,800,2)
 for items in ([],[good]*33,[good,good]):unchanged_failure(lambda items=items:batch(t,items,'invalid-list'),422,'validation_failed')
 for field,value in [('amount',True),('amount',1.5),('amount',-1),('amount',1000000001),('expected_revision',True),('expected_revision',0),('reason',''),('effective_at',instant(3600))]:
  z=copy.deepcopy(good);z[field]=value
  # Stage3 ordinary correction validation explicitly assigns invalid input422.
  # Stage4 reuses those fields/rules; endpoint rules override Stage1's default.
  # Preserve the earlier400-oracle execution as a superseded audit assumption.
  status,code=422,'validation_failed'
  try:unchanged_failure(lambda z=z:batch(t,[z],'invalid-item'),status,code)
  except AssertionError as e:raise AssertionError(f'{field}={value!r}: {e}')
 unchanged_failure(lambda:call('/correction-batches','POST',{'corrections':[item(q,300)]},None,'noauth'),401,'unauthenticated')
 unchanged_failure(lambda:call('/correction-batches','POST',{'corrections':[item(q,300)]},t['bob'],'nonoperator'),403,'forbidden')
 # Failed key stays free: same key with corrected valid content can succeed.
 expect(batch(t,[item(q,300)],'invalid-list'),201)
case('batch input-order errors, exact type/range/access gates and no burned failed key',validation_precedence)

def capture_refund():
 t=seed();h=expect(call('/authorizations','POST',{'to_handle':'bob','amount':1000,'note':'held','visibility':'private'},t['ada'],'hold'),201)
 p=expect(call('/authorizations/'+h['authorization_id']+'/capture','POST',{'amount':400,'final':False},t['bob'],'cap'),201)
 before=expect(call('/me',token=t['ada']),200);r=expect(refund(t,p,400),201);after=expect(call('/me',token=t['ada']),200)
 assert before['held']==after['held']==600 and after['total']==before['total']+400
 assert r['request_id'] is None and r['authorization_id'] is None and r['refund_of']==p['payment_id']
 unchanged_failure(lambda:batch(t,[item(p,0)],'correct-cap'),422,'linked_payment_immutable')
 expect(call('/authorizations/'+h['authorization_id']+'/void','POST',{},t['ada']),200)
 rows=expect(call('/authorizations',token=t['ada']),200)['authorizations'];assert rows[0]['status']=='voided' and rows[0]['captured_amount']==400
 assert expect(refund(t,p,400),200)==r
case('refund of partial capture restores money without restoring hold/lifecycle',capture_refund)

def request_refund():
 t=seed();body={'payer_handle':'ada','amount':500,'note':'request'};q=expect(call('/requests','POST',body,t['bob'],'request'),201)
 path='/requests/'+q['request_id']+'/pay';p=expect(call(path,'POST',{'visibility':'private'},t['ada'],'pay-request'),201)
 expect(refund(t,p,500),201)
 rows=expect(call('/requests',token=t['ada']),200)['requests'];assert next(x for x in rows if x['request_id']==q['request_id'])['status']=='paid'
 assert expect(call(path,'POST',{'visibility':'private'},t['ada'],'pay-request'),200)==p
 unchanged_failure(lambda:refund(t,p,1,'after-full'),422,'refund_exceeds_payment')
 expect(batch(t,[item(p,500)],'at-floor'),201)
 unchanged_failure(lambda:batch(t,[item(p,499,2)],'below-floor'),422,'refund_exceeds_payment')
case('request refund leaves request paid, original pay receipt intact and exact correction floor',request_refund)

def refund_correction_race():
 for i in range(8):
  t=seed();p=pay(t)
  def write(n):return refund(t,p,800,'race-refund') if n else batch(t,[item(p,500)],'race-correction')
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:rs=list(pool.map(write,range(2)))
  assert sorted(r[0] for r in rs)==[201,422],f'refund/correction race requires one201 and one422, observed{[r[0] for r in rs]}'
  expect(next(r for r in rs if r[0]==422),422,'refund_exceeds_payment')
  assert money(t) in ([9500,5500,2000],[9800,5200,2000])
case('eight refund/correction races preserve one consistent corrected refund ceiling',refund_correction_race)

def historical_available():
 t=seed((10000,0,0));p=pay(t)
 # RFC3339 permits second precision. Separate events so the past hold interval
 # and known-before-creation view exist even for a coarse server clock.
 time.sleep(1.05)
 h=expect(call('/authorizations','POST',{'to_handle':'cy','amount':800},t['bob'],'bob-hold'),201)
 assert datetime.datetime.fromisoformat(h['created_at'])>datetime.datetime.fromisoformat(p['created_at']),'fixture requires payment before hold'
 time.sleep(1.05)
 expect(call('/authorizations/'+h['authorization_id']+'/void','POST',{},t['bob']),200)
 unchanged_failure(lambda:batch(t,[item(p,500)],'historical-held'),409,'historical_overdraft')
 # Equality at an earlier hold boundary is affordable and must succeed.
 expect(batch(t,[item(p,800)],'historical-held'),201)
 at=h['created_at'];m=expect(call('/me?'+urllib.parse.urlencode({'as_of':at}),token=t['bob']),200)
 assert [m[k] for k in ('total','available','held')]==[800,0,800]
 m=expect(call('/me?'+urllib.parse.urlencode({'as_of':at,'known_at':p['created_at']}),token=t['bob']),200)
 assert [m[k] for k in ('total','available','held')]==[1000,1000,0]
case('released hold still constrains past available funds; zero boundary and old knowledge are exact',historical_available)

def settlement_refund_membership():
 t=seed();body={'transfers':[{'from_handle':'ada','to_handle':'bob','amount':500},{'from_handle':'bob','to_handle':'cy','amount':300}]}
 receipt=expect(call('/settlements','POST',body,t['ada'],'s'),201);ps=receipt['payments']
 expect(refund(t,ps[0],200),201)
 unchanged_failure(lambda:batch(t,[item(ps[0],400)],'one-member'),422,'incomplete_settlement')
 at=receipt.get('committed_at',ps[0]['created_at']);items=[item(ps[0],400,at=at),item(ps[1],200,at=at)]
 expect(batch(t,items,'all-members'),201)
 unchanged_failure(lambda:refund(t,ps[0],201,'exceed-corrected'),422,'refund_exceeds_payment')
 expect(refund(t,ps[0],200,'remaining'),201)
 assert expect(call('/settlements','POST',body,t['ada'],'s'),200)==receipt
case('settlement refund retains membership and ceiling follows corrected amount',settlement_refund_membership)

def historical_net():
 def seeded(pid,fr,to,n,at):return {'id':pid,'from_user_id':'u_'+fr,'to_user_id':'u_'+to,'amount':n,'created_at':at,'visibility':'private','note':''}
 at1=instant(-10800);at2=instant(-7200);at3=instant(-3600)
 ps=[seeded('p_in','ada','bob',1000,at1),seeded('p_out','bob','cy',1000,at2),seeded('p_back','cy','bob',1000,at3)]
 t=seed((2000,1000,0),payments=ps)
 a=item({'payment_id':'p_in','created_at':at1},500)
 unchanged_failure(lambda:batch(t,[a],'historical'),409,'historical_overdraft')
 # Combined revisions avoid the intermediate historical debt that a single item creates.
 b=item({'payment_id':'p_out','created_at':at2},500)
 c=item({'payment_id':'p_back','created_at':at3},500)
 expect(batch(t,[a,b,c],'historical'),201);assert money(t)==[2500,500,0]
case('historical batch refusal is atomic even when current wallets can afford change',historical_net)

def knowledge_boundary():
 t=seed();p=pay(t);q=pay(t,500,key='q');snap=expect(call('/statement?limit=1',token=t['ada']),200)
 r=expect(batch(t,[item(q,300),item(p,600)]),201);known=datetime.datetime.fromisoformat(r['recorded_at'])
 def at(k):return expect(call('/me?'+urllib.parse.urlencode({'known_at':k}),token=t['ada']),200)['balance']
 assert at((known-datetime.timedelta(microseconds=1)).isoformat())==8500
 assert at(known.isoformat())==9100
 frozen=expect(call('/statement?'+urllib.parse.urlencode({'snapshot':snap['snapshot'],'limit':1}),token=t['ada']),200)
 assert {k:v for k,v in frozen.items() if k!='snapshot'}=={k:v for k,v in snap.items() if k!='snapshot'}
 expect(call('/_test/import','POST',export(),target=other),204)
 assert expect(call('/correction-batches','POST',{'corrections':[item(q,300),item(p,600)]},t['ada'],'b',target=other),200)==r
case('shared recorded instant is atomic/inclusive and imported snapshots/receipts stay frozen',knowledge_boundary)

def decimal_identity():
 for pathkind in ('refund','batch'):
  t=seed();p=pay(t)
  if pathkind=='refund':path='/payments/'+p['payment_id']+'/refunds';body={'amount':100};token=t['bob']
  else:path='/correction-batches';body={'corrections':[item(p,800)]};token=t['ada']
  raw=json.dumps(body)[:-1]+',"ignored":{"n":0.1234567890123456789012345678901}}'
  first=expect(call(path,'POST',raw,token,'long-number',raw=True),201)
  assert expect(call(path,'POST',raw,token,'long-number',raw=True),200)==first
  # Replace the complete literal once. Replacing '8901' alone also changed
  # earlier significant digits and could hide last-digit rounding defects.
  changed=raw.replace('0.1234567890123456789012345678901','0.1234567890123456789012345678902',1)
  assert changed!=raw
  before=export();expect(call(path,'POST',changed,token,'long-number',raw=True),409,'idempotency_key_reuse');assert export()==before
  # A fresh fixture keeps the marker positive control on revision1; do not
  # accidentally submit a stale correction after the long-number control.
  t=seed();p=pay(t)
  if pathkind=='refund':path='/payments/'+p['payment_id']+'/refunds';body={'amount':100};token=t['bob']
  else:path='/correction-batches';body={'corrections':[item(p,800)]};token=t['ada']
  numeric={**body,'ignored':1};lookalike={**body,'ignored':{'$number':'1'}}
  first=expect(call(path,'POST',numeric,token,'marker-object'),201)
  assert expect(call(path,'POST',numeric,token,'marker-object'),200)==first
  before=export();expect(call(path,'POST',lookalike,token,'marker-object'),409,'idempotency_key_reuse');assert export()==before
case('new write paths retain exact deep JSON decimal identity rather than rounded floats',decimal_identity)

def predecessor_receipts():
 t=seed(target=old);writes=[]
 def create(path,b,h,key):
  response=expect(call(path,'POST',b,t[h],key,target=old),201);writes.append((path,b,h,key,response));return response
 p=create('/payments',{'to_handle':'bob','amount':1000},'ada','old-payment')
 h=create('/authorizations',{'to_handle':'bob','amount':800},'ada','old-hold')
 c=create('/authorizations/'+h['authorization_id']+'/capture',{'amount':100,'final':False},'bob','old-capture')
 create('/payments/'+p['payment_id']+'/corrections',{'expected_revision':1,'amount':900,'effective_at':p['created_at'],'reason':'old'},'ada','old-correction')
 snapshot=expect(call('/statement?limit=1',token=t['ada'],target=old),200);oldmoney=money(t,old)
 expect(call('/_test/import','POST',export(old)),204);assert money(t)==oldmoney
 expect(call('/_test/import','POST',export(),target=other),204)
 for target in (base,other):
  for path,b,h,key,response in writes:
   before=export(target);assert expect(call(path,'POST',b,t[h],key,target=target),200)==response;assert export(target)==before
  frozen=expect(call('/statement?'+urllib.parse.urlencode({'snapshot':snapshot['snapshot'],'limit':1}),token=t['ada'],target=target),200)
  assert {k:v for k,v in frozen.items() if k!='snapshot'}=={k:v for k,v in snapshot.items() if k!='snapshot'}
 expect(refund(t,c,100,'new-refund'),201)
 held=expect(call('/me',token=t['ada']),200)['held'];assert held==700
case('real Stage3 authorization/capture/correction receipts and snapshot survive two Stage4 imports',predecessor_receipts)

def corrupt_revision_import():
 t=seed();p=pay(t);expect(batch(t,[item(p,800)]),201)
 good=export();expect(call('/_test/import','POST',good,target=other),204)
 assert money(t,other)==[9200,5800,2000]
 before=export(other);bad=copy.deepcopy(good)
 # This negative probe uses the candidate's own documented implementation-defined
 # export shape; destination bytes and credentials never leave the probe process.
 state=bad['state']
 if isinstance(state.get('revisions'),dict):
  history=state['revisions'][p['payment_id']]
 else:
  record=next(z for z in state['payments'] if z.get('payment_id',z.get('id'))==p['payment_id'])
  history=record['revisions']
 assert len(history)==2,'positive export must contain initial and correction history'
 for name in ('effective_at','recorded_at','reason'):history[0].pop(name)
 expect(call('/_test/import','POST',bad,target=other),422,'validation_failed')
 assert export(other)==before,'invalid history replaced destination state'
 assert money(t,other)==[9200,5800,2000]
case('malformed nested payment revision import rejects422 and preserves healthy destination',corrupt_revision_import)

def deterministic_model():
 t=seed((1000000,1000000,1000000));rng=random.Random(27062026);expected=[1000000]*3;people=['ada','bob','cy'];records=[]
 for i in range(6):
  fr=i%3;to=(fr+1)%3;n=2000+i*100;p=pay(t,n,people[fr],people[to],'model-payment-'+str(i));records.append({'p':p,'fr':fr,'to':to,'current':n,'refunded':0,'revision':1});expected[fr]-=n;expected[to]+=n
 for i in range(100):
  z=rng.choice(records);p=z['p'];fr=z['fr'];to=z['to']
  if rng.randrange(2) and z['current']>z['refunded']:
   n=rng.randint(1,z['current']-z['refunded']);expect(refund(t,p,n,'model-refund-'+str(i),people[to]),201);z['refunded']+=n;expected[to]-=n;expected[fr]+=n
  else:
   n=rng.randint(z['refunded'],6000);expect(batch(t,[item(p,n,z['revision'])],'model-batch-'+str(i)),201);diff=n-z['current'];expected[fr]-=diff;expected[to]+=diff;z['current']=n;z['revision']+=1
  assert money(t)==expected,f'operation{i} differs from independent integer balance model'
  assert sum(expected)==3000000 and min(expected)>=0
  if i in (19,59,99):
   expect(call('/_test/import','POST',export(),target=other),204);assert money(t,other)==expected
case('100 seeded random refunds/corrections agree with independent conserved integer model',deterministic_model)

report={'source_revision':os.environ['POCKETFUL_REVISION'],'previous_revision':os.environ['POCKETFUL_OLD_REVISION'],'seed':27062026,'cases':cases,'passed':sum(c['status']=='PASS' for c in cases),'failed':sum(c['status']=='FAIL' for c in cases),'spec_interpretation':'Stage3 ordinary correction fields explicitly reject invalid input422; Stage4 reuses those rules, overriding the generic Stage1 wrong-type400 default. Earlier400-oracle report retained; no changed product assertion is concealed.','scope':'actual isolated HTTP execution; no organizer implementation; no raw export/token persistence'}
(out/'adversarial-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));raise SystemExit(bool(report['failed']))
