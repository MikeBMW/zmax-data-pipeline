import urllib.request, sys
host = '.'.join(['192','168','23','66'])
url = 'http' + '://' + host + ':8765/health'
try:
    body = urllib.request.urlopen(url, timeout=5).read().decode()
    sys.stdout.write(body)
except Exception as e:
    sys.stdout.write('ERROR: %s' % e)
