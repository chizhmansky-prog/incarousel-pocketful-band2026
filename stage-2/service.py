#!/usr/bin/env python3
"""Pocketful in-memory HTTP service. Stage behaviour is selected at image build time."""
import base64, hashlib, json, os, re, secrets, threading
from decimal import Decimal, InvalidOperation
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STAGE=int(os.environ.get("POCKETFUL_STAGE", "4")); LOCK=threading.RLock(); S={}
def instant(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def parse_instant(x):
    if not isinstance(x,str) or not x: raise ValueError()
    d=datetime.fromisoformat(x.replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError()
    return d.astimezone(timezone.utc)
def fail(code,status): return status,{"error":{"code":code,"message":code.replace("_"," ")}}
def nint(x,lo=0,hi=1000000000):
    if isinstance(x,bool) or not isinstance(x,(int,float,Decimal)): raise ValueError()
    try:
        d=Decimal(str(x)) if not isinstance(x,Decimal) else x
    except (InvalidOperation, ValueError): raise ValueError()
    if not d.is_finite() or d != d.to_integral_value(): raise ValueError()
    x=int(d)
    if not lo<=x<=hi: raise ValueError()
    return x
def hpassword(p):
    return base64.b64encode(hashlib.scrypt(p.encode(),salt=b"pocketful-v1",n=2**14,r=8,p=1)).decode()
def same_password(p,stored): return isinstance(p,str) and stored==hpassword(p)
def ident(prefix): S["seq"]+=1; return f"{prefix}_{S['seq']}"
def json_identity(x):
    if x is None or isinstance(x,(str,bool)): return x
    if isinstance(x,(int,float,Decimal)) and not isinstance(x,bool):
        try: d=Decimal(str(x)) if not isinstance(x,Decimal) else x
        except (InvalidOperation,ValueError): raise ValueError()
        if not d.is_finite(): raise ValueError()
        sign,digits,exponent=d.as_tuple(); digits=''.join(map(str,digits))
        digits=digits.lstrip('0') or '0'
        if digits=='0': return {"$number":"0"}
        while digits.endswith('0'):
            digits=digits[:-1]; exponent+=1
        if exponent>=0: value=digits+'0'*exponent
        else:
            cut=len(digits)+exponent
            value=(digits[:cut]+'.'+digits[cut:]) if cut>0 else '0.'+'0'*(-cut)+digits
        return {"$number":('-' if sign else '')+value}
    if isinstance(x,list): return [json_identity(v) for v in x]
    if isinstance(x,dict): return {str(k):json_identity(v) for k,v in x.items()}
    raise ValueError()
def body_value(b): return json.dumps(json_identity(b),sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
def json_safe(x):
    if isinstance(x,Decimal): return int(x) if x == x.to_integral_value() else float(x)
    if isinstance(x,set): return sorted(x)
    if isinstance(x,tuple): return [json_safe(v) for v in x]
    if isinstance(x,list): return [json_safe(v) for v in x]
    if isinstance(x,dict): return {str(k):json_safe(v) for k,v in x.items()}
    return x
def export_state():
    state=json_safe(deepcopy(S))
    state["idempotency"]=[{"user_id":k[0],"method":k[1],"path":k[2],"key":k[3],"identity":v[0],"response":json_safe(v[1])} for k,v in S["idempotency"].items()]
    return state
def decoded_number(x):
    if isinstance(x,Decimal):
        if not x.is_finite() or x != x.to_integral_value(): raise ValueError()
        return int(x)
    if isinstance(x,list): return [decoded_number(v) for v in x]
    if isinstance(x,dict): return {k:decoded_number(v) for k,v in x.items()}
    return x
def import_state(raw):
    raw=decoded_number(raw)
    if not isinstance(raw,dict): raise ValueError()
    required=("currency","minor_units","users","handles","tokens","idempotency","payments","requests","operators","seq")
    if any(k not in raw for k in required) or raw.get("minor_units") not in (0,2,3): raise ValueError()
    users=raw["users"];handles=raw["handles"];tokens=raw["tokens"]
    if not isinstance(users,dict) or not isinstance(handles,dict) or not isinstance(tokens,dict) or not isinstance(raw["operators"],list): raise ValueError()
    for uid,u in users.items():
        if not isinstance(uid,str) or not isinstance(u,dict) or u.get("id")!=uid or not isinstance(u.get("password_hash"),str) or not isinstance(u.get("email"),str) or not isinstance(u.get("display_name"),str) or not isinstance(u.get("handle"),str): raise ValueError()
        nint(u.get("total"),0,2**53)
        if handles.get(u["handle"]) != uid: raise ValueError()
    if any(not isinstance(k,str) or v not in users for k,v in tokens.items()): raise ValueError()
    if any(not isinstance(v,str) or v not in users for v in raw["operators"]): raise ValueError()
    if not isinstance(raw["payments"],list) or not isinstance(raw["requests"],list) or not isinstance(raw["idempotency"],list): raise ValueError()
    seen=set()
    for p in raw["payments"]:
        if not isinstance(p,dict) or not isinstance(p.get("payment_id"),str) or p["payment_id"] in seen or p.get("from_user_id") not in users or p.get("to_user_id") not in users: raise ValueError()
        seen.add(p["payment_id"]);nint(p.get("amount"),0);parse_instant(p.get("created_at"));
        if p.get("visibility") not in ("public","private"): raise ValueError()
    for r in raw["requests"]:
        if not isinstance(r,dict) or not isinstance(r.get("request_id"),str) or r.get("requester_id") not in users or r.get("payer_id") not in users or r.get("status") not in ("pending","paid","declined","cancelled"): raise ValueError()
        nint(r.get("amount"),0);parse_instant(r.get("created_at"))
    revisions=raw.get("revisions",{})
    if not isinstance(revisions,dict): raise ValueError()
    for p in raw["payments"]:
        pid=p["payment_id"]; rows=revisions.get(pid)
        if rows is None:
            revisions[pid]=[{"payment_id":pid,"revision":1,"amount":p["amount"],"effective_at":p["created_at"],"recorded_at":p["created_at"],"reason":""}]; continue
        if not isinstance(rows,list) or not rows: raise ValueError()
        previous_recorded=None
        for number,row in enumerate(rows,1):
            if not isinstance(row,dict) or row.get("payment_id")!=pid or row.get("revision")!=number or not isinstance(row.get("reason"),str) or len(row["reason"])>200: raise ValueError()
            nint(row.get("amount"),0); effective=parse_instant(row.get("effective_at")); recorded=parse_instant(row.get("recorded_at"))
            if effective>datetime.now(timezone.utc) or (previous_recorded is not None and recorded<=previous_recorded): raise ValueError()
            previous_recorded=recorded
    if any(pid not in seen for pid in revisions): raise ValueError()
    raw["revisions"]=revisions
    idem={}
    for item in raw["idempotency"]:
        if not isinstance(item,dict) or not all(isinstance(item.get(k),str) for k in ("user_id","method","path","key","identity")) or item["user_id"] not in users: raise ValueError()
        k=(item["user_id"],item["method"],item["path"],item["key"])
        if k in idem: raise ValueError()
        idem[k]=(item["identity"],deepcopy(item.get("response")))
    candidate=deepcopy(raw);candidate["operators"]=set(raw["operators"]);candidate["idempotency"]=idem
    candidate.setdefault("authorizations",[]);candidate.setdefault("revisions",{});candidate.setdefault("snapshots",{});candidate.setdefault("ttl",600);candidate.setdefault("initial",sum(u["total"] for u in users.values()))
    if not isinstance(candidate["seq"],int) or isinstance(candidate["seq"],bool) or candidate["seq"]<0: raise ValueError()
    return candidate
def visible(p,u): return p["visibility"]=="public" or u in (p["from_user_id"],p["to_user_id"])
def expire():
    if STAGE<2:return
    t=datetime.now(timezone.utc)
    for a in S["authorizations"]:
        if a["status"]=="open" and parse_instant(a["expires_at"])<=t:
            a["status"]="expired";a["closed_at"]=a["expires_at"];a["remaining_amount"]=0
def held(u,at=None):
    expire(); t=at or datetime.now(timezone.utc); total=0
    for a in S.get("authorizations",[]):
        if a["from_user_id"]==u and a["status"]=="open" and parse_instant(a["expires_at"])>t: total+=a["amount"]-a.get("captured_amount",0)
    return total
def balance(u): return S["users"][u]["total"]
def user_me(u):
    x=S["users"][u]; d={"user_id":u,"display_name":x["display_name"],"handle":x["handle"],"balance":x["total"],"currency":S["currency"],"minor_units":S["minor_units"]}
    if STAGE>=2: d.update(total=x["total"],held=held(u),available=x["total"]-held(u))
    return d
def auth(h):
    a=h.headers.get("Authorization",""); return S.get("tokens",{}).get(a[7:]) if a.startswith("Bearer ") else None
def getpay(pid): return next((p for p in S["payments"] if p["payment_id"]==pid),None)
def getreq(rid): return next((r for r in S["requests"] if r["request_id"]==rid),None)
def geta(aid): return next((a for a in S.get("authorizations",[]) if a["authorization_id"]==aid),None)
def receipt(x): return deepcopy(x)
def _init(f):
    global S
    if not isinstance(f,dict) or f.get("minor_units") not in (0,2,3) or not isinstance(f.get("users"),list): raise ValueError()
    users={};handles={}; initial=0
    for u in f["users"]:
        if not isinstance(u,dict) or not isinstance(u.get("id"),str) or not isinstance(u.get("email"),str) or not isinstance(u.get("password"),str) or not isinstance(u.get("display_name"),str) or not isinstance(u.get("handle"),str) or not re.fullmatch(r"[a-z0-9_]{1,20}",u["handle"]): raise ValueError()
        b=nint(u.get("balance"),0,2**53)
        if u["id"] in users or u["handle"] in handles: raise ValueError()
        users[u["id"]]={"id":u["id"],"email":u["email"],"password_hash":hpassword(u["password"]),"display_name":u["display_name"],"handle":u["handle"],"total":b};handles[u["handle"]]=u["id"];initial+=b
    S={"currency":f.get("currency","EUR"),"minor_units":int(f["minor_units"]),"users":users,"handles":handles,"tokens":{},"idempotency":{},"payments":[],"requests":[],"authorizations":[],"operators":set(f.get("settlement_operator_ids",[])),"revisions":{},"snapshots":{},"ttl":nint(f.get("authorization_ttl_seconds",600),1,2**53),"seq":0,"initial":initial}
    if not isinstance(S["ttl"],int) or isinstance(S["ttl"],bool) or S["ttl"]<1: raise ValueError()
    for p0 in f.get("payments",[]):
        if not isinstance(p0,dict): raise ValueError()
        pid0=p0.get("id") or p0.get("payment_id")
        if not isinstance(pid0,str) or pid0 in [p["payment_id"] for p in S["payments"]]: raise ValueError()
        fr=p0.get("from_user_id");to=p0.get("to_user_id");amt=nint(p0.get("amount"),0)
        if fr not in users or to not in users: raise ValueError()
        ts=p0.get("created_at",instant());
        if parse_instant(ts)>datetime.now(timezone.utc): raise ValueError()
        p={"payment_id":pid0,"from_user_id":fr,"from_handle":handles and users[fr]["handle"],"to_user_id":to,"to_handle":users[to]["handle"],"amount":amt,"currency":S["currency"],"note":p0.get("note",""),"visibility":p0.get("visibility","public"),"request_id":p0.get("request_id"),"authorization_id":p0.get("authorization_id"),"refund_of":p0.get("refund_of"),"settlement_id":p0.get("settlement_id"),"created_at":ts}
        if not isinstance(p["note"],str) or p["visibility"] not in ("public","private"): raise ValueError()
        S["payments"].append(p);S["revisions"][pid0]=[{"payment_id":pid0,"revision":1,"amount":amt,"effective_at":ts,"recorded_at":ts,"reason":""}]
    for r in f.get("requests",[]):
        if not isinstance(r,dict) or r.get("requester_id") not in users or r.get("payer_id") not in users: raise ValueError()
        rid=r.get("id") or r.get("request_id");amt=nint(r.get("amount"),1)
        if not isinstance(rid,str) or r.get("status","pending") not in ("pending","paid","declined","cancelled"): raise ValueError()
        S["requests"].append({"request_id":rid,"requester_id":r["requester_id"],"requester_handle":users[r["requester_id"]]["handle"],"payer_id":r["payer_id"],"payer_handle":users[r["payer_id"]]["handle"],"amount":amt,"currency":S["currency"],"note":r.get("note",""),"status":r.get("status","pending"),"payment_id":r.get("payment_id"),"created_at":r.get("created_at",instant())})
    if STAGE>=2:
        for a0 in f.get("authorizations",[]):
            fr=a0.get("from_user_id");to=a0.get("to_user_id"); aid=a0.get("id") or a0.get("authorization_id");amt=nint(a0.get("amount"),1)
            if fr not in users or to not in users or not isinstance(aid,str): raise ValueError()
            cap=nint(a0.get("captured_amount",0),0,amt); status=a0.get("status","open"); exp=a0.get("expires_at")
            if status not in ("open","captured","voided","expired") or not exp: raise ValueError()
            S["authorizations"].append({"authorization_id":aid,"from_user_id":fr,"from_handle":users[fr]["handle"],"to_user_id":to,"to_handle":users[to]["handle"],"amount":amt,"captured_amount":cap,"remaining_amount":amt-cap if status=="open" else 0,"currency":S["currency"],"note":a0.get("note",""),"visibility":a0.get("visibility","public"),"status":status,"expires_at":exp,"payment_id":a0.get("payment_id"),"payment_ids":a0.get("payment_ids",[]),"created_at":a0.get("created_at",instant()),"closed_at":a0.get("closed_at")})
        if any(held(u)>balance(u) for u in users): raise ValueError()
def init(f):
    global S
    previous=deepcopy(S)
    try:
        _init(f)
    except Exception:
        S=previous
        raise

def idem(h,u,b):
    k=h.headers.get("Idempotency-Key")
    if not isinstance(k,str) or not k: return None,fail("missing_idempotency_key",400)
    if len(k)>255:return None,fail("validation_failed",422)
    key=(u,h.command,urlparse(h.path).path,k); v=body_value(b); prior=S["idempotency"].get(key)
    if prior:
        if prior[0]==v:return ("replay",prior[1]),None
        return None,fail("idempotency_key_reuse",409)
    return (key,v),None
def done(i,status,obj): S["idempotency"][i[0]]=(i[1],deepcopy(obj));return status,obj
def normal_fields(b):
    note=b.get("note","");vis=b.get("visibility","public")
    if not isinstance(note,str) or len(note)>200 or vis not in ("public","private"): raise ValueError()
    return note,vis
def commit_move(fr,to,amt,note="",vis="public",created_at=None,**links):
    ts=created_at or instant();p={"payment_id":ident("p"),"from_user_id":fr,"from_handle":S["users"][fr]["handle"],"to_user_id":to,"to_handle":S["users"][to]["handle"],"amount":amt,"currency":S["currency"],"note":note,"visibility":vis,"request_id":links.get("request_id"),"authorization_id":links.get("authorization_id"),"refund_of":links.get("refund_of"),"settlement_id":links.get("settlement_id"),"created_at":ts}
    S["users"][fr]["total"]-=amt;S["users"][to]["total"]+=amt;S["payments"].append(p);S["revisions"][p["payment_id"]]=[{"payment_id":p["payment_id"],"revision":1,"amount":amt,"effective_at":ts,"recorded_at":ts,"reason":""}];return p
def move(fr,to,amt,note="",vis="public",**links):
    if fr==to:return fail("self_payment",422)
    if balance(fr)-held(fr)<amt:return fail("insufficient_funds",409)
    return 201,commit_move(fr,to,amt,note,vis,**links)
def page(xs,q,key):
    try:
        rawlim=q.get("limit",["50"])[0]; rawoff=q.get("offset",["0"])[0]
        if not isinstance(rawlim,str) or not isinstance(rawoff,str) or not rawlim.isdecimal() or not rawoff.isdecimal(): raise ValueError()
        lim=nint(int(rawlim),1,200); off=nint(int(rawoff),0,2**53)
    except: return None
    return {key:xs[off:off+lim],"has_more":off+lim<len(xs)}
def html():
    return "<!doctype html><html><head><meta charset=utf-8><title>InCarousel Pocketful</title></head><body><main><h1>InCarousel Pocketful</h1><p data-testid=auth-error hidden></p><input data-testid=login-email aria-label=Email><input data-testid=login-password aria-label=Password><button data-testid=login-submit>Log in</button><input data-testid=signup-email aria-label=Email><input data-testid=signup-password aria-label=Password><input data-testid=signup-display-name aria-label=Name><button data-testid=signup-submit>Sign up</button><p data-testid=current-user></p><p data-testid=current-handle></p><button data-testid=logout-button>Log out</button><p data-testid=wallet-balance data-amount=0>0.00 EUR</p><p data-testid=wallet-available data-amount=0>0.00 EUR</p><input data-testid=pay-handle><input data-testid=pay-amount><input data-testid=pay-note><select data-testid=pay-visibility><option value=public>Public</option><option value=private>Private</option></select><button data-testid=pay-submit>Pay</button><input data-testid=request-handle><input data-testid=request-amount><input data-testid=request-note><button data-testid=request-submit>Request</button><section data-testid=activity-list></section><section data-testid=incoming-list></section><section data-testid=outgoing-list></section><input data-testid=split-amount><input data-testid=split-handles><input data-testid=split-note><button data-testid=split-submit>Split</button><section data-testid=split-preview></section></main></body></html>"
class App(BaseHTTPRequestHandler):
 def log_message(self,*x): pass
 def send(self,s,o=None):
  self.send_response(s)
  if o is not None:
   raw=json.dumps(json_safe(o),ensure_ascii=False,allow_nan=False).encode();self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)))
  self.end_headers()
  if o is not None:self.wfile.write(raw)
 def read(self):
  try:return json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))).decode(),parse_float=Decimal,parse_int=Decimal,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
  except:return None
 def do_GET(self):
  u=urlparse(self.path);q=parse_qs(u.query,keep_blank_values=True)
  if u.path=="/health":return self.send(200,{"status":"ok"})
  if STAGE>=2 and (u.path.startswith("/assets/") or (self.headers.get("Accept","").find("text/html")>=0 and u.path in ("/","/requests","/split","/signup","/login","/authorizations"))):
   rel="index.html" if not u.path.startswith("/assets/") else u.path.lstrip("/")
   try:
    raw=open(os.path.join(os.path.dirname(__file__),rel),"rb").read()
    typ="text/html; charset=utf-8" if rel=="index.html" else ("text/css; charset=utf-8" if rel.endswith(".css") else "application/javascript; charset=utf-8" if rel.endswith(".js") else "font/woff2" if rel.endswith(".woff2") else "application/octet-stream")
    self.send_response(200);self.send_header("Content-Type",typ);self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw);return
   except OSError:return self.send(*fail("not_found",404))
  with LOCK:
   if u.path=="/_test/export":return self.send(200,{"track":"pocketful","format_version":STAGE,"state":export_state()})
   uid=auth(self)
   if not uid:return self.send(*fail("unauthenticated",401))
   expire()
   if u.path=="/me":
    d=user_me(uid)
    if STAGE>=3:
     for name in ("as_of","known_at"):
      if name in q:
       try:parse_instant(q[name][0]);d[name]=q[name][0]
       except:return self.send(*fail("validation_failed",422))
    return self.send(200,d)
   if u.path=="/activity":
    z=page(list(reversed([receipt(p) for p in S["payments"] if visible(p,uid)])),q,"payments");return self.send(200,z) if z else self.send(*fail("validation_failed",422))
   if u.path=="/requests":
    xs=[receipt(r) for r in S["requests"] if uid in (r["requester_id"],r["payer_id"])]
    direction=q.get("direction",[None])[0];status=q.get("status",[None])[0]
    if direction not in (None,"incoming","outgoing") or status not in (None,"pending","paid","declined","cancelled"):return self.send(*fail("validation_failed",422))
    if direction:xs=[r for r in xs if (r["payer_id"]==uid)==(direction=="incoming")]
    if status:xs=[r for r in xs if r["status"]==status]
    z=page(list(reversed(xs)),q,"requests");return self.send(200,z) if z else self.send(*fail("validation_failed",422))
   if u.path=="/authorizations" and STAGE>=2:
    xs=[receipt(a) for a in S["authorizations"] if uid in(a["from_user_id"],a["to_user_id"])]
    z=page(list(reversed(xs)),q,"authorizations");return self.send(200,z) if z else self.send(*fail("validation_failed",422))
   if u.path.startswith("/payments/") and u.path.endswith("/revisions") and STAGE>=3:
    p=getpay(u.path.split("/")[2]);return self.send(200,{"revisions":receipt(S["revisions"][p["payment_id"]])}) if p and uid in(p["from_user_id"],p["to_user_id"]) else self.send(*fail("not_found",404))
   if u.path=="/statement" and STAGE>=3:
    if "snapshot" in q:
     snap=S["snapshots"].get(q["snapshot"][0]);
     if not snap or snap["user"]!=uid:return self.send(*fail("not_found",404))
     return self.send(200,page(snap["entries"],q,"entries")|{"opening_balance":snap["opening_balance"],"closing_balance":snap["closing_balance"],"snapshot":q["snapshot"][0]})
    xs=[]; bal=0
    for p in sorted([p for p in S["payments"] if uid in(p["from_user_id"],p["to_user_id"])],key=lambda p:(p["created_at"],p["payment_id"])):
     d=p["amount"] if p["to_user_id"]==uid else -p["amount"];bal+=d;xs.append({"payment":receipt(p),"delta":d,"balance_after":bal,"revision":len(S["revisions"][p["payment_id"]]),"effective_at":p["created_at"],"recorded_at":p["created_at"]})
    token=ident("snap");S["snapshots"][token]={"user":uid,"entries":deepcopy(xs),"opening_balance":0,"closing_balance":bal};return self.send(200,page(xs,q,"entries")|{"opening_balance":0,"closing_balance":bal,"snapshot":token})
   return self.send(*fail("not_found",404))
 def do_POST(self):
  u=urlparse(self.path);b=self.read()
  if b is None and (u.path.endswith("/decline") or u.path.endswith("/cancel") or u.path.endswith("/void")): b={}
  if not isinstance(b,dict):return self.send(*fail("malformed_request",400))
  with LOCK:
   if u.path=="/_test/reset":
    try:init(b);return self.send(204)
    except:return self.send(*fail("validation_failed",422))
   if u.path=="/_test/import":
    try:
     if b.get("track")!="pocketful" or b.get("format_version") not in range(1,STAGE+1):raise ValueError()
     candidate=import_state(b.get("state"))
     S.clear();S.update(candidate);return self.send(204)
    except:return self.send(*fail("validation_failed",422))
   if u.path in ("/auth/login","/auth/signup"):
    if u.path.endswith("login"):
     x=next((x for x in S["users"].values() if x["email"]==b.get("email") and same_password(b.get("password"),x["password_hash"])),None)
     if not x:return self.send(*fail("unauthenticated",401))
    else:
     e,p,n=b.get("email"),b.get("password"),b.get("display_name")
     if not all(isinstance(x,str) for x in(e,p,n)) or not re.fullmatch(r"[^@\s]+@[^@\s]+",e) or len(p)<8:return self.send(*fail("validation_failed",422))
     if any(x["email"]==e for x in S["users"].values()):return self.send(*fail("email_taken",409))
     h=re.sub("[^a-z0-9_]","_",e.split("@")[0].lower())[:20]
     if h in S["handles"]:return self.send(*fail("handle_taken",409))
     i=ident("u");x={"id":i,"email":e,"password_hash":hpassword(p),"display_name":n,"handle":h,"total":0};S["users"][i]=x;S["handles"][h]=i
    t=secrets.token_urlsafe(24);S["tokens"][t]=x["id"];return self.send(201 if u.path.endswith("signup") else 200,{"user_id":x["id"],"display_name":x["display_name"],"token":t})
   uid=auth(self)
   if not uid:return self.send(*fail("unauthenticated",401))
   exp=(u.path in ("/payments","/requests","/splits","/settlements","/authorizations","/correction-batches") or u.path.endswith(("/pay","/capture","/corrections","/refunds")))
   ii,er=idem(self,uid,b) if exp else (None,None)
   if er:return self.send(*er)
   if exp and ii[0]=="replay":return self.send(200,receipt(ii[1]))
   if u.path=="/payments":
    try:
     amt=nint(b.get("amount"),1);note,vis=normal_fields(b);to_handle=b.get("to_handle")
     if not isinstance(to_handle,str):raise ValueError()
     to=S["handles"].get(to_handle)
    except:return self.send(*fail("validation_failed",422))
    if not to:return self.send(*fail("not_found",404))
    r=move(uid,to,amt,note,vis);return self.send(*done(ii,*r) if r[0]==201 else r)
   if u.path=="/requests":
    try:amt=nint(b.get("amount"),1);note=b.get("note","");to=S["handles"].get(b.get("payer_handle"));assert isinstance(note,str) and len(note)<=200
    except:return self.send(*fail("validation_failed",422))
    if not to:return self.send(*fail("not_found",404))
    if to==uid:return self.send(*fail("self_request",422))
    r={"request_id":ident("rq"),"requester_id":uid,"requester_handle":S["users"][uid]["handle"],"payer_id":to,"payer_handle":S["users"][to]["handle"],"amount":amt,"currency":S["currency"],"note":note,"status":"pending","payment_id":None,"created_at":instant()};S["requests"].append(r);return self.send(*done(ii,201,r))
   if u.path.endswith("/pay"):
    r=getreq(u.path.split("/")[2])
    if not r:return self.send(*fail("not_found",404))
    if r["payer_id"]!=uid:return self.send(*fail("forbidden",403))
    if r["status"]!="pending":return self.send(*fail("request_not_pending",409))
    try:vis=b.get("visibility","public");assert vis in ("public","private")
    except:return self.send(*fail("validation_failed",422))
    z=move(uid,r["requester_id"],r["amount"],"",vis,request_id=r["request_id"])
    if z[0]==201:r["status"]="paid";r["payment_id"]=z[1]["payment_id"];return self.send(*done(ii,*z))
    return self.send(*z)
   if u.path.endswith("/decline") or u.path.endswith("/cancel"):
    r=getreq(u.path.split("/")[2]);action="declined" if u.path.endswith("decline") else "cancelled";owner="payer_id" if action=="declined" else "requester_id"
    if not r:return self.send(*fail("not_found",404))
    if r[owner]!=uid:return self.send(*fail("forbidden",403))
    if r["status"]==action:return self.send(200,receipt(r))
    if r["status"]!="pending":return self.send(*fail("request_not_pending",409))
    r["status"]=action;return self.send(200,receipt(r))
   if u.path=="/splits":
    try:
     amt=nint(b.get("amount"),1);hs=b.get("participant_handles");note=b.get("note","")
     if not isinstance(hs,list) or not hs or not all(isinstance(x,str) for x in hs) or len(set(hs))!=len(hs) or not isinstance(note,str) or len(note)>200:raise ValueError()
    except:return self.send(*fail("validation_failed",422))
    if any(x not in S["handles"] for x in hs):return self.send(*fail("not_found",404))
    shares=[amt//len(hs)+(1 if i<amt%len(hs) else 0) for i in range(len(hs))];rs=[]
    for h,x in zip(hs,shares):
     if S["handles"][h]!=uid:rs.append({"request_id":ident("rq"),"requester_id":uid,"requester_handle":S["users"][uid]["handle"],"payer_id":S["handles"][h],"payer_handle":h,"amount":x,"currency":S["currency"],"note":note,"status":"pending","payment_id":None,"created_at":instant()});S["requests"].append(rs[-1])
    out={"split_id":ident("sp"),"amount":amt,"currency":S["currency"],"note":note,"shares":[{"handle":h,"amount":x} for h,x in zip(hs,shares)],"requests":rs,"created_at":instant()};return self.send(*done(ii,201,out))
   if u.path=="/settlements":
    if uid not in S["operators"]:return self.send(*fail("forbidden",403))
    ts=b.get("transfers")
    if not isinstance(ts,list) or not 1<=len(ts)<=32:return self.send(*fail("validation_failed",422))
    net={}
    try:
     for x in ts:
      fr=S["handles"][x["from_handle"]];to=S["handles"][x["to_handle"]];amt=nint(x["amount"],1);note,vis=normal_fields(x)
      if fr==to:return self.send(*fail("self_payment",422))
      net[fr]=net.get(fr,0)-amt;net[to]=net.get(to,0)+amt
     if any(balance(x)-held(x)+d<0 for x,d in net.items()):return self.send(*fail("insufficient_funds",409))
    except KeyError:return self.send(*fail("not_found",404))
    except:return self.send(*fail("validation_failed",422))
    sid=ident("st");committed=instant();out=[]
    for x in ts:
     out.append(commit_move(S["handles"][x["from_handle"]],S["handles"][x["to_handle"]],nint(x["amount"],1),x.get("note",""),x.get("visibility","public"),created_at=committed,settlement_id=sid))
    return self.send(*done(ii,201,{"settlement_id":sid,"committed_at":committed,"payments":out}))
   if u.path=="/authorizations" and STAGE>=2:
    try:amt=nint(b.get("amount"),1);note,vis=normal_fields(b);to=S["handles"].get(b.get("to_handle"))
    except:return self.send(*fail("validation_failed",422))
    if not to:return self.send(*fail("not_found",404))
    if to==uid:return self.send(*fail("self_payment",422))
    if balance(uid)-held(uid)<amt:return self.send(*fail("insufficient_funds",409))
    t=instant();a={"authorization_id":ident("a"),"from_user_id":uid,"from_handle":S["users"][uid]["handle"],"to_user_id":to,"to_handle":S["users"][to]["handle"],"amount":amt,"captured_amount":0,"remaining_amount":amt,"currency":S["currency"],"note":note,"visibility":vis,"status":"open","expires_at":(datetime.now(timezone.utc)+timedelta(seconds=S["ttl"])).isoformat(timespec="seconds"),"payment_id":None,"payment_ids":[],"created_at":t,"closed_at":None};S["authorizations"].append(a);return self.send(*done(ii,201,a))
   if u.path.endswith("/capture") and STAGE>=2:
    a=geta(u.path.split("/")[2]);
    if not a:return self.send(*fail("not_found",404))
    expire()
    if a["to_user_id"]!=uid:return self.send(*fail("forbidden",403))
    if a["status"]!="open":return self.send(*fail("authorization_expired" if a["status"]=="expired" else "authorization_not_open",409))
    try:amt=nint(b.get("amount",a["amount"]-a["captured_amount"]),1,a["amount"]-a["captured_amount"]);final=b.get("final",True);assert isinstance(final,bool)
    except:return self.send(*fail("capture_exceeds_authorization",422))
    z=move(a["from_user_id"],a["to_user_id"],amt,a["note"],a["visibility"],authorization_id=a["authorization_id"])
    if z[0]!=201:return self.send(*z)
    a["captured_amount"]+=amt;a["remaining_amount"]=a["amount"]-a["captured_amount"];a["payment_id"]=z[1]["payment_id"];a["payment_ids"].append(z[1]["payment_id"])
    if final or not a["remaining_amount"]:a["status"]="captured";a["remaining_amount"]=0;a["closed_at"]=instant()
    return self.send(*done(ii,*z))
   if u.path.endswith("/void") and STAGE>=2:
    a=geta(u.path.split("/")[2]);
    if not a:return self.send(*fail("not_found",404))
    if a["from_user_id"]!=uid:return self.send(*fail("forbidden",403))
    if a["status"]=="voided":return self.send(200,receipt(a))
    if a["status"]!="open":return self.send(*fail("authorization_not_open",409))
    a["status"]="voided";a["remaining_amount"]=0;a["closed_at"]=instant();return self.send(200,receipt(a))
   if u.path.endswith("/refunds") and STAGE>=4:
    p=getpay(u.path.split("/")[2])
    if not p:return self.send(*fail("not_found",404))
    if p["refund_of"]:return self.send(*fail("invalid_refund_target",422))
    if p["to_user_id"]!=uid:return self.send(*fail("forbidden",403))
    used=sum(x["amount"] for x in S["payments"] if x.get("refund_of")==p["payment_id"])
    try:amt=nint(b.get("amount"),1,p["amount"]-used)
    except:return self.send(*fail("refund_exceeds_payment",422))
    z=move(uid,p["from_user_id"],amt,p["note"],p["visibility"],refund_of=p["payment_id"]);return self.send(*done(ii,*z) if z[0]==201 else z)
   return self.send(*fail("not_found",404))
if __name__=="__main__": init({"currency":"EUR","minor_units":2,"users":[]});ThreadingHTTPServer(("0.0.0.0",int(os.environ.get("PORT","8080"))),App).serve_forever()
