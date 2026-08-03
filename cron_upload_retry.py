import subprocess, sys, time
host = 'tashan@' + '.'.join(['192','168','23','66'])
def ssh(cmd, timeout=180):
    r = subprocess.run(['ssh'] + [host, cmd], capture_output=True, text=True, timeout=timeout)
    return (r.stdout or '') + (r.stderr or '')
out = ssh("ls -td /home/tashan/.zmax/mcap/record_*/ | head -1").strip()
print('LATEST_DIR:', out)
for attempt in range(1, 4):
    up = ssh("python3 ~/.zmax/upload_data_v2.py %s" % out)
    print('--- attempt %d ---' % attempt)
    print(up)
    if '✅' in up or ('上传成功' in up) or ('成功' in up and '失败' not in up):
        print('RESULT: SUCCESS')
        sys.exit(0)
    time.sleep(15)
print('RESULT: FAILED_AFTER_RETRIES')
