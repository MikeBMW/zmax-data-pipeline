import subprocess, sys
host = 'tashan@' + '.'.join(['192','168','23','66'])
cmd = host + " \"bash -c 'source /opt/ros/humble/setup.bash && ros2 topic echo /motion/initialization_complete --once 2>&1'\""
try:
    r = subprocess.run(['ssh'] + [host, "bash -c 'source /opt/ros/humble/setup.bash && ros2 topic echo /motion/initialization_complete --once 2>&1'"],
                       capture_output=True, text=True, timeout=30)
    out = (r.stdout or '') + (r.stderr or '')
    sys.stdout.write(out)
except Exception as e:
    sys.stdout.write('SSH-ERROR: %s' % e)
