"""Check every packaged file against the release file manifest (standard library only)."""
import csv,hashlib,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
    n=0
    with (ROOT/'FILE_MANIFEST.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            p=(ROOT/r['path']).resolve()
            if not p.is_relative_to(ROOT.resolve()):raise ValueError('invalid manifest path')
            h=hashlib.sha256()
            with p.open('rb') as q:
                for b in iter(lambda:q.read(1<<20),b''):h.update(b)
            if h.hexdigest()!=r['sha256'] or p.stat().st_size!=int(r['bytes']):raise ValueError('hash mismatch: '+r['path'])
            n+=1
    print(json.dumps({'package_file_hashes_checked':n,'status':'PASS','API_calls':0}))
if __name__=='__main__':main()
