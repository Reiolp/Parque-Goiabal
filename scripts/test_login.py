import urllib.request, json
url = 'http://127.0.0.1:5000/api/login'
data = {'email':'testuser+1@example.com','senha':'secret123'}
b = json.dumps(data).encode('utf-8')
req = urllib.request.Request(url, data=b, headers={'Content-Type':'application/json'})
try:
    with urllib.request.urlopen(req) as r:
        print('STATUS', r.status)
        print(r.read().decode())
except Exception as e:
    import traceback
    print('ERROR', e)
    traceback.print_exc()
