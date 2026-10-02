"""Reset only a disposable loopback demo, then verify the three fixture logins."""
import argparse,ipaddress,json,pathlib,urllib.parse,urllib.request

def loopback_url(value):
    parsed=urllib.parse.urlsplit(value)
    try: local=ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError: local=parsed.hostname=='localhost'
    if parsed.scheme!='http' or not local or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise argparse.ArgumentTypeError('Use an HTTP loopback URL for a disposable local instance.')
    return value.rstrip('/')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',type=loopback_url,default='http://127.0.0.1:8080')
    a=p.parse_args()
    fixture=json.loads(pathlib.Path(__file__).with_name('seed.json').read_text())
    def post(path,body):
        q=urllib.request.Request(a.base_url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Accept':'application/json'},method='POST')
        with urllib.request.urlopen(q,timeout=10) as result:
            raw=result.read();return result.status,json.loads(raw) if raw else None
    status,_=post('/_test/reset',fixture)
    if status!=204:raise RuntimeError('Fixture reset did not return204.')
    for user in fixture['users']:
        status,body=post('/auth/login',{'email':user['email'],'password':user['password']})
        if status!=200 or not body.get('token'):raise RuntimeError('Fixture login failed.')
    print('Disposable demo ready. Open '+a.base_url+'/ and sign in as ada@example.test (fixture password). Three fixture logins verified; no real funds.')

if __name__=='__main__':main()
