"""Verify all payload hashes and frozen references; no external API requests."""
import csv,json,pathlib,hashlib
from benchlib import ROOT,manifest,resolve_case,readjson,public_messages,safe_classify
def main():
 mf=ROOT/'FILE_MANIFEST.csv';n=0
 if mf.exists():
  with mf.open(encoding='utf-8-sig') as f:
   for r in csv.DictReader(f):
    p=(ROOT/r['path']).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('Unsafe path')
    if hashlib.file_digest(p.open('rb'),'sha256').hexdigest()!=r['sha256']:raise ValueError('File changed: '+r['path'])
    n+=1
 rows=manifest();seen=set()
 for r in rows:
  if r['case_uid'] in seen:raise ValueError('Duplicate UID')
  seen.add(r['case_uid']);public_messages(r);d=resolve_case(r['case_dir']);ref=readjson(d/'private/evaluation_reference_output.json')
  if not r.get('evaluation_eligible',True):continue
  v=safe_classify(r,json.dumps(ref))
  if v['category']!='CORRECT':raise ValueError(str((r['case_id'],v)))
 print(json.dumps({'all_file_hashes_checked':n,'cases_checked':len(rows),'reference_correct':sum(r.get('evaluation_eligible',True) for r in rows),'REVIEW':sum(not r.get('evaluation_eligible',True) for r in rows),'API_requests':0}))
if __name__=='__main__':main()
