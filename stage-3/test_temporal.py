import json, os, subprocess, sys, time, urllib.request
PORT='18993'
p=subprocess.Popen([sys.executable,'service.py'],env={**os.environ,'PORT':PORT,'POCKETFUL_STAGE':'3'})
def req(path, body=None, token=None, key=None):
 data=json.dumps(body).encode() if body is not None else None; headers={'Content-Type':'application/json'}
 if token: headers['Authorization']='Bearer '+token
 if key: headers['Idempotency-Key']=key
 try:
  r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+PORT+path,data=data,headers=headers,method='POST' if data is not None else 'GET'));return r.status,json.loads(r.read() or b'{}')
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read() or b'{}')
try:
 for _ in range(30):
  try:
   if req('/health')[0]==200:break
  except Exception:time.sleep(.1)
 else:raise AssertionError('service did not become healthy')
 fixture={'currency':'EUR','minor_units':2,'users':[{'id':'a','email':'a@x','password':'password1','display_name':'Ada','handle':'ada','balance':1000},{'id':'b','email':'b@x','password':'password1','display_name':'Bob','handle':'bob','balance':1000}]}
 assert req('/_test/reset',fixture)[0]==204
 a=req('/auth/login',{'email':'a@x','password':'password1'})[1]['token']
 s,pay=req('/payments',{'to_handle':'bob','amount':300},a,'pay');assert s==201
 body={'expected_revision':1,'amount':200,'effective_at':pay['created_at'],'reason':'actual amount'}
 s,rev=req('/payments/'+pay['payment_id']+'/corrections',body,a,'correct');assert s==201 and rev['revision']==2
 assert req('/payments/'+pay['payment_id']+'/corrections',body,a,'correct')[0]==200
 assert req('/payments/'+pay['payment_id']+'/corrections',{**body,'amount':201},a,'correct')[0]==409
 s,statement=req('/statement',None,a);assert s==200 and statement['entries'][0]['payment']['amount']==200
 snapshot=statement['snapshot'];assert req('/payments',{'to_handle':'bob','amount':10},a,'later')[0]==201
 s,frozen=req('/statement?snapshot='+snapshot,None,a);assert s==200 and len(frozen['entries'])==1 and frozen['entries'][0]['payment']['amount']==200
 print('PASS stage3: correction replay/key conflict, selected statement, frozen snapshot')
finally:
 p.terminate();p.wait()
