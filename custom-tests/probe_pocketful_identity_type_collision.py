"""Numeric canonicalization must not collide with a user-supplied JSON object."""
import json,os,pathlib,urllib.error,urllib.request
base=os.environ['POCKETFUL_BASE_URL'];out=pathlib.Path(os.environ['POCKETFUL_EVIDENCE_OUT'])
def call(path,method='GET',body=None,token=None,key=None):
 h={'Accept':'application/json'}
 if body is not None:h['Content-Type']='application/json'
 if token:h['Authorization']='Bearer '+token
 if key:h['Idempotency-Key']=key
 req=urllib.request.Request(base+path,method=method,headers=h,data=None if body is None else json.dumps(body).encode())
 try:
  with urllib.request.urlopen(req,timeout=5) as x:s,b=x.status,x.read()
 except urllib.error.HTTPError as x:s,b=x.code,x.read()
 return s,json.loads(b) if b else None
def expect(r,status,code=None):
 assert r[0]==status,f'expected{status}, observed{r[0]}'
 if code:assert r[1]['error']['code']==code
 return r[1]
cases=[]
try:
 fixture={'currency':'EUR','minor_units':2,'users':[{'id':'u_'+h,'handle':h,'email':h+'@example.test','password':'fixture password','display_name':h,'balance':1000} for h in ('ada','bob')],'payments':[],'requests':[]}
 expect(call('/_test/reset','POST',fixture),204)
 t=expect(call('/auth/login','POST',{'email':'ada@example.test','password':'fixture password'}),200)['token']
 a={'to_handle':'bob','amount':1,'ignored':1};b={**a,'ignored':{'$number':'1'}}
 receipt=expect(call('/payments','POST',a,t,'typed-json'),201)
 assert expect(call('/payments','POST',a,t,'typed-json'),200)==receipt
 before=expect(call('/_test/export'),200)
 expect(call('/payments','POST',b,t,'typed-json'),409,'idempotency_key_reuse')
 assert expect(call('/_test/export'),200)==before
 cases.append({'case':'JSON number and a lookalike marker object have distinct identity','status':'PASS'})
except Exception as e:cases.append({'case':'JSON number and a lookalike marker object have distinct identity','status':'FAIL','finding':str(e)})
report={'source_revision':os.environ['POCKETFUL_REVISION'],'cases':cases,'passed':sum(c['status']=='PASS' for c in cases),'failed':sum(c['status']=='FAIL' for c in cases),'boundary':'Actual source-bound HTTP; positive original201/identical200 then typed conflict409 and atomicity; no tokens or exports saved'}
out.mkdir(parents=True,exist_ok=True);(out/'identity-type-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report));raise SystemExit(bool(report['failed']))
