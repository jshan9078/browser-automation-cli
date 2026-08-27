import os, subprocess, sys, time
sys.argv, _a = sys.argv[:1], sys.argv; import run as r; sys.argv=_a
URL=sys.argv[1] if len(sys.argv)>1 else "https://dash.cloudflare.com/login"
PY=r.PY; ENV=r.ENV
subprocess.run(["pkill","-f","daemon.server"],capture_output=True)
while subprocess.run(["pgrep","-f","daemon.server"],capture_output=True).returncode==0: time.sleep(0.1)
d=subprocess.Popen(r.DAEMON,env=ENV,stdout=subprocess.DEVNULL,stderr=open("/dev/null","w"))
while not r.SOCK.exists(): time.sleep(0.05)
time.sleep(0.3)
sid=subprocess.run([*r.CLI,"create"],capture_output=True,text=True,env=ENV).stdout.strip()
subprocess.run([*r.CLI,sid,"navigate",URL],capture_output=True,env=ENV)
for label,wait in (("t+3s",3),("t+10s",7),("t+20s",10)):
    time.sleep(wait); pids=r.descendants(d.pid); a=r.cputimes(pids); time.sleep(4); b=r.cputimes(pids)
    rows=sorted(((b[p][0]-a[p][0])/4*100, b[p][1]//1024, b[p][2][-50:]) for p in b if p in a)
    print(label, [(round(c,1),m,n) for c,m,n in rows if c>1][::-1])
print(subprocess.run([*r.CLI,"list"],capture_output=True,text=True,env=ENV).stdout)
d.terminate()
