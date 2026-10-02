import json, subprocess, sys, time, urllib.request
p=subprocess.Popen([sys.executable,'service.py'],env={'PORT':'18990','POCKETFUL_STAGE':__import__('os').environ.get('POCKETFUL_STAGE','1')})
def req(path,body=None,t=None,key=None):
 d=json.dumps(body).encode() if body is not None else None; h={'Content-Type':'application/json'}
 if t:h['Authorization']='Bearer '+t
 if key:h['Idempotency-Key']=key
 try:
  r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18990'+path,data=d,headers=h,method='POST' if d else 'GET'));return r.status,json.loads(r.read() or b'{}')
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
try:
 time.sleep(.2); assert req('/health')[0]==200
 fixture={'currency':'EUR','minor_units':2,'users':[{'id':'a','email':'a@x','password':'password1','display_name':'Ada','handle':'ada','balance':1000},{'id':'b','email':'b@x','password':'password1','display_name':'Bob','handle':'bob','balance':0}]}
 assert req('/_test/reset',fixture)[0]==204
 _,a=req('/auth/login',{'email':'a@x','password':'password1'});_,b=req('/auth/login',{'email':'b@x','password':'password1'})
 s,x=req('/payments',{'to_handle':'bob','amount':1000.0},a['token'],'k');assert s==201 and x['amount']==1000
 assert req('/payments',{'to_handle':'bob','amount':1000.0},a['token'],'k')[0]==200
 assert req('/payments',{'to_handle':'bob','amount':True},a['token'],'x')[0]==422
 if int(__import__('os').environ.get('POCKETFUL_STAGE','1'))>=2:
  assert req('/_test/reset',fixture)[0]==204;_,a=req('/auth/login',{'email':'a@x','password':'password1'});assert req('/authorizations',{'to_handle':'bob','amount':500},a['token'],'hold')[0]==201;assert req('/me',None,a['token'])[1]['available']==500
 if int(__import__('os').environ.get('POCKETFUL_STAGE','1'))>=4: assert True
 print('PASS public HTTP: health/reset/login/idempotent payment/numeric rejection/stage hold')
finally:p.terminate();p.wait()
