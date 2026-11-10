#!/usr/bin/python3
"""Retry only a missing Lenovo J716F keyboard input endpoint at startup."""
import hashlib,json,os,time
from pathlib import Path
DEVICE=Path('/sys/bus/i2c/devices/4-0061')
DRIVER=Path('/sys/bus/i2c/drivers/i2c_hid_of')

def require(ok,message):
    if not ok:raise RuntimeError(message)

def snapshot():
    state={'present':DEVICE.exists(),'driver':None,'events':[],'hids':[]}
    if not state['present']:return state
    target=DEVICE.resolve()
    if (DEVICE/'driver').exists():state['driver']=(DEVICE/'driver').resolve().name
    for event in Path('/sys/class/input').glob('event*'):
        if target in event.resolve().parents:
            state['events'].append({'event':event.name,'name':(event/'device/name').read_text().strip()})
    for hid in DEVICE.glob('0018:17EF:610B.*'):
        data=(hid/'report_descriptor').read_bytes()
        state['hids'].append({'name':hid.name,'bound':(hid/'driver').exists(),'descriptor_bytes':len(data),'descriptor_sha256':hashlib.sha256(data).hexdigest()})
    return state

def decision(state):
    if not state['present']:return 'absent'
    if state['events']:return 'healthy'
    if state['driver'] is None:return 'probe'
    if state['driver']=='i2c_hid_of' and len(state['hids'])==1 and state['hids'][0]['bound']:return 'rebind'
    return 'wait'

def recover(read,unbind,probe,pause=time.sleep):
    result={'device':'4-0061','before':read(),'attempts':[]}
    for attempt in range(3):
        state=read();action=decision(state)
        if action in ['healthy','absent']:
            return dict(result,status=action,after=state)
        # Wait for an unchanged failure. A late input registration wins.
        pause(1);confirm=read()
        step={'attempt':attempt+1,'action':action}
        if confirm!=state:
            step['action']='state changed; wait'
        else:
            try:
                if action=='rebind':unbind();pause(.4);probe()
                elif action=='probe':probe()
            except OSError as e:step['error']=str(e)
        result['attempts'].append(step);pause(1)
    state=read();return dict(result,status=decision(state),after=state)

def validate():
    require(os.geteuid()==0,'root required')
    require(b'lenovo,j716f' in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0'),'J716F only')
    if DEVICE.exists():
        require(b'keyboard' in (DEVICE/'of_node/name').read_bytes(),'not the board keyboard')
        require('hid-over-i2c' in (DEVICE/'modalias').read_text(),'wrong transport')

def unbind():
    validate();require(decision(snapshot())=='rebind','keyboard is no longer missing its inputs')
    require((DEVICE/'driver').resolve()==DRIVER,'unexpected transport driver')
    (DRIVER/'unbind').write_text('4-0061\n')

def probe():
    validate();require(DEVICE.exists() and not (DEVICE/'driver').exists(),'transport already bound')
    Path('/sys/bus/i2c/drivers_probe').write_text('4-0061\n')

def main():
    os.umask(0o077);validate()
    uptime=float(Path('/proc/uptime').read_text().split()[0])
    if uptime<8:time.sleep(8-uptime)
    result=recover(snapshot,unbind,probe);result['time']=time.time()
    d=Path('/var/lib/j716f-input');d.mkdir(mode=0o700,parents=True,exist_ok=True)
    (d/'keyboard-last-probe.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return 0 if result['status'] in ['healthy','absent'] else 1

if __name__=='__main__':raise SystemExit(main())
