#!/usr/bin/python3
"""Select the charge-only target only for a real USB-charger boot."""
import os,sys
from pathlib import Path

def should_charge(cmdline,board,entered):
 args={}
 for item in cmdline.split():
  key,sep,value=item.partition('=')
  if sep:args[key]=value
 return (b'lenovo,j716f' in board.split(b'\0') and not entered
         and args.get('androidboot.mode')=='charger'
         and args.get('androidboot.bootreason') in ['usb_chg','charger'])

def main():
 if len(sys.argv)<2 or os.environ.get('SYSTEMD_IN_INITRD')=='1':return
 entered=Path('/run/j716f-charge-only/enter-ubuntu').exists()
 if not should_charge(Path('/proc/cmdline').read_text(),Path('/sys/firmware/devicetree/base/compatible').read_bytes(),entered):return
 output=Path(sys.argv[2] if len(sys.argv)>2 else sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
 (output/'default.target').symlink_to('/etc/systemd/system/j716f-charge-only.target')
if __name__=='__main__':main()
