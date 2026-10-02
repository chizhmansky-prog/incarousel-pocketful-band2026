#!/usr/bin/env python3
import json, os, re, secrets, threading
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

STAGE=int(os.environ.get('POCKETFUL_STAGE','1'))
LOCK=threading.RLock()
STATE={}
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def err(code,msg,status): return status,{'error':{'code':code,'message':msg}}
def integer(v, minimum=0, maximum=1000000000):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not isinstance(v,float) and False: raise ValueError
    if isinstance(v,float) and (not v.is_integer() or not v==v or abs(v)==float('inf')): raise ValueError
    v=int(v)
    if v<minimum or v>maximum: raise ValueError
    return v
def auth(h):
    a=h.headers.get('Authorization','')
    return STATE.get('tokens',{}).get(a[7:]) if a.startswith('Bearer ') else None
def init_state(f):
    global STATE
    if not isinstance(f,dict) or f.get('minor_units') not in (0,2,3) or not isinstance(f.get('users'),list): raise ValueError
    users={}; handles={}
    for u in f['users']:
      if not isinstance(u,dict) or not isinstance(u.get('id'),str) or not isinstance(u.get('handle'),str) or not re.fullmatch(r'[a-z0-9_]{1,20}',u['handle']): raise ValueError
      b=integer(u.get('balance'),0,2**53)
      if u['id'] in users or u['handle'] in handles: raise ValueError
      users[u['id']]={'id':u['id'],'email':u.get('email',''),'password':u.get('password',''),'display_name':u.get('display_name',''),'handle':u['handle'],'total':b}
      handles[u['handle']]=u['id']
    STATE={'currency':f.get('currency','EUR'),'minor_units':f['minor_units'],'users':users,'handles':handles,'payments':deepcopy(f.get('payments',[])),'requests':deepcopy(f.get('requests',[])),'authorizations':deepcopy(f.get('authorizations',[])) if STAGE>=2 else [],'operators':set(f.get('settlement_operator_ids',[])),'tokens':{},'idempotency':{},'revisions':{},'snapshots':{},'ttl':f.get('authorization_ttl_seconds',600),'seq':0}
    for p in STATE['payments']:
      p.setdefault('created_at',now());p.setdefault('visibility','public');p.setdefault('note','');p.setdefault('request_id',None);p.setdefault('authorization_id',None);p.setdefault('refund_of',None);p.setdefault('settlement_id',None)
      STATE['revisions'][p['id']]=[{'revision':1,'amount':p['amount'],'effective_at':p['created_at'],'recorded_at':p['created_at'],'reason':''}]
def pid(prefix):
 STATE['seq']+=1; return f'{prefix}_{STATE["seq"]}'
def hold(u):
 if STAGE<2:return 0
 t=now(); return sum(a['amount']-a.get('captured_amount',0) for a in STATE['authorizations'] if a['from_user_id']==u and a.get('status')=='open' and a['expires_at']>t)
def me(uid):
 u=STATE['users'][uid]; d={'user_id':uid,'display_name':u['display_name'],'handle':u['handle'],'balance':u['total'],'currency':STATE['currency'],'minor_units':STATE['minor_units']}
 if STAGE>=2: d.update(total=u['total'],held=hold(uid),available=u['total']-hold(uid))
 return d
def receipt(p): return deepcopy(p)
def valid_write(h,uid,body):
 k=h.headers.get('Idempotency-Key')
 if not k:return None,err('missing_idempotency_key','key required',400)
 if not isinstance(k,str) or not 1<=len(k)<=255:return None,err('validation_failed','bad key',422)
 key=(uid,h.command,urlparse(h.path).path,k); canonical=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False)
 old=STATE['idempotency'].get(key)
 if old:
  if old[0]!=canonical:return None,err('idempotency_key_reuse','different request',409)
  return ('replay',old[1]),None
 return (key,canonical),None
def finish_idem(key,canonical,status,obj): STATE['idempotency'][key]=(canonical,obj);return status,obj
def pay(uid,b,kind='payment'):
 try: amt=integer(b.get('amount'),1)
 except ValueError: return err('validation_failed','amount',422)
 to=STATE['handles'].get(b.get('to_handle'))
 if not to:return err('not_found','recipient',404)
 if to==uid:return err('self_payment','self',422)
 if STATE['users'][uid]['total']-hold(uid)<amt:return err('insufficient_funds','funds',409)
 p={'payment_id':pid('p'),'from_user_id':uid,'from_handle':STATE['users'][uid]['handle'],'to_user_id':to,'to_handle':STATE['users'][to]['handle'],'amount':amt,'currency':STATE['currency'],'note':b.get('note',''),'visibility':b.get('visibility','public'),'request_id':None,'authorization_id':None,'refund_of':None,'settlement_id':None,'created_at':now()}
 if not isinstance(p['note'],str) or len(p['note'])>200 or p['visibility'] not in ('public','private'):return err('validation_failed','fields',422)
 STATE['users'][uid]['total']-=amt;STATE['users'][to]['total']+=amt; STATE['payments'].append(p);STATE['revisions'][p['payment_id']]=[{'revision':1,'amount':amt,'effective_at':p['created_at'],'recorded_at':p['created_at'],'reason':''}]
 return 201,p
def list_page(items,q,key):
 lim=int(q.get('limit',['50'])[0]); off=int(q.get('offset',['0'])[0]); return {key:items[off:off+lim],'has_more':off+lim<len(items)}
class App(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def send(self,status,obj=None):
  self.send_response(status)
  if obj is not None:
   raw=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode();self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
  self.end_headers()
  if obj is not None:self.wfile.write(raw)
 def body(self):
  try:return json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')) or 0).decode() or '{}')
  except:return None
 def do_GET(self):
  u=urlparse(self.path);q=parse_qs(u.query,keep_blank_values=True)
  if u.path=='/health':return self.send(200,{'status':'ok'})
  with LOCK:
   uid=auth(self)
   if u.path=='/_test/export':return self.send(200,{'track':'pocketful','format_version':STAGE,'state':deepcopy(STATE)})
   if not uid:return self.send(*err('unauthenticated','token',401))
   if u.path=='/me':return self.send(200,me(uid))
   if u.path=='/activity':
    ps=[p for p in STATE['payments'] if p['visibility']=='public' or uid in (p['from_user_id'],p['to_user_id'])];return self.send(200,list_page(list(reversed(ps)),q,'payments'))
   if u.path=='/requests':return self.send(200,list_page(list(reversed([r for r in STATE['requests'] if uid in (r['requester_id'],r['payer_id'])])),q,'requests'))
   if u.path=='/authorizations' and STAGE>=2:return self.send(200,list_page(list(reversed([a for a in STATE['authorizations'] if uid in(a['from_user_id'],a['to_user_id'])])),q,'authorizations'))
   if u.path.startswith('/payments/') and u.path.endswith('/revisions') and STAGE>=3:
    p=u.path.split('/')[2]; x=next((x for x in STATE['payments'] if x['payment_id']==p),None)
    if not x or uid not in (x['from_user_id'],x['to_user_id']):return self.send(*err('not_found','payment',404))
    return self.send(200,{'revisions':STATE['revisions'][p]})
   if u.path=='/statement' and STAGE>=3:
    es=[]; bal=0
    for p in sorted([p for p in STATE['payments'] if uid in(p['from_user_id'],p['to_user_id'])],key=lambda x:(x['created_at'],x['payment_id'])):
     delta=p['amount'] if p['to_user_id']==uid else -p['amount'];bal+=delta;es.append({'payment':receipt(p),'delta':delta,'balance_after':bal,'revision':len(STATE['revisions'][p['payment_id']]),'effective_at':p['created_at'],'recorded_at':p['created_at']})
    return self.send(200,dict(opening_balance=0,entries=es,closing_balance=bal,has_more=False,snapshot=pid('snap')))
   return self.send(*err('not_found','route',404))
 def do_POST(self):
  u=urlparse(self.path); b=self.body()
  if b is None or not isinstance(b,dict):return self.send(*err('malformed_request','json',400))
  with LOCK:
   if u.path=='/_test/reset':
    try:init_state(b);return self.send(204)
    except:return self.send(*err('validation_failed','fixture',422))
   if u.path=='/_test/import':
    try:
     if b.get('track')!='pocketful' or not isinstance(b.get('state'),dict):raise ValueError
     global STATE; STATE=deepcopy(b['state']);return self.send(204)
    except:return self.send(*err('validation_failed','import',422))
   if u.path=='/auth/login':
    x=next((v for v in STATE['users'].values() if v['email']==b.get('email') and v['password']==b.get('password')),None)
    if not x:return self.send(*err('unauthenticated','login',401))
    t=secrets.token_urlsafe(24);STATE['tokens'][t]=x['id'];return self.send(200,{'user_id':x['id'],'display_name':x['display_name'],'token':t})
   if u.path=='/auth/signup':
    e=b.get('email');pw=b.get('password');name=b.get('display_name')
    if not all(isinstance(x,str) for x in(e,pw,name)) or '@' not in e or len(pw)<8:return self.send(*err('validation_failed','signup',422))
    if any(x['email']==e for x in STATE['users'].values()):return self.send(*err('email_taken','email',409))
    h=re.sub('[^a-z0-9_]','_',e.split('@')[0].lower())[:20]
    if h in STATE['handles']:return self.send(*err('handle_taken','handle',409))
    i=pid('u');STATE['users'][i]={'id':i,'email':e,'password':pw,'display_name':name,'handle':h,'total':0};STATE['handles'][h]=i;t=secrets.token_urlsafe(24);STATE['tokens'][t]=i;return self.send(201,{'user_id':i,'display_name':name,'token':t})
   uid=auth(self)
   if not uid:return self.send(*err('unauthenticated','token',401))
   idem,fail=valid_write(self,uid,b) if (u.path in ['/payments','/requests','/splits','/settlements','/authorizations','/correction-batches'] or u.path.endswith(('/pay','/capture','/corrections','/refunds'))) else (None,None)
   if fail:return self.send(*fail)
   if idem and idem[0]=='replay':return self.send(200,idem[1])
   if u.path=='/payments':
    s,o=pay(uid,b); return self.send(*finish_idem(*idem,s,o) if s==201 else (s,o))
   if u.path=='/requests':
    try:amt=integer(b.get('amount'),1)
    except:return self.send(*err('validation_failed','amount',422))
    to=STATE['handles'].get(b.get('payer_handle')); 
    if not to:return self.send(*err('not_found','payer',404))
    r={'request_id':pid('rq'),'requester_id':uid,'requester_handle':STATE['users'][uid]['handle'],'payer_id':to,'payer_handle':b['payer_handle'],'amount':amt,'currency':STATE['currency'],'note':b.get('note',''),'status':'pending','payment_id':None,'created_at':now()};STATE['requests'].append(r);return self.send(*finish_idem(*idem,201,r))
   if u.path.endswith('/pay'):
    rid=u.path.split('/')[2];r=next((x for x in STATE['requests'] if x['request_id']==rid),None)
    if not r:return self.send(*err('not_found','request',404))
    if r['payer_id']!=uid:return self.send(*err('forbidden','payer',403))
    if r['status']!='pending':return self.send(*err('request_not_pending','state',409))
    s,p=pay(uid,{'to_handle':r['requester_handle'],'amount':r['amount'],'visibility':b.get('visibility','public')})
    if s==201:r['status']='paid';r['payment_id']=p['payment_id'];p['request_id']=rid;return self.send(*finish_idem(*idem,201,p))
    return self.send(s,p)
   if u.path=='/authorizations' and STAGE>=2:
    try:amt=integer(b.get('amount'),1)
    except:return self.send(*err('validation_failed','amount',422))
    to=STATE['handles'].get(b.get('to_handle'))
    if not to:return self.send(*err('not_found','recipient',404))
    if STATE['users'][uid]['total']-hold(uid)<amt:return self.send(*err('insufficient_funds','funds',409))
    a={'authorization_id':pid('a'),'from_user_id':uid,'from_handle':STATE['users'][uid]['handle'],'to_user_id':to,'to_handle':b['to_handle'],'amount':amt,'captured_amount':0,'currency':STATE['currency'],'note':b.get('note',''),'visibility':b.get('visibility','public'),'status':'open','expires_at':(datetime.now(timezone.utc)+timedelta(seconds=STATE['ttl'])).isoformat(timespec='seconds'),'payment_id':None,'created_at':now(),'remaining_amount':amt};STATE['authorizations'].append(a);return self.send(*finish_idem(*idem,201,a))
   if u.path.endswith('/capture') and STAGE>=2:
    aid=u.path.split('/')[2];a=next((x for x in STATE['authorizations'] if x['authorization_id']==aid),None)
    if not a:return self.send(*err('not_found','authorization',404))
    if a['to_user_id']!=uid:return self.send(*err('forbidden','receiver',403))
    if a['status']!='open':return self.send(*err('authorization_not_open','closed',409))
    amount=a['amount']-a['captured_amount'] if 'amount' not in b else b['amount']
    try:amount=integer(amount,1,a['amount']-a['captured_amount'])
    except:return self.send(*err('capture_exceeds_authorization','amount',422))
    p={'to_handle':a['to_handle'],'amount':amount,'note':a['note'],'visibility':a['visibility']};s,p=pay(a['from_user_id'],p)
    if s!=201:return self.send(s,p)
    p['authorization_id']=aid;a['captured_amount']+=amount;a['payment_id']=p['payment_id'];a['remaining_amount']=a['amount']-a['captured_amount']
    if b.get('final',True) or a['remaining_amount']==0:a['status']='captured'
    return self.send(*finish_idem(*idem,201,p))
   if u.path.endswith('/refunds') and STAGE>=4:
    target=u.path.split('/')[2];p=next((x for x in STATE['payments'] if x['payment_id']==target),None)
    if not p:return self.send(*err('not_found','payment',404))
    if p.get('refund_of'):return self.send(*err('invalid_refund_target','refund',422))
    if p['to_user_id']!=uid:return self.send(*err('forbidden','receiver',403))
    used=sum(x['amount'] for x in STATE['payments'] if x.get('refund_of')==target)
    try:amt=integer(b.get('amount'),1,p['amount']-used)
    except:return self.send(*err('refund_exceeds_payment','amount',422))
    s,r=pay(uid,{'to_handle':p['from_handle'],'amount':amt,'note':p['note'],'visibility':p['visibility']})
    if s==201:r['refund_of']=target;return self.send(*finish_idem(*idem,201,r))
    return self.send(s,r)
   return self.send(*err('not_found','route',404))
if __name__=='__main__':
 init_state({'currency':'EUR','minor_units':2,'users':[]});ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),App).serve_forever()
