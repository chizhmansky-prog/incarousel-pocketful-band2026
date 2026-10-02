import json, os, subprocess, sys, time, urllib.request

PORT = '18994'
p = subprocess.Popen([sys.executable, 'service.py'], env={**os.environ, 'PORT': PORT, 'POCKETFUL_STAGE': '4'})

def req(path, body=None, token=None, key=None):
    data = json.dumps(body, allow_nan=False).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    if key: headers['Idempotency-Key'] = key
    request = urllib.request.Request('http://127.0.0.1:' + PORT + path, data=data, headers=headers, method='POST' if data is not None else 'GET')
    try:
        r = urllib.request.urlopen(request)
        return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')

try:
    for _ in range(30):
        try:
            if req('/health')[0] == 200:
                break
        except Exception:
            time.sleep(.1)
    else:
        raise AssertionError('service did not become healthy')
    fixture = {'currency':'EUR','minor_units':2,'users':[
        {'id':'a','email':'a@x','password':'password1','display_name':'Ada','handle':'ada','balance':1000},
        {'id':'b','email':'b@x','password':'password1','display_name':'Bob','handle':'bob','balance':1000},
        {'id':'c','email':'c@x','password':'password1','display_name':'Cy','handle':'cy','balance':1000}],
        'settlement_operator_ids':['a']}
    assert req('/_test/reset', fixture)[0] == 204
    a = req('/auth/login', {'email':'a@x','password':'password1'})[1]['token']
    b = req('/auth/login', {'email':'b@x','password':'password1'})[1]['token']
    s, pay = req('/payments', {'to_handle':'bob','amount':300,'note':'rent'}, a, 'payment'); assert s == 201
    pid = pay['payment_id']
    s, correction = req('/payments/'+pid+'/corrections', {'expected_revision':1,'amount':200,'effective_at':pay['created_at'],'reason':'actual rent'}, a, 'correct'); assert s == 201 and correction['revision'] == 2
    assert req('/payments/'+pid+'/corrections', {'expected_revision':1,'amount':200,'effective_at':pay['created_at'],'reason':'actual rent'}, a, 'correct')[0] == 200
    s, revisions = req('/payments/'+pid+'/revisions', None, a); assert s == 200 and [x['amount'] for x in revisions['revisions']] == [300,200]
    s, statement = req('/statement', None, a); assert s == 200 and statement['entries'][0]['payment']['amount'] == 200
    snapshot = statement['snapshot']
    assert req('/payments/'+pid+'/refunds', {'amount':50}, b, 'refund')[0] == 201
    s, frozen = req('/statement?snapshot='+snapshot, None, a); assert s == 200 and frozen['entries'][0]['payment']['amount'] == 200
    s, settlement = req('/settlements', {'transfers':[{'from_handle':'ada','to_handle':'cy','amount':50},{'from_handle':'bob','to_handle':'cy','amount':50}]}, a, 'settlement'); assert s == 201
    corrections = [{'payment_id':x['payment_id'],'expected_revision':1,'amount':0,'effective_at':x['created_at'],'reason':'reverse'} for x in settlement['payments']]
    assert req('/correction-batches', {'corrections':corrections[:1]}, a, 'incomplete')[0] == 422
    assert req('/payments/'+settlement['payments'][0]['payment_id']+'/revisions', None, a)[1]['revisions'][-1]['revision'] == 1
    s, batch = req('/correction-batches', {'corrections':corrections}, a, 'batch'); assert s == 201 and len(batch['revisions']) == 2
    assert req('/correction-batches', {'corrections':corrections}, a, 'batch')[0] == 200
    print('PASS stage3/4: correction replay/revisions, selected statement snapshot, refund freeze, complete settlement batch replay')
finally:
    p.terminate(); p.wait()
