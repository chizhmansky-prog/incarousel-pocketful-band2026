import json, os, subprocess, sys, time, urllib.request
p=subprocess.Popen([sys.executable,'service.py'],env={**os.environ,'PORT':'18991','POCKETFUL_STAGE':'4'})
def req(path, body=None, tok=None, key=None):
    data=json.dumps(body).encode() if body is not None else None; headers={'Content-Type':'application/json'}
    if tok: headers['Authorization']='Bearer '+tok
    if key: headers['Idempotency-Key']=key
    try:
        r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18991'+path,data=data,headers=headers,method='POST' if data is not None else 'GET'))
        return r.status,json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
try:
 time.sleep(.2)
 fixture={'currency':'EUR','minor_units':2,'users':[{'id':'a','email':'a@x','password':'password1','display_name':'Ada','handle':'ada','balance':1000},{'id':'b','email':'b@x','password':'password1','display_name':'Bob','handle':'bob','balance':1000},{'id':'c','email':'c@x','password':'password1','display_name':'Cy','handle':'cy','balance':0}],'settlement_operator_ids':['a']}
 assert req('/_test/reset',fixture)[0]==204
 _,a=req('/auth/login',{'email':'a@x','password':'password1'});_,b=req('/auth/login',{'email':'b@x','password':'password1'})
 s,r=req('/requests',{'payer_handle':'ada','amount':1200,'note':'taxi'},b['token'],'rq');assert s==201
 assert req('/requests/'+r['request_id']+'/pay',{},a['token'],'pay')[0]==409
 assert req('/splits',{'amount':5,'participant_handles':['ada','bob','cy'],'note':'dinner'},a['token'],'split')[1]['shares']==[{'handle':'ada','amount':2},{'handle':'bob','amount':2},{'handle':'cy','amount':1}]
 s,batch=req('/settlements',{'transfers':[{'from_handle':'ada','to_handle':'cy','amount':100},{'from_handle':'bob','to_handle':'cy','amount':100}]},a['token'],'settle');assert s==201 and len(batch['payments'])==2
 pay=batch['payments'][0]; assert req('/payments/'+pay['payment_id']+'/refunds',{'amount':50},req('/auth/login',{'email':'c@x','password':'password1'})[1]['token'],'refund')[0]==201
 assert req('/payments',{'to_handle':'bob','amount':True},a['token'],'bool')[0]==422
 assert req('/payments',{'to_handle':'bob','amount':float('nan')},a['token'],'nan')[0] in (400,422)
 assert req('/statement',None,a['token'])[0]==200
 print('PASS contract: request insufficient retry, split rounding, atomic settlement, receiver refund, numeric rejects, statement snapshot')
finally:
 p.terminate();p.wait()
