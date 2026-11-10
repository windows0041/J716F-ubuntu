#!/usr/bin/env python3
"""Inventory a read-only filesystem tree without publishing file contents."""
import argparse,base64,hashlib,json,os,stat,time
from pathlib import Path

def inventory(root):
    root=Path(root);out={};hashed={};total=0
    def visit(directory):
        nonlocal total
        with os.scandir(directory) as scan:entries=sorted(scan,key=lambda e:os.fsencode(e.name))
        for entry in entries:
            path=Path(entry.path);relative=path.relative_to(root).as_posix();st=entry.stat(follow_symlinks=False)
            row={'mode':st.st_mode,'uid':st.st_uid,'gid':st.st_gid,'mtime_ns':st.st_mtime_ns,'inode':st.st_ino,'nlink':st.st_nlink}
            attrs={}
            for n in sorted(os.listxattr(path,follow_symlinks=False)):
                attrs[n]=base64.b64encode(os.getxattr(path,n,follow_symlinks=False)).decode('ascii')
            row['xattrs']=attrs
            if stat.S_ISREG(st.st_mode):
                row['size']=st.st_size
                if st.st_ino not in hashed:
                    with path.open('rb') as f:
                        hashed[st.st_ino]=hashlib.file_digest(f,'sha256').hexdigest()
                        os.posix_fadvise(f.fileno(),0,0,os.POSIX_FADV_DONTNEED)
                    total+=st.st_size
                row['sha256']=hashed[st.st_ino]
            elif stat.S_ISLNK(st.st_mode):row['target']=os.readlink(path)
            elif stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):row['rdev']=st.st_rdev
            out[relative]=row
            if stat.S_ISDIR(st.st_mode):visit(path)
    visit(root)
    digest=hashlib.sha256(json.dumps(out,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'schema':1,'entries':out,'summary':{'entries':len(out),'regular_files':sum(stat.S_ISREG(x['mode']) for x in out.values()),'bytes_hashed':total,'canonical_sha256':digest}}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--compare',type=Path)
    args=ap.parse_args();start=time.monotonic()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result=inventory(args.root);args.output.write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n');os.chmod(args.output,0o600)
    summary=result['summary'];summary['seconds']=round(time.monotonic()-start,2)
    if args.compare:
        old=json.loads(args.compare.read_text())['entries'];now=result['entries']
        changed=[x for x in old.keys()&now.keys() if old[x]!=now[x]];removed=old.keys()-now.keys();added=now.keys()-old.keys()
        summary['comparison']={'changed':len(changed),'removed':len(removed),'added':len(added),'matches':not(changed or removed or added)}
        if changed or removed or added:
            print(json.dumps(summary));raise SystemExit(1)
    print(json.dumps(summary))

if __name__=='__main__':main()
