import urllib.request, sys
host = '.'.join(['192','168','23','66'])
url = 'http' + '://' + host + ':8765/record/start?duration=20'
req = urllib.request.Request(url, method='POST')
try:
    body = urllib.request.urlopen(req, timeout=15).read().decode()
    sys.stdout.write(body)
except Exception as e:
    sys.stdout.write('ERROR: %s' % e)
