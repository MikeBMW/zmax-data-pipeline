import subprocess, sys
host = 'tashan@' + '.'.join(['192','168','23','66'])

def ssh(cmd, timeout=120):
    r = subprocess.run(['ssh'] + [host, cmd], capture_output=True, text=True, timeout=timeout)
    return (r.stdout or '') + (r.stderr or '')

# find latest record dir
out = ssh("ls -td /home/tashan/.zmax/mcap/record_*/ | head -1").strip()
sys.stdout.write('LATEST_DIR: %s\n' % out)
if not out.startswith('/home/tashan/.zmax/mcap/record_'):
    sys.stdout.write('NO_RECORD_DIR\n')
    sys.exit(1)
# upload
up = ssh("python3 ~/.zmax/upload_data_v2.py %s" % out)
sys.stdout.write('UPLOAD_OUTPUT:\n%s\n' % up)
