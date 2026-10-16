import pathlib,json,hashlib,argparse
p=argparse.ArgumentParser();p.add_argument('root',nargs='?',default='.');a=p.parse_args();root=pathlib.Path(a.root).resolve();m=json.loads((root/'FILE_MANIFEST.json').read_text());bad=[]
for r in m:
 f=root/r['path']
 if not f.is_file() or f.stat().st_size!=r['bytes']:bad.append(r['path']);continue
 h=hashlib.sha256()
 with f.open('rb') as s:
  for b in iter(lambda:s.read(1048576),b''):h.update(b)
 if h.hexdigest()!=r['sha256']:bad.append(r['path'])
idx=[json.loads(s) for s in (root/'case_index.jsonl').read_text().splitlines()];print({'files_checked':len(m),'cases':len(idx),'unique_registered_keys':len({r['scientific_key'] for r in idx}),'bad_files':bad});raise SystemExit(bool(bad))
