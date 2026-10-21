"""Offline USBPcap evidence extraction; no device access and no executable loading."""
from pathlib import Path
import argparse, collections, hashlib, json
from parse_pcap import packets

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('captures',type=Path,nargs='+')
parser.add_argument('--output',type=Path,default=Path('evidence.json'))
args=parser.parse_args()
results = []
for capture in args.captures:
    name=capture.name
    data = capture.read_bytes()
    ps = list(packets(capture)); start = ps[0]['t']
    requests = [p for p in ps if p['fn'] == 27 and p['typ'] == 2]
    replies = [p for p in ps if p['ep'] == 0x82 and p['n'] == 17]
    invalid_requests = [p['index'] for p in requests if sum(p['payload'][8:]) % 256 != 0x55]
    invalid_replies = [p['index'] for p in replies if sum(p['payload']) % 256 != 0x55]
    selected = []
    for p in requests:
        d = p['payload'][8:]
        if d[1] not in (7, 0x0f): continue
        reply = next((q for q in replies if q['index'] > p['index'] and q['dev'] == p['dev'] and q['payload'] == d), None)
        selected.append(dict(packet=p['index'], time_s=round(p['t']-start,6), device=p['dev'], opcode=d[1], address=(d[3]<<8)|d[4], data=d[6:6+d[5]].hex(' '), report=d.hex(' '), exact_ack_packet=reply['index'] if reply else None, ack_latency_ms=round((reply['t']-p['t'])*1000,3) if reply else None))
    results.append(dict(capture=name, sha256=hashlib.sha256(data).hexdigest(), packet_count=len(ps), report_count=len(requests), replies=len(replies), request_opcode_counts=dict(collections.Counter(p['payload'][9] for p in requests)), invalid_request_checksums=invalid_requests, invalid_reply_checksums=invalid_replies, selected_transactions=selected))
args.output.write_text(json.dumps(results,indent=2),encoding='utf-8')
for r in results:
    print(r['capture'], 'requests',r['report_count'],'replies',r['replies'],'bad checksums',r['invalid_request_checksums'],r['invalid_reply_checksums'])
