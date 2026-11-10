#!/usr/bin/python3
"""Prefer J716F primary PON so its power-key children can be instantiated."""
from pathlib import Path
import json,os,subprocess,time
BASE=Path('/sys/bus/platform/devices')
PRIMARY=BASE/'c440000.spmi:pmic@0:pon@800'
AUX=BASE/'c440000.spmi:pmic@a:pon@800'
DRIVER=Path('/sys/bus/platform/drivers/qcom-pon')
def need(ok,message):
 if not ok:raise RuntimeError(message)
def main():
 need(os.geteuid()==0,'root required')
 need(b'lenovo,j716f' in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0'),'J716F only')
 uptime=float(Path('/proc/uptime').read_text().split()[0])
 if uptime<8:time.sleep(8-uptime)
 need(PRIMARY.exists() and AUX.exists(),'unexpected PMIC layout')
 result={'primary_bound':(PRIMARY/'driver').exists(),'aux_bound':(AUX/'driver').exists(),'rebound':False}
 if not result['primary_bound']:
  need(b'qcom,pm8941-pwrkey' in (PRIMARY/'of_node/pwrkey/compatible').read_bytes(),'wrong power-key node')
  if (AUX/'driver').exists():
   need((AUX/'driver').resolve()==DRIVER,'unexpected auxiliary driver')
   need(not any(x.is_dir() for x in (AUX/'of_node').iterdir()),'auxiliary PON has children')
   (DRIVER/'unbind').write_text(AUX.name+'\n');time.sleep(.5)
  try:
   Path('/sys/bus/platform/drivers_probe').write_text(PRIMARY.name+'\n')
   need((PRIMARY/'driver').exists(),'primary did not bind')
  except BaseException:
   if not (AUX/'driver').exists():Path('/sys/bus/platform/drivers_probe').write_text(AUX.name+'\n')
   raise
  result['rebound']=True
 subprocess.run(['modprobe','pm8941_pwrkey'],check=True)
 result['primary_bound']=(PRIMARY/'driver').exists()
 result['input_names']=[(x/'device/name').read_text().strip() for x in Path('/sys/class/input').glob('event*') if 'pm8941' in (x/'device/name').read_text()]
 d=Path('/var/lib/j716f-input');d.mkdir(mode=0o700,exist_ok=True)
 (d/'primary-pon.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
