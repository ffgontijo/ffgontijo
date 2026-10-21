from pathlib import Path
import json,struct,collections

def packets(path):
 b=Path(path).read_bytes()
 if b[:4] != b'\xd4\xc3\xb2\xa1': raise ValueError('Expected little-endian pcap')
 pos=24; index=0
 while pos<len(b):
  sec,us,cap,orig=struct.unpack_from('<IIII',b,pos); pos+=16; d=b[pos:pos+cap];pos+=cap;index+=1
  if len(d)<27: continue
  hl,irp,status,fn,info,bus,dev,ep,typ,n=struct.unpack_from('<HQIHBHHBBI',d)
  yield dict(index=index,t=sec+us/1e6,hl=hl,irp=irp,status=status,fn=fn,info=info,bus=bus,dev=dev,ep=ep,typ=typ,n=n,stage=d[27] if hl>=28 else None,payload=d[hl:],raw=d)

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description='Read USBPcap classic captures offline.')
 parser.add_argument('captures',type=Path,nargs='+')
 parser.add_argument('--output',type=Path,default=Path.cwd())
 args=parser.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
 for capture in args.captures:
  name=capture.name
  ps=list(packets(capture)); print(name,len(ps))
  cnt=collections.Counter((p['bus'],p['dev'],p['ep'],p['typ'],p['fn'],p['stage'],p['n']) for p in ps)
  for k,v in cnt.most_common(60): print(k,v)
  lines=[]
  for p in ps:
   if p['typ']==2: lines.append(f"{p['index']:5} {p['t']-ps[0]['t']:11.6f} bus={p['bus']} dev={p['dev']} ep={p['ep']:02x} fn={p['fn']:04x} info={p['info']} stage={p['stage']} n={p['n']:3} status={p['status']:08x} {p['payload'].hex(' ')}")
  (out/(name+'.control.txt')).write_text('\n'.join(lines))
